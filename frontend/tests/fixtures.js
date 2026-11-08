export function storedItem(id = "reading-001", timestamp = "2026-11-06T00:00:00Z") {
  return {
    reading: {
      device_id: "device-001", reading_id: id, timestamp, activity: "rest",
      heart_rate_bpm: 110, body_temperature_c: 36.7, spo2_pct: 89,
      blood_pressure: { systolic: 150, diastolic: 95 },
    },
    evaluations: [
      { metric: "heart_rate_bpm", level: "warning", message: "Heart rate: 110 bpm, level: warning" },
      { metric: "body_temperature_c", level: "normal" },
      { metric: "spo2_pct", level: "critical", message: "Blood oxygen: 89%, level: critical" },
      { metric: "blood_pressure", level: "warning" },
    ],
    alert_history: { spo2_pct: { status: "CRITICAL_PENDING" } },
    measured_at_epoch: Math.floor(new Date(timestamp).getTime() / 1000),
    processing_status: "COMPLETE", is_late: false,
  };
}

export function publicItem(id, timestamp) {
  const item = storedItem(id, timestamp);
  return { ...item, overall_status: "critical", alerts: item.evaluations
    .filter((entry) => ["warning", "critical"].includes(entry.level))
    .map((entry) => ({ ...entry, notification_status: item.alert_history[entry.metric]?.status })) };
}
