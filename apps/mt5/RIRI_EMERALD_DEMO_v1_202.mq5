#property copyright "RIRI EMERALD"
#property version   "1.202"
#property strict

#include <Trade/Trade.mqh>

// This EA is intentionally demo-only. Real-account enablement does not exist in this build.
input string InpExpectedServer                 = "MetaQuotes-Demo";
input string InpExpectedSymbol                 = "XAUUSD";
input string InpExpectedCurrency               = "USD";
input long   InpExpectedLeverage               = 200;
input double InpExpectedInitialBalance         = 3000.0;
input long   InpMagicNumber                    = 26090202;
input string InpApiBaseUrl                     = "https://api-emerald.albiagent.com";
input string InpApiToken                       = "replace-me";
input int    InpTimerSeconds                   = 1;
input int    InpHttpTimeoutMilliseconds        = 2500;
input int    InpHeartbeatTimeoutSeconds        = 15;
input int    InpRecoveryHeartbeats             = 3;
input int    InpMaxTicksPerBatch               = 250;
input int    InpFlattenMinutesBeforeClose      = 10;
input double InpDailyLossStopPercent           = 20.0;
input double InpHighWaterHardStopPercent       = 50.0;
input double InpMaximumManagedLots             = 0.50;
input string InpManualHardStopReset             = "KEEP_LOCKED";

CTrade g_trade;

double   g_day_start_equity = 0.0;
double   g_equity_high_water = 0.0;
int      g_jakarta_day_key = 0;
long     g_last_sent_tick_msc = 0;
datetime g_last_healthy_api_local = 0;
int      g_consecutive_healthy_heartbeats = 0;
bool     g_api_fail_safe = true;
bool     g_risk_breach_latched = false;
bool     g_daily_stop = false;
bool     g_high_water_hard_stop = false;
string   g_incident_code = "STARTING";

string StateKey(const string suffix)
{
   return StringFormat("EMERALD.DEMO.%I64d.%I64d.%s",
                       AccountInfoInteger(ACCOUNT_LOGIN), InpMagicNumber, suffix);
}

string JsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   StringReplace(value, "\r", "\\r");
   StringReplace(value, "\n", "\\n");
   StringReplace(value, "\t", "\\t");
   return value;
}

string IsoUtcMillis(const long epoch_milliseconds)
{
   MqlDateTime value;
   TimeToStruct((datetime)(epoch_milliseconds / 1000), value);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02d.%03dZ",
                       value.year, value.mon, value.day, value.hour, value.min,
                       value.sec, (int)(epoch_milliseconds % 1000));
}

int JakartaDayKey()
{
   MqlDateTime value;
   TimeToStruct(TimeGMT() + 7 * 3600, value);
   return value.year * 10000 + value.mon * 100 + value.day;
}

double LossPercent(const double anchor, const double equity)
{
   if(anchor <= 0.0)
      return 100.0;
   return MathMax(0.0, (anchor - equity) / anchor * 100.0);
}

bool IsEmeraldPosition(const ulong ticket)
{
   if(ticket == 0 || !PositionSelectByTicket(ticket))
      return false;
   return PositionGetInteger(POSITION_MAGIC) == InpMagicNumber;
}

bool IsRolloverThesis(const ulong ticket)
{
   if(!PositionSelectByTicket(ticket))
      return false;
   return StringFind(PositionGetString(POSITION_COMMENT), "EMR|ROLL|") == 0;
}

double ManagedLots()
{
   double lots = 0.0;
   for(int index = PositionsTotal() - 1; index >= 0; --index)
   {
      const ulong ticket = PositionGetTicket(index);
      if(IsEmeraldPosition(ticket))
         lots += PositionGetDouble(POSITION_VOLUME);
   }
   return lots;
}

int ManagedPositions()
{
   int count = 0;
   for(int index = PositionsTotal() - 1; index >= 0; --index)
   {
      const ulong ticket = PositionGetTicket(index);
      if(IsEmeraldPosition(ticket))
         ++count;
   }
   return count;
}

void CancelEmeraldOrders()
{
   for(int index = OrdersTotal() - 1; index >= 0; --index)
   {
      const ulong ticket = OrderGetTicket(index);
      if(ticket == 0 || !OrderSelect(ticket))
         continue;
      if(OrderGetInteger(ORDER_MAGIC) != InpMagicNumber)
         continue;
      if(!g_trade.OrderDelete(ticket))
         PrintFormat("EMERALD order-delete failed ticket=%I64u retcode=%u message=%s",
                     ticket, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
   }
}

void CloseEmeraldPositions(const bool include_rollover)
{
   for(int index = PositionsTotal() - 1; index >= 0; --index)
   {
      const ulong ticket = PositionGetTicket(index);
      if(!IsEmeraldPosition(ticket))
         continue;
      if(!include_rollover && IsRolloverThesis(ticket))
         continue;
      if(!g_trade.PositionClose(ticket))
         PrintFormat("EMERALD position-close failed ticket=%I64u retcode=%u message=%s",
                     ticket, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
   }
}

void PersistRiskState()
{
   GlobalVariableSet(StateKey("DAY_START_EQUITY"), g_day_start_equity);
   GlobalVariableSet(StateKey("EQUITY_HIGH_WATER"), g_equity_high_water);
   GlobalVariableSet(StateKey("JAKARTA_DAY_KEY"), (double)g_jakarta_day_key);
   GlobalVariableSet(StateKey("DAILY_STOP"), g_daily_stop ? 1.0 : 0.0);
   GlobalVariableSet(StateKey("HWM_HARD_STOP"), g_high_water_hard_stop ? 1.0 : 0.0);
}

void LoadRiskState()
{
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   g_day_start_equity = GlobalVariableCheck(StateKey("DAY_START_EQUITY"))
                        ? GlobalVariableGet(StateKey("DAY_START_EQUITY")) : equity;
   g_equity_high_water = GlobalVariableCheck(StateKey("EQUITY_HIGH_WATER"))
                         ? GlobalVariableGet(StateKey("EQUITY_HIGH_WATER")) : equity;
   g_jakarta_day_key = GlobalVariableCheck(StateKey("JAKARTA_DAY_KEY"))
                       ? (int)GlobalVariableGet(StateKey("JAKARTA_DAY_KEY"))
                       : JakartaDayKey();
   g_daily_stop = GlobalVariableCheck(StateKey("DAILY_STOP"))
                  && GlobalVariableGet(StateKey("DAILY_STOP")) >= 1.0;
   g_high_water_hard_stop = GlobalVariableCheck(StateKey("HWM_HARD_STOP"))
                            && GlobalVariableGet(StateKey("HWM_HARD_STOP")) >= 1.0;

   if(InpManualHardStopReset == "RESET-DEMO-HARD-STOP")
   {
      g_high_water_hard_stop = false;
      g_equity_high_water = equity;
      Print("EMERALD manual high-water hard-stop reset accepted");
   }
   if(g_jakarta_day_key != JakartaDayKey())
   {
      g_jakarta_day_key = JakartaDayKey();
      g_day_start_equity = equity;
      g_daily_stop = false;
   }
   g_equity_high_water = MathMax(g_equity_high_water, equity);
   PersistRiskState();
}

void RefreshRiskState()
{
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   const int today = JakartaDayKey();
   if(today != g_jakarta_day_key)
   {
      g_jakarta_day_key = today;
      g_day_start_equity = equity;
      g_daily_stop = false;
      if(!g_high_water_hard_stop)
         g_incident_code = "NONE";
   }
   g_equity_high_water = MathMax(g_equity_high_water, equity);
   PersistRiskState();
}

void EnforceLocalRisk()
{
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   const double daily_loss = LossPercent(g_day_start_equity, equity);
   const double high_water_drawdown = LossPercent(g_equity_high_water, equity);

   if(high_water_drawdown >= InpHighWaterHardStopPercent)
   {
      g_high_water_hard_stop = true;
      g_incident_code = "HIGH_WATER_DRAWDOWN_50_PERCENT";
      CancelEmeraldOrders();
      CloseEmeraldPositions(true);
      PersistRiskState();
      return;
   }
   if(daily_loss >= InpDailyLossStopPercent)
   {
      g_daily_stop = true;
      g_incident_code = "DAILY_LOSS_20_PERCENT";
      CancelEmeraldOrders();
      CloseEmeraldPositions(true);
      PersistRiskState();
      return;
   }
   if(ManagedLots() > InpMaximumManagedLots + 0.000001)
   {
      g_risk_breach_latched = true;
      g_api_fail_safe = true;
      g_incident_code = "MANAGED_VOLUME_LIMIT_BREACH";
      CancelEmeraldOrders();
      CloseEmeraldPositions(true);
   }
}

int SecondsUntilSessionClose()
{
   const datetime server_now = TimeTradeServer();
   MqlDateTime now_value;
   TimeToStruct(server_now, now_value);
   const int now_seconds = now_value.hour * 3600 + now_value.min * 60 + now_value.sec;
   const ENUM_DAY_OF_WEEK day = (ENUM_DAY_OF_WEEK)now_value.day_of_week;

   for(uint session = 0; session < 32; ++session)
   {
      datetime session_from = 0;
      datetime session_to = 0;
      if(!SymbolInfoSessionTrade(_Symbol, day, session, session_from, session_to))
         break;

      MqlDateTime from_value;
      MqlDateTime to_value;
      TimeToStruct(session_from, from_value);
      TimeToStruct(session_to, to_value);
      const int from_seconds = from_value.hour * 3600 + from_value.min * 60 + from_value.sec;
      int to_seconds = to_value.hour * 3600 + to_value.min * 60 + to_value.sec;
      if(to_seconds <= from_seconds)
         to_seconds += 24 * 3600;

      int comparable_now = now_seconds;
      if(comparable_now < from_seconds && to_seconds > 24 * 3600)
         comparable_now += 24 * 3600;
      if(comparable_now >= from_seconds && comparable_now <= to_seconds)
         return to_seconds - comparable_now;
   }
   return -1;
}

void EnforcePreCloseFlatten()
{
   const int seconds_to_close = SecondsUntilSessionClose();
   if(seconds_to_close < 0 || seconds_to_close > InpFlattenMinutesBeforeClose * 60)
      return;
   CancelEmeraldOrders();
   CloseEmeraldPositions(false);
}

bool HttpPost(const string path, const string payload, string &response_text)
{
   const string url = InpApiBaseUrl + path;
   const string headers = "Content-Type: application/json\r\nAuthorization: Bearer "
                          + InpApiToken + "\r\n";
   char body[];
   char response[];
   string response_headers;
   StringToCharArray(payload, body, 0, WHOLE_ARRAY, CP_UTF8);
   if(ArraySize(body) > 0)
      ArrayResize(body, ArraySize(body) - 1);

   ResetLastError();
   const int status_code = WebRequest("POST", url, headers,
                                      InpHttpTimeoutMilliseconds, body,
                                      response, response_headers);
   response_text = CharArrayToString(response, 0, WHOLE_ARRAY, CP_UTF8);
   if(status_code >= 200 && status_code < 300)
      return true;
   PrintFormat("EMERALD HTTP failure path=%s status=%d terminal_error=%d response=%s",
               path, status_code, GetLastError(), response_text);
   return false;
}

string BrokerId()
{
   return AccountInfoString(ACCOUNT_COMPANY) + "|" + AccountInfoString(ACCOUNT_SERVER);
}

bool SendNewTicks()
{
   MqlTick ticks[];
   const ulong from_msc = (ulong)(g_last_sent_tick_msc == 0
                                  ? 0 : g_last_sent_tick_msc + 1);
   const int copied = CopyTicks(_Symbol, ticks, COPY_TICKS_INFO, from_msc,
                                (uint)MathMax(1, InpMaxTicksPerBatch));
   if(copied < 0)
   {
      PrintFormat("EMERALD CopyTicks failed error=%d", GetLastError());
      return false;
   }

   string items = "";
   long newest_msc = g_last_sent_tick_msc;
   int valid_count = 0;
   for(int index = 0; index < copied; ++index)
   {
      if(ticks[index].time_msc <= g_last_sent_tick_msc ||
         ticks[index].bid <= 0.0 || ticks[index].ask < ticks[index].bid)
         continue;
      if(valid_count > 0)
         items += ",";
      const string timestamp = IsoUtcMillis(ticks[index].time_msc);
      items += StringFormat(
         "{\"symbol\":\"%s\",\"bid\":%.8f,\"ask\":%.8f,"
         "\"broker_time\":\"%s\",\"observed_at\":\"%s\",\"volume\":%.2f}",
         JsonEscape(_Symbol), ticks[index].bid, ticks[index].ask,
         timestamp, timestamp, (double)ticks[index].volume_real
      );
      if(ticks[index].time_msc > newest_msc)
         newest_msc = ticks[index].time_msc;
      ++valid_count;
   }
   if(valid_count == 0)
      return true;

   const string payload = StringFormat(
      "{\"broker_id\":\"%s\",\"point\":%.10f,\"ticks\":[%s]}",
      JsonEscape(BrokerId()), SymbolInfoDouble(_Symbol, SYMBOL_POINT), items
   );
   string response;
   if(!HttpPost("/market/ticks", payload, response))
      return false;
   g_last_sent_tick_msc = newest_msc;
   return true;
}

string SystemState()
{
   if(g_high_water_hard_stop)
      return "HARD_STOP";
   if(g_daily_stop)
      return "DAILY_STOP";
   if(g_api_fail_safe || g_risk_breach_latched)
      return "FAIL_SAFE";
   return "ACTIVE";
}

string BuildHeartbeat()
{
   MqlTick tick;
   SymbolInfoTick(_Symbol, tick);
   const double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   return StringFormat(
      "{\"account_login\":%I64d,\"account_server\":\"%s\","
      "\"account_company\":\"%s\",\"account_currency\":\"%s\","
      "\"account_trade_mode\":\"DEMO\",\"margin_mode\":\"RETAIL_HEDGING\","
      "\"leverage\":%I64d,\"symbol\":\"%s\",\"digits\":%I64d,"
      "\"point\":%.10f,\"tick_size\":%.10f,\"tick_value_loss\":%.8f,"
      "\"volume_min\":%.4f,\"volume_max\":%.4f,\"volume_step\":%.4f,"
      "\"bid\":%.8f,\"ask\":%.8f,\"balance\":%.2f,\"equity\":%.2f,"
      "\"free_margin\":%.2f,\"margin_level\":%.2f,"
      "\"managed_positions\":%d,\"managed_lots\":%.4f,"
      "\"daily_loss_pct\":%.6f,\"high_water_drawdown_pct\":%.6f,"
      "\"seconds_until_session_close\":%d,\"system_state\":\"%s\","
      "\"incident\":\"%s\",\"terminal_connected\":%s,"
      "\"account_trade_allowed\":%s,\"expert_trade_allowed\":%s,"
      "\"server_time_epoch\":%I64d,\"jakarta_time_epoch\":%I64d}",
      AccountInfoInteger(ACCOUNT_LOGIN), JsonEscape(AccountInfoString(ACCOUNT_SERVER)),
      JsonEscape(AccountInfoString(ACCOUNT_COMPANY)),
      JsonEscape(AccountInfoString(ACCOUNT_CURRENCY)),
      AccountInfoInteger(ACCOUNT_LEVERAGE), JsonEscape(_Symbol),
      SymbolInfoInteger(_Symbol, SYMBOL_DIGITS), SymbolInfoDouble(_Symbol, SYMBOL_POINT),
      SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE),
      SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE_LOSS),
      SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN),
      SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX),
      SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP), tick.bid, tick.ask,
      AccountInfoDouble(ACCOUNT_BALANCE), equity,
      AccountInfoDouble(ACCOUNT_MARGIN_FREE), AccountInfoDouble(ACCOUNT_MARGIN_LEVEL),
      ManagedPositions(), ManagedLots(), LossPercent(g_day_start_equity, equity),
      LossPercent(g_equity_high_water, equity), SecondsUntilSessionClose(),
      SystemState(), JsonEscape(g_incident_code),
      TerminalInfoInteger(TERMINAL_CONNECTED) ? "true" : "false",
      AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) ? "true" : "false",
      AccountInfoInteger(ACCOUNT_TRADE_EXPERT) ? "true" : "false",
      (long)TimeTradeServer(), (long)(TimeGMT() + 7 * 3600)
   );
}

bool SendHeartbeat()
{
   string response;
   return HttpPost("/executor/heartbeat", BuildHeartbeat(), response);
}

bool ValidateDedicatedDemoAccount()
{
   bool valid = true;
   if((ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE)
      != ACCOUNT_TRADE_MODE_DEMO)
   {
      Print("EMERALD START REFUSED: this build accepts demo accounts only");
      valid = false;
   }
   if((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE)
      != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
   {
      Print("EMERALD START REFUSED: hedging account mode is required");
      valid = false;
   }
   if(AccountInfoString(ACCOUNT_SERVER) != InpExpectedServer)
   {
      PrintFormat("EMERALD START REFUSED: server '%s' does not equal '%s'",
                  AccountInfoString(ACCOUNT_SERVER), InpExpectedServer);
      valid = false;
   }
   if(_Symbol != InpExpectedSymbol)
   {
      PrintFormat("EMERALD START REFUSED: symbol '%s' does not equal '%s'",
                  _Symbol, InpExpectedSymbol);
      valid = false;
   }
   if(AccountInfoString(ACCOUNT_CURRENCY) != InpExpectedCurrency)
   {
      PrintFormat("EMERALD START REFUSED: account currency '%s' does not equal '%s'",
                  AccountInfoString(ACCOUNT_CURRENCY), InpExpectedCurrency);
      valid = false;
   }
   if(AccountInfoInteger(ACCOUNT_LEVERAGE) != InpExpectedLeverage)
   {
      PrintFormat("EMERALD START REFUSED: leverage %I64d does not equal %I64d",
                  AccountInfoInteger(ACCOUNT_LEVERAGE), InpExpectedLeverage);
      valid = false;
   }
   const double balance_delta = MathAbs(AccountInfoDouble(ACCOUNT_BALANCE)
                                        - InpExpectedInitialBalance);
   if(balance_delta > 0.01 && !GlobalVariableCheck(StateKey("DAY_START_EQUITY")))
      PrintFormat("EMERALD WARNING: first observed balance %.2f differs from configured %.2f",
                  AccountInfoDouble(ACCOUNT_BALANCE), InpExpectedInitialBalance);
   return valid;
}

bool ValidateDedicatedEmeraldApi()
{
   bool valid = true;
   if(StringFind(InpApiBaseUrl, "https://") != 0)
   {
      Print("EMERALD START REFUSED: production API must use HTTPS");
      valid = false;
   }
   if(StringFind(InpApiBaseUrl, "api-riri.albiagent.com") >= 0 ||
      StringFind(InpApiBaseUrl, "127.0.0.1") >= 0 ||
      StringFind(InpApiBaseUrl, "localhost") >= 0)
   {
      Print("EMERALD START REFUSED: RIRI and localhost API targets are forbidden");
      valid = false;
   }
   if(StringLen(InpApiToken) < 32 || InpApiToken == "replace-me")
   {
      Print("EMERALD START REFUSED: configure the dedicated EMERALD API token");
      valid = false;
   }
   return valid;
}

void PrintTradingSessions()
{
   for(int day = MONDAY; day <= FRIDAY; ++day)
   {
      for(uint session = 0; session < 32; ++session)
      {
         datetime session_from = 0;
         datetime session_to = 0;
         if(!SymbolInfoSessionTrade(_Symbol, (ENUM_DAY_OF_WEEK)day, session,
                                    session_from, session_to))
            break;
         PrintFormat("EMERALD SESSION day=%s index=%u from=%s to=%s server-time",
                     EnumToString((ENUM_DAY_OF_WEEK)day), session,
                     TimeToString(session_from, TIME_MINUTES),
                     TimeToString(session_to, TIME_MINUTES));
      }
   }
}

int OnInit()
{
   if(!ValidateDedicatedDemoAccount() || !ValidateDedicatedEmeraldApi())
      return INIT_FAILED;

   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetAsyncMode(false);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   LoadRiskState();
   PrintTradingSessions();
   g_last_healthy_api_local = TimeLocal();
   EventSetTimer(MathMax(1, InpTimerSeconds));
   Print("RIRI EMERALD DEMO v1.202 initialized; production telemetry enabled, entries locked");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   PersistRiskState();
   PrintFormat("RIRI EMERALD DEMO stopped reason=%d", reason);
}

void OnTick()
{
   RefreshRiskState();
   EnforceLocalRisk();
   EnforcePreCloseFlatten();
}

void OnTimer()
{
   RefreshRiskState();
   EnforceLocalRisk();
   EnforcePreCloseFlatten();

   const bool ticks_ok = SendNewTicks();
   const bool heartbeat_ok = SendHeartbeat();
   if(heartbeat_ok)
   {
      g_last_healthy_api_local = TimeLocal();
      ++g_consecutive_healthy_heartbeats;
   }
   else
      g_consecutive_healthy_heartbeats = 0;

   const bool heartbeat_fresh =
      (TimeLocal() - g_last_healthy_api_local) <= InpHeartbeatTimeoutSeconds;
   if(!heartbeat_fresh)
   {
      g_api_fail_safe = true;
      g_incident_code = "API_HEARTBEAT_EXPIRED";
      CancelEmeraldOrders();
   }
   else if(!ticks_ok)
   {
      g_api_fail_safe = true;
      g_incident_code = "TICK_INGESTION_FAILED";
      CancelEmeraldOrders();
   }
   else if(!g_high_water_hard_stop && !g_daily_stop
           && ManagedLots() <= InpMaximumManagedLots + 0.000001
           && g_consecutive_healthy_heartbeats >= InpRecoveryHeartbeats)
   {
      g_api_fail_safe = false;
      g_risk_breach_latched = false;
      g_incident_code = "NONE";
   }
}
