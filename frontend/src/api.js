import {
  getMockAlerts,
  getMockHistory,
  getMockLatest,
} from "./mockData";


function buildUrl(apiBase, path, parameters = {}) {
  const url = new URL(`${apiBase.replace(/\/$/, "")}${path}`);
  Object.entries(parameters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, value);
    }
  });
  return url;
}


async function request(apiBase, path, parameters, signal) {
  if (!apiBase) {
    throw new Error("请先在 .env 中配置 VITE_API_BASE_URL");
  }

  const response = await fetch(buildUrl(apiBase, path, parameters), {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.message || `API 请求失败：${response.status}`);
  }
  return body;
}


export async function fetchLatest(options) {
  const { apiBase, deviceId, signal, useMock } = options;
  if (useMock) return getMockLatest(deviceId);
  return request(
    apiBase,
    `/devices/${encodeURIComponent(deviceId)}/latest`,
    {},
    signal,
  );
}


export async function fetchHistory(options) {
  const { apiBase, deviceId, from, to, signal, useMock } = options;
  if (useMock) return getMockHistory(deviceId, from, to);
  return request(
    apiBase,
    `/devices/${encodeURIComponent(deviceId)}/history`,
    { from, to, order: "asc", limit: 200 },
    signal,
  );
}


export async function fetchAlerts(options) {
  const { apiBase, deviceId, from, to, signal, useMock } = options;
  if (useMock) return getMockAlerts(deviceId, from, to);
  return request(
    apiBase,
    `/devices/${encodeURIComponent(deviceId)}/alerts`,
    { from, to, order: "desc", limit: 100 },
    signal,
  );
}
