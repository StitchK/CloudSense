const PRIORITY = { normal: 0, warning: 1, critical: 2 };

export function readPreference(key, fallback) {
  try { return localStorage.getItem(key) || fallback; } catch { return fallback; }
}

export function writePreference(key, value) {
  try { localStorage.setItem(key, value); } catch { /* Storage can be disabled. */ }
}

export function updateAlertState(record, previous) {
  previous = previous && typeof previous === "object" ? previous : {};
  const current = Object.fromEntries((record?.alerts || []).map((alert) => [alert.metric, alert.severity]));
  const notify = Object.entries(current).some(([metric, severity]) =>
    !previous[metric] || PRIORITY[severity] > PRIORITY[previous[metric]]);
  return { current, notify };
}
