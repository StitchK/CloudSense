import { getMockAlerts, getMockHistory, getMockLatest } from "./mockData.js";
import { normalizeRecord } from "./records.js";

export function wholeSecond(value) {
  const date = new Date(value);
  date.setUTCMilliseconds(0);
  return date.toISOString().replace(".000Z", "Z");
}

async function request(apiBase, path, parameters, signal) {
  if (!apiBase) throw new Error("Configure the query API URL before connecting.");
  const url = new URL(`${apiBase.replace(/\/$/, "")}${path}`);
  Object.entries(parameters).forEach(([key, value]) => {
    if (value != null && value !== "") url.searchParams.set(key, value);
  });
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timeout = setTimeout(() => controller.abort(new Error("Request timed out. Please try again.")), 15000);
  try {
    const response = await fetch(url, {
      method: "GET", headers: { Accept: "application/json" }, signal: controller.signal,
    });
    const body = await response.json();
    if (!response.ok) {
      const error = new Error(body.message || `Query failed (HTTP ${response.status})`);
      error.status = response.status;
      throw error;
    }
    return body;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}

export async function fetchLatest({ apiBase, deviceId, signal, useMock }) {
  if (useMock) return getMockLatest(deviceId);
  try {
    const body = await request(apiBase, `/devices/${encodeURIComponent(deviceId)}/latest`, {}, signal);
    const record = normalizeRecord(body.data);
    if (record.deviceId !== deviceId) throw new Error("The returned device does not match the selected device.");
    return { ...record, isStale: body.is_stale, ageSeconds: body.age_seconds };
  } catch (error) {
    if (error.status === 404) return null;
    throw error;
  }
}

async function fetchPages({ apiBase, deviceId, from, to, signal }, view) {
  const end = wholeSecond(to || new Date());
  const start = wholeSecond(from || new Date(new Date(end).getTime() - 86400000));
  const records = new Map();
  const tokens = new Set();
  let token;
  for (let pageNumber = 0; pageNumber < 100; pageNumber += 1) {
    const body = await request(apiBase, `/devices/${encodeURIComponent(deviceId)}/${view}`, {
      from: start, to: end, limit: 100, next_token: token,
    }, signal);
    if (!Array.isArray(body.items)) throw new Error("The query returned an incomplete list response.");
    for (const item of body.items) {
      const record = normalizeRecord(item);
      if (record.deviceId !== deviceId) throw new Error("The returned device does not match the selected device.");
      records.set(record.recordId, record);
    }
    token = body.next_token;
    if (!token) {
      const sorted = [...records.values()].sort((a, b) =>
        new Date(a.timestamp) - new Date(b.timestamp) || a.recordId.localeCompare(b.recordId));
      if (view === "alerts") sorted.reverse();
      return { deviceId, records: sorted, count: sorted.length };
    }
    if (tokens.has(token)) throw new Error("Pagination could not continue. Retry or select a shorter time range.");
    tokens.add(token);
  }
  throw new Error("Too many readings. Select a shorter time range and try again.");
}

export async function fetchHistory(options) {
  return options.useMock
    ? getMockHistory(options.deviceId, options.from, options.to)
    : fetchPages(options, "history");
}

export async function fetchAlerts(options) {
  return options.useMock
    ? getMockAlerts(options.deviceId, options.from, options.to)
    : fetchPages(options, "alerts");
}
