from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TickPayload(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    symbol: str = Field(min_length=1, max_length=32)
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)
    broker_time: datetime
    observed_at: datetime
    volume: float = Field(default=0.0, ge=0)

    @field_validator("broker_time", "observed_at")
    @classmethod
    def timestamp_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a UTC offset")
        return value


class TickBatchPayload(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    broker_id: str = Field(min_length=1, max_length=100)
    point: float = Field(gt=0)
    ticks: list[TickPayload] = Field(min_length=1, max_length=5000)


class ExecutorHeartbeatPayload(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    account_login: int = Field(gt=0)
    account_server: str = Field(min_length=1, max_length=100)
    account_company: str = Field(min_length=1, max_length=100)
    account_currency: str = Field(min_length=3, max_length=10)
    account_trade_mode: Literal["DEMO"]
    margin_mode: Literal["RETAIL_HEDGING"]
    leverage: int = Field(gt=0)
    symbol: str = Field(min_length=1, max_length=32)
    digits: int = Field(ge=0, le=12)
    point: float = Field(gt=0)
    tick_size: float = Field(gt=0)
    tick_value_loss: float = Field(ge=0)
    volume_min: float = Field(gt=0)
    volume_max: float = Field(gt=0)
    volume_step: float = Field(gt=0)
    bid: float = Field(ge=0)
    ask: float = Field(ge=0)
    balance: float = Field(ge=0)
    equity: float = Field(ge=0)
    free_margin: float
    margin_level: float = Field(ge=0)
    managed_positions: int = Field(ge=0)
    managed_lots: float = Field(ge=0)
    daily_loss_pct: float = Field(ge=0)
    high_water_drawdown_pct: float = Field(ge=0)
    seconds_until_session_close: int = Field(ge=-1)
    system_state: Literal["ACTIVE", "FAIL_SAFE", "DAILY_STOP", "HARD_STOP"]
    incident: str = Field(min_length=1, max_length=100)
    terminal_connected: bool
    account_trade_allowed: bool
    expert_trade_allowed: bool
    server_time_epoch: int = Field(ge=0)
    jakarta_time_epoch: int = Field(gt=0)

    @field_validator("account_currency", "symbol")
    @classmethod
    def normalize_uppercase(cls, value: str) -> str:
        return value.strip().upper()
