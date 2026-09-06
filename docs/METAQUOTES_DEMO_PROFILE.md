# MetaQuotes Demo Profile

This profile is locked for the first EMERALD deployment.

| Property | Required value |
| --- | --- |
| Environment | Windows PC |
| Broker/company | MetaQuotes Ltd. (reported value is telemetry only) |
| Server | `MetaQuotes-Demo` |
| Symbol | `XAUUSD` |
| Account trade mode | Demo |
| Position accounting | Retail hedging |
| Currency | USD |
| Leverage | 1:200 |
| Expected starting balance | USD 3,000 |
| User/dashboard timezone | GMT+7 / Asia-Jakarta |

The EA discovers the actual XAUUSD sessions from the terminal instead of
assuming a fixed rollover clock. It prints every Monday-Friday trading session
reported by the server during initialization. This is necessary because GMT+7
is a display/risk-day timezone, while symbol sessions are defined in broker
server time and may change.

## First production telemetry test

1. Log in to the dedicated MetaQuotes demo account in MT5.
2. Open an XAUUSD chart and confirm the account is hedging with leverage 1:200.
3. Open MetaEditor and compile `RIRI_EMERALD_DEMO_v1_202.mq5`. The build must
   report `code generated` and zero errors.
4. In MT5, open Tools > Options > Expert Advisors and add
   `https://api-emerald.albiagent.com` to the allowed WebRequest URLs.
5. Enter the dedicated EMERALD API token in `InpApiToken`. Do not reuse the RIRI
   API credential.
6. Attach the EA to XAUUSD. Keep AutoTrading disabled for the first telemetry
   smoke test; tick ingestion, heartbeat, session discovery, and incidents can
   still be inspected before any execution protocol exists.
7. In a second PowerShell window run
   `scripts\windows\Check-EmeraldProduction.ps1`. Enter the token only in the
   secure prompt. `telemetry_ready=true` means heartbeat and Bid/Ask ticks are
   live. `entry_ready=false` is expected until the probability model has passed
   calibration. The same script reports shadow sample counts and outcome
   intervals for each strategy mode.

Never paste the MT5 password or API token into chat, source control, logs, or
screenshots.
