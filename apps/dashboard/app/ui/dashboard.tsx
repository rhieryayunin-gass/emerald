"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import type { DashboardSnapshot, ModeMetric, ShadowEvent } from "@/lib/types";

const calibrationReasons: Record<string, string> = {
  INSUFFICIENT_INDEPENDENT_SAMPLES: "Sampel peluang independen belum cukup",
  INSUFFICIENT_TIME_SPLIT: "Data pada periode pelatihan atau pengujian belum cukup",
  INSUFFICIENT_CLASS_COVERAGE: "Contoh target dan stop belum cukup untuk melatih model",
  INCOMPLETE_HISTORICAL_OUTCOMES: "Ada peluang historis yang hasilnya belum lengkap",
  NO_OUT_OF_TIME_PROBABILITY_SKILL: "Prediksi belum mengungguli pembanding pada data pengujian",
  CALIBRATION_ERROR_ABOVE_10_PERCENT: "Selisih probabilitas dan hasil aktual masih terlalu besar",
  INSUFFICIENT_80_PERCENT_VALIDATION_SIGNALS: "Sinyal dengan probabilitas 80% belum cukup teruji",
  VALIDATION_TARGET_RATE_BELOW_80_PERCENT: "Hasil sinyal terpilih belum mencapai target 80%",
  NONPOSITIVE_VALIDATION_EXPECTANCY: "Hasil rata-rata setelah biaya belum positif",
  UNCERTAIN_EXPECTANCY_AFTER_COSTS: "Keuntungan setelah biaya belum cukup meyakinkan",
  EXECUTION_COSTS_NOT_CONFIGURED: "Asumsi komisi dan slippage belum diisi",
  MARKET_CLOCK_AHEAD_OF_LABEL_CLOCK: "Waktu harga mendahului waktu pencatatan hasil. Sampel ini ditolak karena sesi rollover/news belum dapat dipercaya. Perbarui EA dan periksa jam Windows.",
};

const modeLabels: Record<string, string> = {
  REGULAR_MISMATCH: "Regular mismatch",
  ROLLOVER_REVERSAL: "Rollover reversal",
  NEWS_REVERSAL: "News reversal",
};

function formatPercent(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function formatJakarta(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("id-ID", {
    timeZone: "Asia/Jakarta",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function statusClass(ok: boolean | undefined): string {
  return ok ? "status good" : "status locked";
}

function MetricCard({ metric }: { metric: ModeMetric }) {
  const progress = Math.min(100, (metric.resolved_outcomes / metric.minimum_samples) * 100);
  return (
    <article className="mode-card">
      <div className="mode-heading">
        <div>
          <p className="mode-code">{metric.strategy_mode}</p>
          <h3>{modeLabels[metric.strategy_mode] ?? metric.strategy_mode}</h3>
        </div>
        <span className={statusClass(metric.sample_gate_met)}>
          {metric.sample_gate_met ? "Sample ready" : "Collecting"}
        </span>
      </div>
      <div className="rate-row">
        <strong>{formatPercent(metric.observed_target_rate)}</strong>
        <span>observed target rate</span>
      </div>
      <div className="progress-track" aria-label={`${progress.toFixed(0)}% sample progress`}>
        <span style={{ width: `${progress}%` }} />
      </div>
      <div className="mode-stats">
        <span><b>{metric.resolved_outcomes}</b> / {metric.minimum_samples} resolved</span>
        <span><b>{metric.target_hits}</b> target</span>
        <span><b>{metric.stop_hits}</b> stop</span>
      </div>
      <p className="interval">
        Wilson 95%: {formatPercent(metric.wilson_95_interval[0])}–{formatPercent(metric.wilson_95_interval[1])}
      </p>
    </article>
  );
}

function EventRow({ event }: { event: ShadowEvent }) {
  return (
    <tr>
      <td>{formatJakarta(event.created_at)}</td>
      <td>{modeLabels[event.strategy_mode] ?? event.strategy_mode}<br /><small>{event.shadow_tier}</small></td>
      <td><span className={`direction ${event.direction.toLowerCase()}`}>{event.direction}</span></td>
      <td><span className={`label ${event.label_status.toLowerCase()}`}>{event.label_status}</span></td>
      <td>{event.detector_version}</td>
    </tr>
  );
}

export default function Dashboard() {
  const router = useRouter();
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/dashboard", { cache: "no-store" });
      if (response.status === 401) {
        router.replace("/login");
        return;
      }
      setSnapshot((await response.json()) as DashboardSnapshot);
    } catch {
      setSnapshot((current) => current ? { ...current, errors: ["Frontend cannot reach its secure data route"] } : null);
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const executor = snapshot?.telemetry?.executors[0];
  const stream = snapshot?.telemetry?.tick_streams[0];
  const totalResolved = useMemo(
    () => snapshot?.metrics?.modes.reduce((sum, mode) => sum + mode.resolved_outcomes, 0) ?? 0,
    [snapshot],
  );

  async function logout() {
    await fetch("/api/session", { method: "DELETE" });
    router.replace("/login");
    router.refresh();
  }

  return (
    <main className="dashboard-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">E</div>
          <div>
            <p className="eyebrow">RIRI EMERALD</p>
            <h1>Control Center</h1>
          </div>
        </div>
        <div className="topbar-actions">
          <span className="environment">DEMO LOCK</span>
          <span className="last-update">GMT+7 · {formatJakarta(snapshot?.fetched_at)}</span>
          <button className="ghost-button" onClick={() => void refresh()} disabled={loading}>Refresh</button>
          <button className="ghost-button" onClick={() => void logout()}>Keluar</button>
        </div>
      </header>

      {snapshot?.errors.length ? (
        <section className="alert-banner" role="alert">
          <strong>Gangguan koneksi terdeteksi</strong>
          <span>{snapshot.errors.join(" · ")}</span>
        </section>
      ) : null}

      <section className="hero-grid">
        <article className="hero-panel primary-panel">
          <p className="panel-kicker">System posture</p>
          <div className="hero-status">
            <span className={statusClass(snapshot?.telemetry?.telemetry_ready)} />
            <div>
              <h2>{snapshot?.telemetry?.telemetry_ready ? "Telemetry online" : "Waiting for MT5"}</h2>
              <p>Kalibrasi model dan kesiapan eksekusi demo diperiksa terpisah.</p>
            </div>
          </div>
          <div className="hero-metrics">
            <div><span>Executor</span><strong>{executor?.healthy ? "Healthy" : "Offline"}</strong></div>
            <div><span>Tick stream</span><strong>{stream?.healthy ? "Live" : "Unavailable"}</strong></div>
            <div><span>Entry gate</span><strong>{snapshot?.telemetry?.entry_ready ? "Open" : "Locked"}</strong></div>
          </div>
        </article>

        <article className="hero-panel market-panel">
          <div className="panel-title-row">
            <div><p className="panel-kicker">Live market</p><h2>XAUUSD</h2></div>
            <span className={statusClass(stream?.healthy)}>{stream?.healthy ? "LIVE" : "NO DATA"}</span>
          </div>
          <div className="quote-grid">
            <div><span>BID</span><strong>{stream?.latest_bid?.toFixed(2) ?? "—"}</strong></div>
            <div><span>ASK</span><strong>{stream?.latest_ask?.toFixed(2) ?? "—"}</strong></div>
          </div>
          <p className="muted">Last tick {formatJakarta(stream?.latest_observed_at)} · {stream?.tick_age_seconds ?? "—"}s age</p>
        </article>
      </section>

      <section className="summary-grid">
        <article><span>Shadow outcomes</span><strong>{totalResolved}</strong><small>across all modes</small></article>
        <article><span>Open incidents</span><strong>{snapshot?.incidents.length ?? 0}</strong><small>shown immediately</small></article>
        <article><span>Probability model</span><strong>{snapshot?.health?.probability_model_ready ? "READY" : "LOCKED"}</strong><small>80% calibrated gate</small></article>
        <article><span>Account</span><strong>{executor?.account_login ? `••${String(executor.account_login).slice(-4)}` : "—"}</strong><small>{executor?.account_server ?? "MetaQuotes-Demo"}</small></article>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <div><p className="panel-kicker">Shadow calibration</p><h2>Dataset maturity by strategy</h2></div>
          <span className={statusClass(snapshot?.metrics?.calibration_ready)}>
            {snapshot?.metrics?.calibration_ready ? "Calibration ready" : "Not calibrated"}
          </span>
        </div>
        <div className="mode-grid">
          {snapshot?.metrics?.modes.map((mode) => <MetricCard key={mode.strategy_mode} metric={mode} />) ??
            Array.from({ length: 3 }, (_, index) => <div className="mode-card skeleton" key={index} />)}
        </div>
      </section>

      <section className="section-block" aria-label="Hasil kalibrasi model">
        <div className="section-heading">
          <div><p className="panel-kicker">Model evaluation</p><h2>Hasil kalibrasi</h2></div>
          <span className={statusClass(snapshot?.calibration?.probability_model_ready)}>
            {snapshot?.calibration?.probability_model_ready ? "Siap ditinjau untuk demo" :
              snapshot?.calibration?.status === "REJECTED" ? "Belum lolos validasi" :
              snapshot?.calibration?.status === "INVALID_OR_EXPIRED" ? "Laporan perlu diperbarui" : "Belum dijalankan"}
          </span>
        </div>
        {snapshot?.calibration?.artifact_id ? (
          <>
            <p className="muted">Diuji {formatJakarta(snapshot.calibration.created_at)} ·
              {" "}{snapshot.calibration.audit?.usable_samples ?? 0} peluang independen dari
              {" "}{snapshot.calibration.audit?.total_rows ?? 0} catatan ·
              {" "}{snapshot.calibration.eligible_cohorts ?? 0} kelompok lolos</p>
            <p className="muted">Hasil ini tidak mengaktifkan order. Eksekusi EA dan kontrol risiko akun harus siap terlebih dahulu.</p>
            {snapshot.calibration.blockers.includes("MARKET_CLOCK_AHEAD_OF_LABEL_CLOCK") ? (
              <p className="calibration-reasons" role="alert">
                {calibrationReasons.MARKET_CLOCK_AHEAD_OF_LABEL_CLOCK}
              </p>
            ) : null}
            <a className="ghost-button" href="/api/calibration/report">Unduh laporan kalibrasi</a>
            <div className="mode-grid calibration-grid">
              {snapshot.calibration.cohorts.map((item) => (
                <article className="mode-card" key={item.key.join("|")}>
                  <h3>{modeLabels[item.strategy_mode] ?? item.strategy_mode} · {item.direction}</h3>
                  <p className="mode-code">{item.shadow_tier}</p>
                  <p>{item.usable_samples} / {item.minimum_samples} peluang independen</p>
                  <p className="muted">Latih {item.split_counts.train} · Kalibrasi {item.split_counts.calibration} · Uji {item.split_counts.test}</p>
                  {item.validation ? (
                    <div className="risk-list">
                      <div><span>Sinyal terpilih pada data uji</span><strong>{item.validation.selected_samples}</strong></div>
                      <div><span>Target tercapai pada data uji</span><strong>{formatPercent(item.validation.selected_target_rate)}</strong></div>
                      <div><span>Rata-rata hasil bersih</span><strong>{item.validation.mean_net_r === null ? "—" : `${item.validation.mean_net_r.toFixed(2)} R`}</strong></div>
                    </div>
                  ) : null}
                  {item.blockers.length ? (
                    <ul className="calibration-reasons">
                      {item.blockers.map((reason) => <li key={reason}>{calibrationReasons[reason] ?? reason}</li>)}
                    </ul>
                  ) : <p className="muted">Lolos evaluasi awal untuk ditinjau pada akun demo.</p>}
                </article>
              ))}
            </div>
            {snapshot.calibration.missing_modes?.length ? (
              <p className="muted">Belum ada sampel valid: {snapshot.calibration.missing_modes.map((mode) => modeLabels[mode] ?? mode).join(", ")}.</p>
            ) : null}
          </>
        ) : <p className="muted">{snapshot?.calibration?.status === "INVALID_OR_EXPIRED"
          ? "Laporan kalibrasi rusak atau kedaluwarsa. Jalankan ulang evaluasi; entry tetap terkunci."
          : "Laporan akan muncul setelah kalibrasi database shadow dijalankan pada VPS."}</p>}
      </section>

      <section className="lower-grid">
        <article className="section-block incidents-panel">
          <div className="section-heading">
            <div><p className="panel-kicker">Risk operations</p><h2>Active incidents</h2></div>
            <span className={statusClass(snapshot?.incidents.length === 0)}>{snapshot?.incidents.length ?? 0} open</span>
          </div>
          {snapshot?.incidents.length ? (
            <div className="incident-list">
              {snapshot.incidents.map((incident) => (
                <div className="incident-item" key={incident.incident_id}>
                  <span className="incident-icon">!</span>
                  <div><strong>{incident.code}</strong><p>{incident.component} · {formatJakarta(incident.started_at)}</p></div>
                  <span>{incident.severity}</span>
                </div>
              ))}
            </div>
          ) : <div className="empty-state"><span>✓</span><p>Tidak ada insiden aktif.</p></div>}
        </article>

        <article className="section-block risk-panel">
          <div className="section-heading"><div><p className="panel-kicker">Hard boundaries</p><h2>Risk controls</h2></div></div>
          <div className="risk-list">
            <div><span>Regular setup</span><strong>≤ 10%</strong></div>
            <div><span>Rollover & news</span><strong>≤ 5%</strong></div>
            <div><span>Daily loss stop</span><strong>20%</strong></div>
            <div><span>High-water hard stop</span><strong>50%</strong></div>
            <div><span>Total managed lot</span><strong>≤ 0.50</strong></div>
          </div>
        </article>
      </section>

      <section className="section-block events-panel">
        <div className="section-heading">
          <div><p className="panel-kicker">Detector journal</p><h2>Recent shadow events</h2></div>
          <span className="muted">Auto-refresh 5s</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Jakarta time</th><th>Strategy</th><th>Side</th><th>Outcome</th><th>Detector</th></tr></thead>
            <tbody>
              {snapshot?.events.length ? snapshot.events.map((event) => <EventRow key={event.event_id} event={event} />) :
                <tr><td colSpan={5} className="empty-table">Belum ada shadow event.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <footer>
        <span>RIRI EMERALD · Independent deployment</span>
        <span>{snapshot?.health?.service ?? "riri-emerald-brain"} · v{snapshot?.health?.version ?? "—"}</span>
      </footer>
    </main>
  );
}
