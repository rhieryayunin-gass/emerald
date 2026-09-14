export type Health = {
  service: string;
  status: string;
  environment: string;
  real_trading_allowed: boolean;
  probability_model_ready: boolean;
  version: string;
};

export type ExecutorStatus = {
  account_login: number;
  account_server: string;
  system_state: string;
  incident: string;
  heartbeat_age_seconds: number;
  healthy: boolean;
};

export type TickStream = {
  broker_id: string;
  symbol: string;
  stored_ticks: number;
  latest_bid?: number;
  latest_ask?: number;
  latest_broker_time: string;
  latest_observed_at: string;
  tick_age_seconds: number;
  healthy: boolean;
};

export type TelemetryReadiness = {
  telemetry_ready: boolean;
  entry_ready: boolean;
  blockers: string[];
  expected_profile: {
    server: string;
    symbol: string;
    leverage: number;
    timezone: string;
  };
  executors: ExecutorStatus[];
  tick_streams: TickStream[];
};

export type ModeMetric = {
  strategy_mode: string;
  total_events: number;
  confirmed_events: number;
  pending_events: number;
  target_hits: number;
  stop_hits: number;
  censored_events: number;
  filtered_events: number;
  resolved_outcomes: number;
  observed_target_rate: number | null;
  wilson_95_interval: [number, number];
  minimum_samples: number;
  sample_gate_met: boolean;
};

export type ShadowMetrics = {
  modes: ModeMetric[];
  all_sample_gates_met: boolean;
  probability_model_ready: boolean;
  calibration_ready: boolean;
  notice: string;
};

export type Incident = {
  incident_id: string;
  severity: string;
  component: string;
  code: string;
  status: string;
  started_at: string;
  details: Record<string, unknown>;
};

export type ShadowEvent = {
  event_id: string;
  broker_id: string;
  symbol: string;
  strategy_mode: string;
  shadow_tier: string;
  direction: string;
  confirmed: number;
  spread_artifact: number;
  detector_version: string;
  label_status: string;
  created_at: string;
  labelled_at: string | null;
  payload: Record<string, unknown>;
  outcome: Record<string, unknown> | null;
};

export type DashboardSnapshot = {
  fetched_at: string;
  health: Health | null;
  calibration: CalibrationStatus | null;
  telemetry: TelemetryReadiness | null;
  metrics: ShadowMetrics | null;
  incidents: Incident[];
  events: ShadowEvent[];
  errors: string[];
};


export type CalibrationCohort = {
  key: string[];
  strategy_mode: string;
  shadow_tier: string;
  direction: string;
  status: string;
  usable_samples: number;
  minimum_samples: number;
  split_counts: { train: number; calibration: number; test: number; purged: number };
  blockers: string[];
  validation: {
    brier_score: number;
    baseline_brier_score: number;
    calibration_error: number;
    selected_samples: number;
    selected_target_rate: number | null;
    mean_net_r: number | null;
    conservative_ev_points: number | null;
  } | null;
};

export type CalibrationStatus = {
  status: string;
  artifact_id?: string;
  created_at?: string;
  expires_at?: string;
  probability_model_ready: boolean;
  entry_ready: boolean;
  audit?: { total_rows: number; usable_samples: number; excluded: Record<string, number> };
  eligible_cohorts?: number;
  missing_modes?: string[];
  blockers: string[];
  cohorts: CalibrationCohort[];
};
