import { METRICS, formatMetricValue } from "./constants.js";

const UNITS = {
  heart_rate_bpm: "bpm", body_temperature_c: "°C", spo2_pct: "%", blood_pressure: "mmHg",
};
const PRIORITY = { normal: 0, warning: 1, critical: 2 };
const ACTIVITY = { rest: "Resting", walking: "Walking", running: "Running", sleeping: "Sleeping" };
const PROCESSING = { COMPLETE: "Complete", PROCESSING: "Processing", PENDING: "Pending", LATE: "Late reading saved" };
const NOTIFICATIONS = {
  SENT: "Notification sent", SUPPRESSED: "Notification cooldown", CRITICAL_PENDING: "Awaiting consecutive critical readings",
  NORMAL: "No notification needed", LATE: "Late reading; no notification", OUT_OF_ORDER: "Earlier reading; no notification",
  SEND_FAILED: "Notification failed", RETRY_PENDING: "Notification retry pending", CLAIMED: "Sending notification",
};

export function notificationLabel(status) {
  return NOTIFICATIONS[status] || (status ? "Notification result unavailable" : "No notification result recorded");
}

// Describe the saved value; severity continues to come exclusively from Lambda2.
export function describeAlert(metric, value, severity = "warning") {
  const label = METRICS[metric]?.label || "Reading";
  const highText = severity === "critical" ? "very high" : "high";
  const lowText = severity === "critical" ? "very low" : "low";
  if (value == null) return `${label} is abnormal; measured value unavailable`;
  let reason = `${label} is abnormal`;
  if (metric === "blood_pressure" && typeof value === "object") {
    const { systolic, diastolic } = value;
    const high = systolic > 130 || diastolic > 85;
    const low = systolic < 90 || diastolic < 60;
    const systolicSeverity = systolic < 80 || systolic > 180 ? "critical" : "warning";
    const diastolicSeverity = diastolic < 50 || diastolic > 120 ? "critical" : "warning";
    if (high && low) {
      const systolicText = systolic < 90
        ? (systolicSeverity === "critical" ? "very low" : "low")
        : (systolicSeverity === "critical" ? "very high" : "high");
      const diastolicText = diastolic < 60
        ? (diastolicSeverity === "critical" ? "very low" : "low")
        : (diastolicSeverity === "critical" ? "very high" : "high");
      reason = `Systolic pressure is ${systolicText}; diastolic pressure is ${diastolicText}`;
    } else {
      reason = high ? `Blood pressure is ${highText}` : low ? `Blood pressure is ${lowText}` : reason;
    }
  } else if (typeof value === "number") {
    const bounds = { heart_rate_bpm: [60, 100], body_temperature_c: [36.1, 37.5], spo2_pct: [95, Infinity] }[metric];
    if (bounds) {
      const high = metric === "body_temperature_c" ? value >= bounds[1] : value > bounds[1];
      reason = value < bounds[0] ? `${label} is ${lowText}` : high ? `${label} is ${highText}` : reason;
    }
  }
  return `${reason}; measured value: ${formatMetricValue(metric, value)} ${UNITS[metric] || ""}`.trim();
}

export function normalizeRecord(item) {
  if (!item?.reading?.reading_id || !item.reading.device_id) {
    throw new Error("The query returned an incomplete reading.");
  }
  const reading = item.reading;
  const evaluations = new Map((item.evaluations || []).map((entry) => [entry.metric, entry]));
  const metrics = Object.fromEntries(Object.keys(METRICS).map((metric) => [metric, {
    value: reading[metric], unit: UNITS[metric], status: evaluations.get(metric)?.level || "unknown",
  }]));
  const alerts = (item.alerts || []).map((alert) => ({
    metric: alert.metric, severity: alert.level,
    reason: describeAlert(alert.metric, reading[alert.metric], alert.level),
    notificationStatus: alert.notification_status,
  })).sort((a, b) => (PRIORITY[b.severity] ?? -1) - (PRIORITY[a.severity] ?? -1));
  return {
    recordId: reading.reading_id, deviceId: reading.device_id, timestamp: reading.timestamp,
    measuredAtEpoch: item.measured_at_epoch, metrics, alerts,
    overallStatus: item.overall_status || "unknown",
    processingStatus: PROCESSING[item.processing_status] || "Unknown processing status",
    activity: ACTIVITY[reading.activity] || "Unknown", isLate: Boolean(item.is_late),
  };
}

export function recordIsStale(record, now = Date.now(), staleAfterSeconds = 300) {
  if (!record) return false;
  const time = new Date(record.timestamp).getTime();
  return Boolean(record.isStale || !Number.isFinite(time) || now - time > staleAfterSeconds * 1000);
}
