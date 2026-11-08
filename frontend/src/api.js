import { getMockAlerts, getMockHistory, getMockLatest } from "./mockData.js";
import { normalizeRecord } from "./records.js";

export function wholeSecond(value) {
  const date = new Date(value);
  date.setUTCMilliseconds(0);
  return date.toISOString().replace(".000Z", "Z");
}

async function request(apiBase, path, parameters, signal) {
  if (!apiBase) throw new Error("请先在 .env.local 中配置 VITE_API_BASE_URL");
  const url = new URL(`${apiBase.replace(/\/$/, "")}${path}`);
  Object.entries(parameters).forEach(([key, value]) => {
    if (value != null && value !== "") url.searchParams.set(key, value);
  });
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timeout = setTimeout(() => controller.abort(new Error("请求超时，请稍后重试")), 15000);
  try {
    const response = await fetch(url, {
      method: "GET", headers: { Accept: "application/json" }, signal: controller.signal,
    });
    const body = await response.json();
    if (!response.ok) {
      const error = new Error(body.message || `查询失败（HTTP ${response.status}）`);
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
    if (record.deviceId !== deviceId) throw new Error("接口返回的设备与当前选择不一致");
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
    if (!Array.isArray(body.items)) throw new Error("查询接口返回的列表格式不完整");
    for (const item of body.items) {
      const record = normalizeRecord(item);
      if (record.deviceId !== deviceId) throw new Error("接口返回的设备与当前选择不一致");
      records.set(record.recordId, record);
    }
    token = body.next_token;
    if (!token) {
      const sorted = [...records.values()].sort((a, b) =>
        new Date(a.timestamp) - new Date(b.timestamp) || a.recordId.localeCompare(b.recordId));
      if (view === "alerts") sorted.reverse();
      return { deviceId, records: sorted, count: sorted.length };
    }
    if (tokens.has(token)) throw new Error("查询分页未能继续，请重试或缩短时间范围");
    tokens.add(token);
  }
  throw new Error("查询范围内数据较多，请缩短时间范围后重试");
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
