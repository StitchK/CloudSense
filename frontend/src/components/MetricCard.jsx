import {
  Activity,
  HeartPulse,
  Thermometer,
  Waves,
} from "lucide-react";
import { METRICS, formatMetricValue } from "../constants";
import StatusPill from "./StatusPill";


const ICONS = {
  heart_rate_bpm: HeartPulse,
  body_temperature_c: Thermometer,
  spo2_pct: Waves,
  blood_pressure: Activity,
};


export default function MetricCard({ metricKey, metric, loading }) {
  const config = METRICS[metricKey];
  const Icon = ICONS[metricKey];
  const status = metric?.status || "unknown";

  return (
    <article className={`metric-card metric-${status}`} aria-labelledby={`${metricKey}-title`}>
      <div className="metric-card-heading">
        <div className="metric-icon" aria-hidden="true">
          <Icon size={20} strokeWidth={1.8} />
        </div>
        <div>
          <h3 id={`${metricKey}-title`}>{config.label}</h3>
          <p>参考范围 {config.range}</p>
        </div>
        <StatusPill status={status} compact />
      </div>

      {loading ? (
        <div className="metric-skeleton" aria-label={`${config.label}加载中`} />
      ) : (
        <div className="metric-reading">
          <strong>{formatMetricValue(metricKey, metric?.value)}</strong>
          <span>{metric?.unit || "--"}</span>
        </div>
      )}
    </article>
  );
}
