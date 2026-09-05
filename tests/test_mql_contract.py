from pathlib import Path

EA_PATH = Path("apps/mt5/RIRI_EMERALD_DEMO_v1_202.mq5")


def ea_source() -> str:
    return EA_PATH.read_text(encoding="utf-8")


def test_only_new_emerald_demo_ea_is_distributed() -> None:
    assert EA_PATH.exists()
    assert not Path("apps/mt5/RIRI_EMERALD_DEMO.mq5").exists()
    assert not Path("apps/mt5/RIRI_EMERALD_DEMO_v0_200.mq5").exists()
    assert not Path("apps/mt5/RIRI_EMERALD_EXECUTOR.mq5").exists()


def test_ea_has_no_real_account_override() -> None:
    source = ea_source()
    assert "ACCOUNT_TRADE_MODE_DEMO" in source
    assert "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING" in source
    assert "InpAllowRealTrading" not in source
    assert "ACCOUNT_TRADE_MODE_REAL" not in source


def test_ea_profile_and_api_contract_are_locked() -> None:
    source = ea_source()
    for expected in (
        '#property version   "1.202"',
        'InpExpectedServer                 = "MetaQuotes-Demo"',
        'InpExpectedSymbol                 = "XAUUSD"',
        "InpExpectedLeverage               = 200",
        'HttpPost("/market/ticks"',
        'HttpPost("/executor/heartbeat"',
        "SymbolInfoSessionTrade",
        "CopyTicks",
        'InpApiBaseUrl                     = "https://api-emerald.albiagent.com"',
        'StringFind(InpApiBaseUrl, "api-riri.albiagent.com")',
        'StringFind(InpApiBaseUrl, "127.0.0.1")',
    ):
        assert expected in source


def test_ea_local_risk_fallback_is_present() -> None:
    source = ea_source()
    for expected in (
        "InpDailyLossStopPercent           = 20.0",
        "InpHighWaterHardStopPercent       = 50.0",
        "InpMaximumManagedLots             = 0.50",
        "CancelEmeraldOrders();",
        "CloseEmeraldPositions(true);",
        'InpManualHardStopReset == "RESET-DEMO-HARD-STOP"',
    ):
        assert expected in source
