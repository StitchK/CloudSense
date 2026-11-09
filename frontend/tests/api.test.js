import { test, afterEach } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { fetchLatest, fetchHistory, fetchAlerts } from "../src/api.js";
import { storedItem, publicItem } from "./fixtures.js";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
const options = {
  apiBase: "https://example.test", deviceId: "device-001",
  from: "2026-11-05T00:00:00.123Z", to: "2026-11-06T00:00:00.456Z",
};
const response = (body, status = 200) => ({ ok: status === 200, status, json: async () => body });

test("frontend requests and data conversion work with the real Python Lambda3 Handler", async () => {
  const root = fileURLToPath(new URL("../../", import.meta.url));
  const python = `
import sys,json
from unittest.mock import Mock
sys.path.insert(0,sys.argv[1])
from src.query import app
payload=json.load(sys.stdin)
table=Mock()
table.query.return_value={"Items":[payload["item"]]}
app.get_table=lambda: table
app.time.time=lambda: payload["item"]["measured_at_epoch"]+5
print(json.dumps(app.lambda_handler(payload["event"],None)))
`;
  globalThis.fetch = async (url) => {
    const path = new URL(url);
    const view = path.pathname.split("/").at(-1);
    assert.equal(path.searchParams.has("order"), false);
    const event = {
      version: "2.0", routeKey: `GET /devices/{device_id}/${view}`,
      requestContext: { http: { method: "GET" } }, pathParameters: { device_id: options.deviceId },
      queryStringParameters: Object.fromEntries(path.searchParams),
    };
    const result = JSON.parse(execFileSync(process.env.PYTHON || "python3", ["-c", python, root], {
      input: JSON.stringify({ item: storedItem(), event }), encoding: "utf8",
    }));
    assert.equal(result.statusCode, 200, result.body);
    return response(JSON.parse(result.body));
  };
  const latest = await fetchLatest(options);
  assert.equal(latest.metrics.heart_rate_bpm.value, 110);
  assert.equal(latest.metrics.spo2_pct.status, "critical");
  assert.equal(latest.overallStatus, "critical");
  assert.equal(latest.alerts[0].notificationStatus, "CRITICAL_PENDING");
  assert.equal(latest.alerts[0].reason, "Blood oxygen is very low; measured value: 89 %");
  assert.equal(latest.isStale, false);
  for (const fetchList of [fetchHistory, fetchAlerts]) {
    const list = await fetchList(options);
    assert.equal(list.records.length, 1);
    assert.equal(list.records[0].recordId, latest.recordId);
  }
});

test("reads beyond empty filtered pages, freezes the time window and sorts history", async () => {
  const pages = [
    { items: [], next_token: "page-two" },
    { items: [publicItem("new", "2026-11-06T00:00:00Z")], next_token: "page-three" },
    { items: [publicItem("old", "2026-11-05T01:00:00Z")], next_token: null },
  ];
  const requests = [];
  globalThis.fetch = async (url) => { requests.push(new URL(url)); return response(pages.shift()); };
  const result = await fetchHistory(options);
  assert.deepEqual(result.records.map((record) => record.recordId), ["old", "new"]);
  assert.equal(requests.length, 3);
  assert.equal(requests[1].searchParams.get("next_token"), "page-two");
  assert.equal(requests[2].searchParams.get("next_token"), "page-three");
  for (const request of requests) {
    assert.equal(request.searchParams.get("from"), "2026-11-05T00:00:00Z");
    assert.equal(request.searchParams.get("to"), "2026-11-06T00:00:00Z");
    assert.equal(request.searchParams.get("limit"), "100");
  }
});

test("alert records are newest first and later-page errors never appear as no alerts", async () => {
  let calls = 0;
  globalThis.fetch = async () => response({ items: [publicItem("old", "2026-11-05T01:00:00Z"), publicItem("new")], next_token: null });
  assert.deepEqual((await fetchAlerts(options)).records.map((record) => record.recordId), ["new", "old"]);
  globalThis.fetch = async () => ++calls === 1
    ? response({ items: [], next_token: "next" }) : response({ message: "Service unavailable" }, 503);
  await assert.rejects(fetchAlerts(options), /Service unavailable/);
});

test("missing latest is an empty device, while authorization and service errors remain errors", async () => {
  globalThis.fetch = async () => response({ message: "No readings" }, 404);
  assert.equal(await fetchLatest(options), null);
  globalThis.fetch = async () => response({ message: "Forbidden" }, 403);
  await assert.rejects(fetchLatest(options), /Forbidden/);
});

test("rejects a repeated page cursor instead of looping forever", async () => {
  globalThis.fetch = async () => response({ items: [], next_token: "same" });
  await assert.rejects(fetchHistory(options), /Pagination could not continue/);
});
