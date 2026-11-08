import { METRICS, formatMetricValue } from "./constants.js";

const UNITS = {
  heart_rate_bpm: "bpm", body_temperature_c: "°C", spo2_pct: "%", blood_pressure: "mmHg",
};
const PRIORITY = { normal: 0, warning: 1, critical: 2 };
const ACTIVITY = { rest: "休息", walking: "步行", running: "跑步", sleeping: "睡眠" };
const PROCESSING = { COMPLETE: "处理完成", PROCESSING: "处理中", PENDING: "等待处理", LATE: "迟到数据已保存" };
const NOTIFICATIONS = {
  SENT: "已发送通知", SUPPRESSED: "通知冷却中", CRITICAL_PENDING: "等待连续异常确认",
  NORMAL: "无需通知", LATE: "迟到数据，未通知", OUT_OF_ORDER: "较早的测量，未通知",
  SEND_FAILED: "通知发送失败", RETRY_PENDING: "等待重试通知", CLAIMED: "通知处理中",
};

export function notificationLabel(status) {
  return NOTIFICATIONS[status] || (status ? "暂无通知结果" : "未记录通知结果");
}

// Describe the saved value; severity continues to come exclusively from Lambda2.
export function describeAlert(metric, value, severity = "warning") {
  const label = METRICS[metric]?.label || "指标";
  const highText = severity === "critical" ? "过高" : "偏高";
  const lowText = severity === "critical" ? "过低" : "偏低";
  if (value == null) return `${label}异常，暂无该次测量值`;
  let reason = `${label}异常`;
  if (metric === "blood_pressure" && typeof value === "object") {
    const { systolic, diastolic } = value;
    const high = systolic > 130 || diastolic > 85;
    const low = systolic < 90 || diastolic < 60;
    const systolicSeverity = systolic < 80 || systolic > 180 ? "critical" : "warning";
    const diastolicSeverity = diastolic < 50 || diastolic > 120 ? "critical" : "warning";
    if (high && low) {
      const systolicText = systolic < 90
        ? (systolicSeverity === "critical" ? "过低" : "偏低")
        : (systolicSeverity === "critical" ? "过高" : "偏高");
      const diastolicText = diastolic < 60
        ? (diastolicSeverity === "critical" ? "过低" : "偏低")
        : (diastolicSeverity === "critical" ? "过高" : "偏高");
      reason = `收缩压${systolicText}、舒张压${diastolicText}`;
    } else {
      reason = high ? `血压${highText}` : low ? `血压${lowText}` : reason;
    }
  } else if (typeof value === "number") {
    const bounds = { heart_rate_bpm: [60, 100], body_temperature_c: [36.1, 37.5], spo2_pct: [95, Infinity] }[metric];
    if (bounds) {
      const high = metric === "body_temperature_c" ? value >= bounds[1] : value > bounds[1];
      reason = value < bounds[0] ? `${label}${lowText}` : high ? `${label}${highText}` : reason;
    }
  }
  return `${reason}，测量值为 ${formatMetricValue(metric, value)} ${UNITS[metric] || ""}`.trim();
}

export function normalizeRecord(item) {
  if (!item?.reading?.reading_id || !item.reading.device_id) {
    throw new Error("查询接口返回的读数格式不完整");
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
    processingStatus: PROCESSING[item.processing_status] || "处理状态未知",
    activity: ACTIVITY[reading.activity] || "未知", isLate: Boolean(item.is_late),
  };
}

export function recordIsStale(record, now = Date.now(), staleAfterSeconds = 300) {
  if (!record) return false;
  const time = new Date(record.timestamp).getTime();
  return Boolean(record.isStale || !Number.isFinite(time) || now - time > staleAfterSeconds * 1000);
}
