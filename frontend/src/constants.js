export const STATUS_LABELS = {
  normal: "正常",
  warning: "警告",
  critical: "严重",
  unknown: "未知",
  stale: "数据过期",
};


export const METRICS = {
  heart_rate_bpm: {
    label: "心率",
    shortLabel: "心率",
    range: "60–100 bpm",
    color: "#5eead4",
  },
  body_temperature_c: {
    label: "体温",
    shortLabel: "体温",
    range: "36.1–37.4 °C",
    color: "#fbbf24",
  },
  spo2_pct: {
    label: "血氧",
    shortLabel: "SpO₂",
    range: "≥ 95%",
    color: "#60a5fa",
  },
  blood_pressure: {
    label: "血压",
    shortLabel: "血压",
    range: "90–130 / 60–85 mmHg",
    color: "#c084fc",
  },
};


export const RANGE_OPTIONS = [
  { value: "1h", label: "1 小时", milliseconds: 60 * 60 * 1000 },
  { value: "24h", label: "24 小时", milliseconds: 24 * 60 * 60 * 1000 },
  { value: "7d", label: "7 天", milliseconds: 7 * 24 * 60 * 60 * 1000 },
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
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: options.seconds ? "2-digit" : undefined,
    hour12: false,
  }).format(date);
}
