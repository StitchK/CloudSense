import { useEffect, useRef } from "react";
import { AlertTriangle, X } from "lucide-react";
import {
  METRICS,
  formatMetricValue,
  formatTimestamp,
} from "../constants";
import StatusPill from "./StatusPill";


export default function AlertDialog({ record, onClose, onViewTrend }) {
  const dialogRef = useRef(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return undefined;
    if (!dialog.open) dialog.showModal();
    const handleCancel = (event) => {
      event.preventDefault();
      onClose();
    };
    dialog.addEventListener("cancel", handleCancel);
    return () => {
      dialog.removeEventListener("cancel", handleCancel);
      if (dialog.open) dialog.close();
    };
  }, [onClose]);

  if (!record?.alerts?.length) return null;
  const primaryAlert = record.alerts[0];

  return (
    <dialog ref={dialogRef} className="alert-dialog" aria-labelledby="alert-title">
      <div className="dialog-heading">
        <div className="dialog-icon" aria-hidden="true">
          <AlertTriangle size={22} strokeWidth={2} />
        </div>
        <div>
          <StatusPill status={primaryAlert.severity} compact />
          <h2 id="alert-title">New abnormal reading detected</h2>
          <p>{formatTimestamp(record.timestamp, { seconds: true })}</p>
        </div>
        <button className="icon-button" type="button" onClick={onClose} aria-label="Close alert">
          <X size={20} aria-hidden="true" />
        </button>
      </div>

      <div className="dialog-alert-list">
        {record.alerts.map((alert) => {
          const metric = record.metrics?.[alert.metric];
          return (
            <article key={`${alert.metric}-${alert.severity}`}>
              <div>
                <strong>{METRICS[alert.metric]?.label || alert.metric}</strong>
                <StatusPill status={alert.severity} compact />
              </div>
              <p className="dialog-value">
                {formatMetricValue(alert.metric, metric?.value)}
                <span>{metric?.unit}</span>
              </p>
              <p>{alert.reason || "This reading is outside the configured range."}</p>
            </article>
          );
        })}
      </div>

      <p className="dialog-note">
        Dismissing this message acknowledges it. The alert status remains until the readings return to normal.
      </p>
      <div className="dialog-actions">
        <button
          type="button"
          className="secondary-button"
          onClick={() => onViewTrend(primaryAlert.metric)}
        >
          View trend
        </button>
        <button type="button" className="primary-button" onClick={onClose} autoFocus>
          Got it
        </button>
      </div>
    </dialog>
  );
}
