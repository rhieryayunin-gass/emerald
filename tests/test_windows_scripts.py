from pathlib import Path

SCRIPTS = Path("scripts/windows")


def test_telemetry_checker_does_not_print_api_token() -> None:
    source = (SCRIPTS / "Check-EmeraldProduction.ps1").read_text(encoding="utf-8")
    assert "/telemetry/readiness" in source
    assert "/shadow/metrics" in source
    assert "Write-Host $ApiToken" not in source
    assert "https://api-emerald.albiagent.com" in source
    assert "-AsSecureString" in source
    assert "entry_ready" in source
    assert "calibration_ready" in source
