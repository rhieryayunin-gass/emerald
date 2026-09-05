import pytest
from pydantic import ValidationError

from apps.brain_api.settings import Settings


def test_production_style_settings_require_dedicated_token() -> None:
    with pytest.raises(ValidationError, match="dedicated API token"):
        Settings(_env_file=None, expose_api_docs=False, trusted_hosts="api-emerald.albiagent.com")


def test_production_style_settings_require_explicit_trusted_hosts() -> None:
    with pytest.raises(ValidationError, match="explicit trusted hosts"):
        Settings(
            _env_file=None,
            expose_api_docs=False,
            api_token="a" * 64,
            trusted_hosts="*",
        )


def test_production_style_settings_accept_isolated_profile() -> None:
    settings = Settings(
        _env_file=None,
        expose_api_docs=False,
        api_token="a" * 64,
        trusted_hosts="api-emerald.albiagent.com,127.0.0.1",
    )
    assert settings.trusted_host_list == ["api-emerald.albiagent.com", "127.0.0.1"]
