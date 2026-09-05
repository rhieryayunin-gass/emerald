import pytest

from emerald.domain import SystemState
from emerald.failsafe import FailSafeAction, FailSafeController, HealthSnapshot, LocalRiskSnapshot
from emerald.strategies import SetupState, SetupStateMachine


def healthy() -> HealthSnapshot:
    return HealthSnapshot(
        ai_heartbeat_age_seconds=1.0,
        api_heartbeat_age_seconds=1.0,
        market_data_age_seconds=0.2,
        mt5_connected=True,
        state_reconciled=True,
    )


def safe_risk(**overrides: object) -> LocalRiskSnapshot:
    values = {
        "daily_loss_fraction": 0.0,
        "overall_drawdown_fraction": 0.0,
        "margin_level": 1000.0,
        "rollover_flatten_due": False,
        "has_regular_positions": False,
    }
    values.update(overrides)
    return LocalRiskSnapshot(**values)


def test_setup_state_machine_accepts_valid_flow() -> None:
    machine = SetupStateMachine()
    for state in (
        SetupState.CANDIDATE,
        SetupState.CONFIRMING,
        SetupState.APPROVED,
        SetupState.ACTIVE,
        SetupState.EXITING,
        SetupState.CLOSED,
    ):
        machine.transition(state)
    assert machine.state is SetupState.CLOSED


def test_setup_state_machine_rejects_illegal_transition() -> None:
    machine = SetupStateMachine()
    with pytest.raises(ValueError):
        machine.transition(SetupState.ACTIVE)


def test_healthy_system_allows_new_entries() -> None:
    decision = FailSafeController().evaluate(healthy(), safe_risk())
    assert decision.system_state is SystemState.ACTIVE
    assert decision.allow_new_entries is True


def test_ai_outage_blocks_entries_without_forcing_close() -> None:
    failed = HealthSnapshot(
        ai_heartbeat_age_seconds=30.0,
        api_heartbeat_age_seconds=1.0,
        market_data_age_seconds=0.2,
        mt5_connected=True,
        state_reconciled=True,
    )
    decision = FailSafeController().evaluate(failed, safe_risk())
    assert decision.system_state is SystemState.FAIL_SAFE
    assert decision.allow_new_entries is False
    assert FailSafeAction.BLOCK_NEW_ENTRIES in decision.actions
    assert FailSafeAction.EMERGENCY_CLOSE_ALL not in decision.actions


def test_daily_loss_triggers_emergency_close() -> None:
    decision = FailSafeController().evaluate(healthy(), safe_risk(daily_loss_fraction=0.20))
    assert decision.system_state is SystemState.HARD_STOP
    assert FailSafeAction.EMERGENCY_CLOSE_ALL in decision.actions


def test_rollover_due_closes_regular_positions() -> None:
    decision = FailSafeController().evaluate(
        healthy(),
        safe_risk(rollover_flatten_due=True, has_regular_positions=True),
    )
    assert decision.allow_new_entries is False
    assert FailSafeAction.CLOSE_REGULAR_FOR_ROLLOVER in decision.actions
