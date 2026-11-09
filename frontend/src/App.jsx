import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CirclePause,
  CirclePlay,
  CloudCog,
  HeartPulse,
  RefreshCw,
  ShieldCheck,
  Wifi,
  WifiOff,
} from "lucide-react";
import { fetchAlerts, fetchHistory, fetchLatest } from "./api";
import AlertDialog from "./components/AlertDialog";
import AlertTable from "./components/AlertTable";
import MetricCard from "./components/MetricCard";
import StatusPill from "./components/StatusPill";
import { recordIsStale } from "./records.js";
import { startPolling } from "./polling.js";
import { readPreference, writePreference, updateAlertState } from "./alertState.js";
import {
  METRICS,
  RANGE_OPTIONS,
  formatTimestamp,
} from "./constants";


const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const USE_MOCK = import.meta.env.VITE_USE_MOCK_DATA === "true";
const POLL_INTERVAL = Number(import.meta.env.VITE_POLL_INTERVAL_MS || 5000);
const STALE_AFTER_SECONDS = Number(
  import.meta.env.VITE_STALE_AFTER_SECONDS || 300,
);
const DEFAULT_DEVICE =
  import.meta.env.VITE_DEFAULT_DEVICE_ID || "device-001";
const DEVICE_PREFERENCE = `cloudsense-device:${DEFAULT_DEVICE}`;
const TrendChart = lazy(() => import("./components/TrendChart"));


function timeWindow(rangeValue) {
  const range = RANGE_OPTIONS.find((item) => item.value === rangeValue);
  const to = new Date();
  const from = new Date(to.getTime() - range.milliseconds);
  return { from, to };
}


export default function App() {
  const initialDevice = readPreference(DEVICE_PREFERENCE, DEFAULT_DEVICE);
  const [deviceId, setDeviceId] = useState(initialDevice);
  const [deviceDraft, setDeviceDraft] = useState(initialDevice);
  const [deviceError, setDeviceError] = useState("");
  const [latest, setLatest] = useState(null);
  const [history, setHistory] = useState([]);
  const [alertRecords, setAlertRecords] = useState([]);
  const [range, setRange] = useState("1h");
  const [selectedMetric, setSelectedMetric] = useState("heart_rate_bpm");
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [alertLoading, setAlertLoading] = useState(true);
  const [errors, setErrors] = useState({});
  const [paused, setPaused] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [clock, setClock] = useState(() => Date.now());
  const [dialogRecord, setDialogRecord] = useState(null);
  const lastProcessedRecord = useRef(null);
  const activeAlerts = useRef({});
  const pauseRef = useRef(paused);
  pauseRef.current = paused;
  const trendSection = useRef(null);
  const error = Object.values(errors).filter(Boolean).join("; ");
  const alertCount = alertRecords.reduce((total, record) => total + (record.alerts?.length || 0), 0);

  useEffect(() => {
    try {
      const saved = JSON.parse(readPreference(`cloudsense-alert-state:${deviceId}`, "{}"));
      lastProcessedRecord.current = typeof saved.recordId === "string" ? saved.recordId : null;
      activeAlerts.current = saved.levels && typeof saved.levels === "object" ? saved.levels : {};
    } catch { lastProcessedRecord.current = null; activeAlerts.current = {}; }
    setLoading(true);
    setHistoryLoading(true);
    setAlertLoading(true);
    return startPolling({
      interval: Number.isFinite(POLL_INTERVAL) ? Math.max(1000, POLL_INTERVAL) : 5000,
      canPoll: () => !pauseRef.current && !document.hidden,
      load: (signal) => {
        const options = { apiBase: API_BASE, deviceId, ...timeWindow(range), signal, useMock: USE_MOCK };
        return Promise.allSettled([fetchLatest(options), fetchHistory(options), fetchAlerts(options)]);
      },
      onResult: ([latestResult, historyResult, alertResult]) => {
        const failures = {};
        if (latestResult.status === "fulfilled") {
          const record = latestResult.value;
          setLatest(record);
          if (!record) {
            lastProcessedRecord.current = null;
            setDialogRecord(null);
          } else if (lastProcessedRecord.current !== record.recordId) {
            lastProcessedRecord.current = record.recordId;
            const state = updateAlertState(record, activeAlerts.current);
            activeAlerts.current = state.current;
            writePreference(`cloudsense-alert-state:${deviceId}`, JSON.stringify({ recordId: record.recordId, levels: state.current }));
            setDialogRecord((openRecord) => openRecord ? (record.alerts.length ? record : null) : null);
            if (state.notify && !recordIsStale(record, Date.now(), STALE_AFTER_SECONDS)) setDialogRecord(record);
          }
        } else failures.latest = `Latest reading: ${latestResult.reason.message}`;
        if (historyResult.status === "fulfilled") setHistory(historyResult.value.records);
        else failures.history = `History: ${historyResult.reason.message}`;
        if (alertResult.status === "fulfilled") setAlertRecords(alertResult.value.records);
        else failures.alerts = `Alerts: ${alertResult.reason.message}`;
        setErrors(failures);
        setLoading(false);
        setHistoryLoading(false);
        setAlertLoading(false);
      },
      onError: (requestError) => {
        setErrors({ latest: requestError.message });
        setLoading(false); setHistoryLoading(false); setAlertLoading(false);
      },
    });
  }, [deviceId, range, refreshVersion]);

  useEffect(() => {
    const interval = window.setInterval(() => setClock(Date.now()), 5000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (dialogRecord && recordIsStale(dialogRecord, clock, STALE_AFTER_SECONDS)) setDialogRecord(null);
  }, [clock, dialogRecord]);

  const isStale = recordIsStale(latest, clock, STALE_AFTER_SECONDS);
  const status = latest?.overallStatus || "unknown";
  const statusDescription = {
    normal: "All readings are within the configured normal ranges.",
    warning: "At least one reading needs attention.",
    critical: "Critical reading detected. Review the details now.",
    stale: "No recent readings. Check the device connection.",
    unknown: "Waiting for device readings.",
  }[status];

  const submitDevice = (event) => {
    event.preventDefault();
    const normalized = deviceDraft.trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$/.test(normalized)) {
      setDeviceError("Use 3–64 characters: letters, numbers, underscores or hyphens. Start with a letter or number.");
      return;
    }
    setDeviceError("");
    writePreference(DEVICE_PREFERENCE, normalized);
    if (normalized !== deviceId) {
      setLatest(null); setHistory([]); setAlertRecords([]); setErrors({});
      setDialogRecord(null); lastProcessedRecord.current = null; activeAlerts.current = {};
    }
    setDeviceId(normalized);
  };

  const viewTrend = (metric) => {
    setSelectedMetric(metric);
    setDialogRecord(null);
    requestAnimationFrame(() => {
      trendSection.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

  const StatusIcon = status === "normal" ? ShieldCheck : AlertTriangle;

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <header className="topbar">
        <div className="brand" aria-label="CloudSense">
          <span className="brand-mark" aria-hidden="true"><HeartPulse size={22} /></span>
          <span>
            <strong>CloudSense</strong>
            <small>Health Monitor</small>
          </span>
        </div>

        <form className="device-form" onSubmit={submitDevice}>
          <label htmlFor="device-id">Device ID</label>
          <div>
            <input
              id="device-id"
              value={deviceDraft}
              onChange={(event) => setDeviceDraft(event.target.value)}
              aria-describedby={deviceError ? "device-error" : undefined}
              autoComplete="off"
              spellCheck="false"
            />
            <button type="submit" className="secondary-button">Switch</button>
          </div>
          {deviceError && <span id="device-error" className="field-error">{deviceError}</span>}
        </form>

        <div className="connection-chip">
          {isStale || error ? <WifiOff size={17} /> : <Wifi size={17} />}
          <span>{USE_MOCK ? "Demo data" : error ? "Connection error" : paused ? "Refresh paused" : !latest ? "Waiting for data" : isStale ? "Outdated data" : "Live connection"}</span>
        </div>
      </header>

      <main id="main-content">
        {error && (
          <div className="error-banner" role="alert">
            <CloudCog size={20} aria-hidden="true" />
            <div><strong>Data connection error</strong><span>{error}</span></div>
            <button type="button" onClick={() => setRefreshVersion((value) => value + 1)}>Retry</button>
          </div>
        )}

        <section className={`status-hero hero-${status}`} aria-labelledby="dashboard-title">
          <div className="hero-icon" aria-hidden="true"><StatusIcon size={30} strokeWidth={1.8} /></div>
          <div className="hero-copy">
            <span className="eyebrow">Device {deviceId}</span>
            <div className="hero-title-row">
              <h1 id="dashboard-title">Health Monitor</h1>
              <StatusPill status={status} />
            </div>
            <p>{statusDescription}</p>
            {isStale && <p className="stale-notice">These readings are outdated. The status reflects the last measurement. Check that the device is still uploading.</p>}
          </div>
          <dl className="hero-meta">
            <div><dt>Last measured</dt><dd>{formatTimestamp(latest?.timestamp, { seconds: true })}</dd></div>
            <div><dt>Activity</dt><dd>{latest?.activity || "--"}</dd></div>
            <div><dt>Processing</dt><dd>{latest?.processingStatus || "--"}</dd></div>
          </dl>
          <div className="hero-actions">
            <button
              type="button"
              className="icon-text-button"
              onClick={() => setPaused((value) => !value)}
              aria-pressed={paused}
            >
              {paused ? <CirclePlay size={18} /> : <CirclePause size={18} />}
              {paused ? "Resume updates" : "Pause updates"}
            </button>
            <button
              type="button"
              className="icon-button"
              onClick={() => setRefreshVersion((value) => value + 1)}
              aria-label="Refresh all readings now"
              title="Refresh now"
            >
              <RefreshCw size={19} aria-hidden="true" />
            </button>
          </div>
        </section>

        <section aria-labelledby="metrics-title">
          <div className="section-heading">
            <div><span className="eyebrow">Current readings</span><h2 id="metrics-title">Current readings</h2></div>
            <span className="section-meta">{paused ? "Automatic updates paused" : `Updates about every ${Math.round(POLL_INTERVAL / 1000)} seconds`}</span>
          </div>
          <div className="metric-grid">
            {Object.keys(METRICS).map((metricKey) => (
              <MetricCard
                key={metricKey}
                metricKey={metricKey}
                metric={latest?.metrics?.[metricKey]}
                loading={loading}
              />
            ))}
          </div>
        </section>

        <section className="dashboard-panel trend-panel" aria-labelledby="trend-title" ref={trendSection}>
          <div className="panel-heading">
            <div><span className="eyebrow">Trend analysis</span><h2 id="trend-title">Historical trends</h2></div>
            <div className="segmented-control" aria-label="Trend time range">
              {RANGE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={range === option.value ? "active" : ""}
                  onClick={() => {
                    if (range !== option.value) {
                      setHistory([]); setAlertRecords([]); setHistoryLoading(true); setAlertLoading(true);
                      setRange(option.value);
                    }
                  }}
                  aria-pressed={range === option.value}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <div className="metric-tabs" role="tablist" aria-label="Select a trend metric">
            {Object.entries(METRICS).map(([key, metric]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={selectedMetric === key}
                className={selectedMetric === key ? "active" : ""}
                onClick={() => setSelectedMetric(key)}
              >
                <span style={{ "--metric-color": metric.color }} aria-hidden="true" />
                {metric.shortLabel}
              </button>
            ))}
          </div>
          <Suspense fallback={<div className="chart-skeleton" aria-label="Loading trend chart" />}>
            <TrendChart records={history} metricKey={selectedMetric} loading={historyLoading} error={errors.history} />
          </Suspense>
          <div className="chart-legend-note">
            <Activity size={16} aria-hidden="true" />
            Abnormal readings use larger yellow or red markers. See the alert history below for details.
          </div>
        </section>

        <section className="dashboard-panel" aria-labelledby="alerts-title">
          <div className="panel-heading">
            <div><span className="eyebrow">Alert history</span><h2 id="alerts-title">Alert history</h2></div>
            <span className="section-meta">{alertCount} {alertCount === 1 ? "alert" : "alerts"}</span>
          </div>
          <AlertTable records={alertRecords} loading={alertLoading} error={errors.alerts} />
        </section>
      </main>

      <footer>
        <span>CloudSense Dashboard</span>
        <span>Reading statuses are for this project demonstration. Pay attention to your health if an abnormal reading appears.</span>
      </footer>

      {dialogRecord && (
        <AlertDialog
          record={dialogRecord}
          onClose={() => setDialogRecord(null)}
          onViewTrend={viewTrend}
        />
      )}
    </div>
  );
}
