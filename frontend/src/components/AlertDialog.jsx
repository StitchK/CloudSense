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
          <h2 id="alert-title">检测到新的身体指标异常</h2>
          <p>{formatTimestamp(record.timestamp, { seconds: true })}</p>
        </div>
        <button className="icon-button" type="button" onClick={onClose} aria-label="关闭异常提醒">
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
              <p>{alert.reason || "当前值超出项目设置的安全范围"}</p>
            </article>
          );
        })}
      </div>

      <p className="dialog-note">
        关闭仅表示已查看。异常恢复正常后，当前告警状态才会解除。
      </p>
      <div className="dialog-actions">
        <button
          type="button"
          className="secondary-button"
          onClick={() => onViewTrend(primaryAlert.metric)}
        >
          查看趋势
        </button>
        <button type="button" className="primary-button" onClick={onClose} autoFocus>
          我知道了
        </button>
      </div>
    </dialog>
  );
}
