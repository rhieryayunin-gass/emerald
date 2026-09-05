from dataclasses import dataclass
from enum import StrEnum


class SetupState(StrEnum):
    OBSERVING = "OBSERVING"
    CANDIDATE = "CANDIDATE"
    CONFIRMING = "CONFIRMING"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SCALING = "SCALING"
    EXITING = "EXITING"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


ALLOWED_TRANSITIONS: dict[SetupState, frozenset[SetupState]] = {
    SetupState.OBSERVING: frozenset({SetupState.CANDIDATE}),
    SetupState.CANDIDATE: frozenset({SetupState.CONFIRMING, SetupState.REJECTED}),
    SetupState.CONFIRMING: frozenset({SetupState.APPROVED, SetupState.REJECTED}),
    SetupState.APPROVED: frozenset({SetupState.ACTIVE, SetupState.REJECTED}),
    SetupState.ACTIVE: frozenset({SetupState.SCALING, SetupState.EXITING}),
    SetupState.SCALING: frozenset({SetupState.ACTIVE, SetupState.EXITING}),
    SetupState.EXITING: frozenset({SetupState.CLOSED}),
    SetupState.CLOSED: frozenset(),
    SetupState.REJECTED: frozenset(),
}


@dataclass(slots=True)
class SetupStateMachine:
    state: SetupState = SetupState.OBSERVING

    def transition(self, target: SetupState) -> None:
        if target not in ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"illegal setup transition: {self.state} -> {target}")
        self.state = target
