import { normalizeRecord } from "./records.js";

const METRIC_CONFIG = {
  heart_rate_bpm: { unit: "bpm", baseline: 76 },
  body_temperature_c: { unit: "C", baseline: 36.7 },
  spo2_pct: { unit: "%", baseline: 97 },
  blood_pressure: {
    unit: "mmHg",
    baseline: { systolic: 121, diastolic: 78 },
  },
};


function statusFor(metric, value) {
  if (metric === "heart_rate_bpm") {
    if (value < 45 || value > 120) return "critical";
    if (value < 60 || value > 100) return "warning";
  }
  if (metric === "body_temperature_c") {
    if (value < 35 || value >= 38) return "critical";
    if (value < 36.1 || value >= 37.5) return "warning";
  }
  if (metric === "spo2_pct") {
    if (value < 92) return "critical";
    if (value < 95) return "warning";
  }
  if (metric === "blood_pressure") {
    if (
      value.systolic < 80 ||
      value.systolic > 180 ||
      value.diastolic < 50 ||
      value.diastolic > 120
    ) {
      return "critical";
    }
    if (
      value.systolic < 90 ||
      value.systolic > 130 ||
      value.diastolic < 60 ||
      value.diastolic > 85
    ) {
      return "warning";
    }
  }
  return "normal";
}


function overallStatus(metrics) {
  const levels = Object.values(metrics).map((metric) => metric.status);
  if (levels.includes("critical")) return "critical";
  if (levels.includes("warning")) return "warning";
  return "normal";
}


function createRecord(deviceId, timestamp, index, total) {
  const phase = index / Math.max(total - 1, 1);
  const criticalPoint = index === total - 4 || index === total - 3;
  const warningPoint = index === total - 8;
  const heartRate = Math.round(74 + Math.sin(phase * Math.PI * 6) * 7);
  const temperature = Number(
    (36.6 + Math.sin(phase * Math.PI * 3) * 0.25).toFixed(1),
  );
  const spo2 = criticalPoint ? 89 : warningPoint ? 93 : 97 + (index % 2);
  const pressure = {
    systolic: warningPoint ? 138 : 118 + (index % 7),
    diastolic: warningPoint ? 89 : 76 + (index % 5),
  };
  const values = {
    heart_rate_bpm: heartRate,
    body_temperature_c: temperature,
    spo2_pct: spo2,
    blood_pressure: pressure,
  };
  const metrics = Object.fromEntries(
    Object.entries(values).map(([metric, value]) => [
      metric,
      {
        value,
        unit: METRIC_CONFIG[metric].unit,
        status: statusFor(metric, value),
      },
    ]),
  );
  const alerts = Object.entries(metrics)
    .filter(([, metric]) => metric.status !== "normal")
    .map(([metric, value]) => ({
      metric,
      severity: value.status,
      reason: `${metric} is outside the configured range`,
      notificationStatus: value.status === "critical" ? "SENT" : "SUPPRESSED",
    }));

  return normalizeRecord({
    reading: {
      ...values, reading_id: `mock-${timestamp.getTime()}`, device_id: deviceId,
      timestamp: timestamp.toISOString(), activity: "rest",
    },
    evaluations: Object.entries(metrics).map(([metric, entry]) => ({ metric, level: entry.status })),
    alerts: alerts.map((alert) => ({ metric: alert.metric, level: alert.severity, notification_status: alert.notificationStatus })),
    measured_at_epoch: Math.floor(timestamp.getTime() / 1000),
    overall_status: overallStatus(metrics), processing_status: "COMPLETE", is_late: false,
  });
}


function mockRecords(deviceId, from, to) {
  const end = to ? new Date(to) : new Date();
  const start = from ? new Date(from) : new Date(end.getTime() - 60 * 60 * 1000);
  const count = 48;
  const step = Math.max((end - start) / (count - 1), 30_000);
  return Array.from({ length: count }, (_, index) =>
    createRecord(deviceId, new Date(start.getTime() + step * index), index, count),
  );
}


export async function getMockLatest(deviceId) {
  await new Promise((resolve) => setTimeout(resolve, 180));
  const records = mockRecords(
    deviceId,
    new Date(Date.now() - 60 * 60 * 1000),
    new Date(),
  );
  return records.at(-1);
}


export async function getMockHistory(deviceId, from, to) {
  await new Promise((resolve) => setTimeout(resolve, 240));
  const records = mockRecords(deviceId, from, to);
  return { deviceId, records, count: records.length, nextToken: null };
}


export async function getMockAlerts(deviceId, from, to) {
  await new Promise((resolve) => setTimeout(resolve, 220));
  const records = mockRecords(deviceId, from, to)
    .filter((record) => record.alerts.length)
    .reverse();
  return { deviceId, records, count: records.length, nextToken: null };
}
