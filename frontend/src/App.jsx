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
import {
  METRICS,
  RANGE_OPTIONS,
  STATUS_LABELS,
  formatTimestamp,
} from "./constants";


const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const USE_MOCK = import.meta.env.VITE_USE_MOCK_DATA === "true";
const POLL_INTERVAL = Number(import.meta.env.VITE_POLL_INTERVAL_MS || 5000);
const STALE_AFTER_SECONDS = Number(
  import.meta.env.VITE_STALE_AFTER_SECONDS || 30,
);
const DEFAULT_DEVICE =
  import.meta.env.VITE_DEFAULT_DEVICE_ID || "device-1";
const STATUS_PRIORITY = { normal: 0, warning: 1, critical: 2 };
const TrendChart = lazy(() => import("./components/TrendChart"));


function timeWindow(rangeValue) {
  const range = RANGE_OPTIONS.find((item) => item.value === rangeValue);
  const to = new Date();
  const from = new Date(to.getTime() - range.milliseconds);
  return { from: from.toISOString(), to: to.toISOString() };
}


function detectNewAlertState(record, deviceId) {
  if (!record) return false;
  const storageKey = `cloudsense-active-alerts:${deviceId}`;
  let previous = {};
  try {
    previous = JSON.parse(localStorage.getItem(storageKey) || "{}");
  } catch {
    previous = {};
  }

  const current = Object.fromEntries(
    (record.alerts || []).map((alert) => [alert.metric, alert.severity]),
  );
  const hasNewOrEscalated = Object.entries(current).some(
    ([metric, severity]) =>
      !previous[metric] ||
      STATUS_PRIORITY[severity] > STATUS_PRIORITY[previous[metric]],
  );
  localStorage.setItem(storageKey, JSON.stringify(current));
  return hasNewOrEscalated;
}


function effectiveStatus(latest, isStale) {
  if (!latest) return "unknown";
  if (isStale) return "stale";
  return latest.overallStatus || "unknown";
}


export default function App() {
  const initialDevice = localStorage.getItem("cloudsense-device") || DEFAULT_DEVICE;
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
  const [error, setError] = useState("");
  const [paused, setPaused] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [clock, setClock] = useState(() => Date.now());
  const [dialogRecord, setDialogRecord] = useState(null);
  const lastProcessedRecord = useRef(null);
  const trendSection = useRef(null);

  const processLatest = (record) => {
    setLatest(record);
    if (!record || lastProcessedRecord.current === record.recordId) return;
    lastProcessedRecord.current = record.recordId;
    if (detectNewAlertState(record, deviceId)) {
      setDialogRecord(record);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    const window = timeWindow(range);
    setLoading(true);
    setHistoryLoading(true);
    setAlertLoading(true);
    setError("");

    Promise.all([
      fetchLatest({
        apiBase: API_BASE,
        deviceId,
        signal: controller.signal,
        useMock: USE_MOCK,
      }),
      fetchHistory({
        apiBase: API_BASE,
        deviceId,
        ...window,
        signal: controller.signal,
        useMock: USE_MOCK,
      }),
      fetchAlerts({
        apiBase: API_BASE,
        deviceId,
        ...window,
        signal: controller.signal,
        useMock: USE_MOCK,
      }),
    ])
      .then(([latestResult, historyResult, alertResult]) => {
        processLatest(latestResult);
        setHistory(historyResult.records || []);
        setAlertRecords(alertResult.records || []);
      })
      .catch((requestError) => {
        if (requestError.name !== "AbortError") {
          setError(requestError.message || "无法加载 Dashboard 数据");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
          setHistoryLoading(false);
          setAlertLoading(false);
        }
      });

    return () => controller.abort();
  }, [deviceId, range, refreshVersion]);

  useEffect(() => {
    if (paused || (!USE_MOCK && !API_BASE)) return undefined;
    const interval = window.setInterval(async () => {
      if (document.hidden) return;
      try {
        const record = await fetchLatest({
          apiBase: API_BASE,
          deviceId,
          useMock: USE_MOCK,
        });
        processLatest(record);
        setError("");
      } catch (requestError) {
        setError(requestError.message || "最新数据刷新失败");
      }
    }, POLL_INTERVAL);
    return () => window.clearInterval(interval);
  }, [deviceId, paused]);

  useEffect(() => {
    const interval = window.setInterval(() => setClock(Date.now()), 5000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    lastProcessedRecord.current = null;
    setDialogRecord(null);
  }, [deviceId]);

  const measurementTime = latest?.timestamp
    ? new Date(latest.timestamp).getTime()
    : null;
  const isStale = Boolean(
    latest &&
      (latest.isLate ||
        !measurementTime ||
        clock - measurementTime > STALE_AFTER_SECONDS * 1000),
  );
  const status = effectiveStatus(latest, isStale);
  const statusDescription = {
    normal: "所有指标均在项目设定的正常范围内",
    warning: "至少一项指标需要关注",
    critical: "检测到严重异常，请立即查看详情",
    stale: "长时间没有收到新数据，请检查设备连接",
    unknown: "正在等待设备数据",
  }[status];

  const submitDevice = (event) => {
    event.preventDefault();
    const normalized = deviceDraft.trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$/.test(normalized)) {
      setDeviceError("设备编号需为 3–64 位字母、数字、下划线或连字符");
      return;
    }
    setDeviceError("");
    localStorage.setItem("cloudsense-device", normalized);
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
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <header className="topbar">
        <div className="brand" aria-label="CloudSense">
          <span className="brand-mark" aria-hidden="true"><HeartPulse size={22} /></span>
          <span>
            <strong>CloudSense</strong>
            <small>Health Monitor</small>
          </span>
        </div>

        <form className="device-form" onSubmit={submitDevice}>
          <label htmlFor="device-id">监测设备</label>
          <div>
            <input
              id="device-id"
              value={deviceDraft}
              onChange={(event) => setDeviceDraft(event.target.value)}
              aria-describedby={deviceError ? "device-error" : undefined}
              autoComplete="off"
              spellCheck="false"
            />
            <button type="submit" className="secondary-button">切换</button>
          </div>
          {deviceError && <span id="device-error" className="field-error">{deviceError}</span>}
        </form>

        <div className="connection-chip">
          {isStale || error ? <WifiOff size={17} /> : <Wifi size={17} />}
          <span>{USE_MOCK ? "演示数据" : paused ? "刷新已暂停" : isStale ? "设备离线" : "实时连接"}</span>
        </div>
      </header>

      <main id="main-content">
        {error && (
          <div className="error-banner" role="alert">
            <CloudCog size={20} aria-hidden="true" />
            <div><strong>数据连接异常</strong><span>{error}</span></div>
            <button type="button" onClick={() => setRefreshVersion((value) => value + 1)}>重试</button>
          </div>
        )}

        <section className={`status-hero hero-${status}`} aria-labelledby="dashboard-title">
          <div className="hero-icon" aria-hidden="true"><StatusIcon size={30} strokeWidth={1.8} /></div>
          <div className="hero-copy">
            <span className="eyebrow">设备 {deviceId}</span>
            <div className="hero-title-row">
              <h1 id="dashboard-title">身体数据监测</h1>
              <StatusPill status={status} />
            </div>
            <p>{statusDescription}</p>
          </div>
          <dl className="hero-meta">
            <div><dt>最近测量</dt><dd>{formatTimestamp(latest?.timestamp, { seconds: true })}</dd></div>
            <div><dt>活动状态</dt><dd>{latest?.activity || "--"}</dd></div>
            <div><dt>处理状态</dt><dd>{latest?.processingStatus || "--"}</dd></div>
          </dl>
          <div className="hero-actions">
            <button
              type="button"
              className="icon-text-button"
              onClick={() => setPaused((value) => !value)}
              aria-pressed={paused}
            >
              {paused ? <CirclePlay size={18} /> : <CirclePause size={18} />}
              {paused ? "继续刷新" : "暂停刷新"}
            </button>
            <button
              type="button"
              className="icon-button"
              onClick={() => setRefreshVersion((value) => value + 1)}
              aria-label="立即刷新全部数据"
              title="立即刷新"
            >
              <RefreshCw size={19} aria-hidden="true" />
            </button>
          </div>
        </section>

        <section aria-labelledby="metrics-title">
          <div className="section-heading">
            <div><span className="eyebrow">Current readings</span><h2 id="metrics-title">当前身体数据</h2></div>
            <span className="section-meta">每 {Math.round(POLL_INTERVAL / 1000)} 秒刷新</span>
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
            <div><span className="eyebrow">Trend analysis</span><h2 id="trend-title">历史趋势</h2></div>
            <div className="segmented-control" aria-label="趋势时间范围">
              {RANGE_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={range === option.value ? "active" : ""}
                  onClick={() => setRange(option.value)}
                  aria-pressed={range === option.value}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <div className="metric-tabs" role="tablist" aria-label="选择趋势指标">
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
          <Suspense fallback={<div className="chart-skeleton" aria-label="趋势图加载中" />}>
            <TrendChart records={history} metricKey={selectedMetric} loading={historyLoading} />
          </Suspense>
          <div className="chart-legend-note">
            <Activity size={16} aria-hidden="true" />
            异常点使用更大的黄色或红色标记；完整异常说明见下方记录。
          </div>
        </section>

        <section className="dashboard-panel" aria-labelledby="alerts-title">
          <div className="panel-heading">
            <div><span className="eyebrow">Alert history</span><h2 id="alerts-title">异常记录</h2></div>
            <span className="section-meta">{alertRecords.reduce((total, record) => total + (record.alerts?.length || 0), 0)} 条</span>
          </div>
          <AlertTable records={alertRecords} loading={alertLoading} />
        </section>
      </main>

      <footer>
        <span>CloudSense Dashboard</span>
        <span>状态判断来自 Lambda2，前端仅负责展示。</span>
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
