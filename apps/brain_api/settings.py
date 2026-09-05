from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: Literal["demo", "real"] = "demo"
    allow_real_trading: bool = False
    api_token: str = "development-only-change-me"
    journal_path: str = "data/emerald.db"
    expected_account_server: str = "MetaQuotes-Demo"
    expected_symbol: str = "XAUUSD"
    expected_leverage: int = 200
    probability_model_ready: bool = False
    executor_heartbeat_max_age_seconds: float = 10.0
    tick_stream_max_age_seconds: float = 5.0
    minimum_calibration_samples_per_mode: int = 100
    expose_api_docs: bool = True
    trusted_hosts: str = "*"

    @property
    def trusted_host_list(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]

    @model_validator(mode="after")
    def secure_when_api_docs_are_disabled(self) -> "Settings":
        if not self.expose_api_docs:
            if len(self.api_token) < 32 or self.api_token == "development-only-change-me":
                raise ValueError("production-style deployment requires a dedicated API token")
            if self.trusted_host_list == ["*"]:
                raise ValueError("production-style deployment requires explicit trusted hosts")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="EMERALD_",
        extra="ignore",
    )
