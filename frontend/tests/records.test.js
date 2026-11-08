import { test } from "node:test";
import assert from "node:assert/strict";
import { describeAlert, normalizeRecord, recordIsStale } from "../src/records.js";
import { updateAlertState } from "../src/alertState.js";
import { publicItem } from "./fixtures.js";

test("warning uses 偏 and critical uses 过 for the measured direction and value", () => {
  assert.equal(describeAlert("blood_pressure", { systolic: 150, diastolic: 95 }, "warning"), "血压偏高，测量值为 150/95 mmHg");
  assert.equal(describeAlert("blood_pressure", { systolic: 190, diastolic: 125 }, "critical"), "血压过高，测量值为 190/125 mmHg");
  assert.equal(describeAlert("blood_pressure", { systolic: 52, diastolic: 30 }, "critical"), "血压过低，测量值为 52/30 mmHg");
  assert.match(describeAlert("heart_rate_bpm", 110, "warning"), /心率偏高.*110/);
  assert.match(describeAlert("body_temperature_c", 38.5, "critical"), /体温过高.*38.5/);
  assert.match(describeAlert("spo2_pct", 93, "warning"), /血氧偏低.*93/);
  assert.match(describeAlert("blood_pressure", { systolic: 190, diastolic: 55 }, "critical"), /收缩压过高、舒张压偏低/);
});

test("description does not change backend severity, and critical is first in mixed alerts", () => {
  const record = normalizeRecord(publicItem());
  assert.equal(record.overallStatus, "critical");
  assert.equal(record.alerts[0].metric, "spo2_pct");
  assert.equal(record.alerts.find((alert) => alert.metric === "heart_rate_bpm").severity, "warning");
  assert.equal(record.metrics.body_temperature_c.value, 36.7);
});

test("staleness preserves classification and is not inferred from the late-arrival flag", () => {
  const record = normalizeRecord(publicItem());
  const measured = new Date(record.timestamp).getTime();
  assert.equal(recordIsStale({ ...record, isLate: true }, measured + 5000), false);
  assert.equal(recordIsStale(record, measured + 301000), true);
  assert.equal(recordIsStale({ ...record, isStale: true }, measured), true);
  assert.equal(record.overallStatus, "critical");
});

test("alerts do not repeat unchanged; escalation and recurrence after recovery notify", () => {
  const warning = { alerts: [{ metric: "spo2_pct", severity: "warning" }] };
  const first = updateAlertState(warning, {});
  assert.equal(first.notify, true);
  assert.equal(updateAlertState(warning, first.current).notify, false);
  assert.equal(updateAlertState({ alerts: [{ metric: "spo2_pct", severity: "critical" }] }, first.current).notify, true);
  const recovered = updateAlertState({ alerts: [] }, first.current);
  assert.equal(recovered.notify, false);
  assert.equal(updateAlertState(warning, recovered.current).notify, true);
});
