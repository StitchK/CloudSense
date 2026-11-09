export const STATUS_LABELS = {
  normal: "Normal",
  warning: "Warning",
  critical: "Critical",
  unknown: "Unknown",
  stale: "Outdated data",
};


export const METRICS = {
  heart_rate_bpm: {
    label: "Heart rate",
    shortLabel: "Heart rate",
    range: "60–100 bpm",
    color: "#5eead4",
  },
  body_temperature_c: {
    label: "Body temperature",
    shortLabel: "Body temperature",
    range: "36.1–37.4 °C",
    color: "#fbbf24",
  },
  spo2_pct: {
    label: "Blood oxygen",
    shortLabel: "SpO₂",
    range: "≥ 95%",
    color: "#60a5fa",
  },
  blood_pressure: {
    label: "Blood pressure",
    shortLabel: "Blood pressure",
    range: "90–130 / 60–85 mmHg",
    color: "#c084fc",
  },
};


export const RANGE_OPTIONS = [
  { value: "1h", label: "1 hour", milliseconds: 60 * 60 * 1000 },
  { value: "24h", label: "24 hours", milliseconds: 24 * 60 * 60 * 1000 },
  { value: "7d", label: "7 days", milliseconds: 7 * 24 * 60 * 60 * 1000 },
];


export function formatMetricValue(metric, value) {
  if (value === null || value === undefined) return "--";
  if (metric === "blood_pressure" && typeof value === "object") {
    return `${value.systolic}/${value.diastolic}`;
  }
  if (metric === "body_temperature_c") return Number(value).toFixed(1);
  return String(value);
}


export function formatTimestamp(value, options = {}) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return new Intl.DateTimeFormat("en-GB", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: options.seconds ? "2-digit" : undefined,
    hour12: false,
  }).format(date);
}
