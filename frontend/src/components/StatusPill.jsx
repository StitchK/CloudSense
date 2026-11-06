import { STATUS_LABELS } from "../constants";


export default function StatusPill({ status = "unknown", compact = false }) {
  const safeStatus = STATUS_LABELS[status] ? status : "unknown";
  return (
    <span className={`status-pill status-${safeStatus} ${compact ? "compact" : ""}`}>
      <span className="status-symbol" aria-hidden="true" />
      {STATUS_LABELS[safeStatus]}
    </span>
  );
}
