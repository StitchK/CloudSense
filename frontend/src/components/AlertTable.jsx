import { BellOff } from "lucide-react";
import {
  METRICS,
  formatMetricValue,
  formatTimestamp,
} from "../constants";
import StatusPill from "./StatusPill";
import { notificationLabel } from "../records.js";


function rowsFromRecords(records) {
  return records.flatMap((record) =>
    (record.alerts || []).map((alert) => ({
      id: `${record.recordId}-${alert.metric}-${alert.severity}`,
      timestamp: record.timestamp,
      alert,
      value: record.metrics?.[alert.metric]?.value,
      unit: record.metrics?.[alert.metric]?.unit,
    })),
  );
}


export default function AlertTable({ records, loading, error }) {
  const rows = rowsFromRecords(records);

  if (error) return <div className="empty-state" role="status"><strong>Alert history is unavailable</strong><span>Try again. Alerts for this time range could not be checked.</span></div>;

  if (loading) {
    return (
      <div className="table-skeleton" aria-label="Loading alert history">
        <span />
        <span />
        <span />
      </div>
    );
  }
  if (!rows.length) {
    return (
      <div className="empty-state">
        <BellOff size={24} strokeWidth={1.6} aria-hidden="true" />
        <strong>No alerts in this time range</strong>
        <span>Warning and Critical events will appear here.</span>
      </div>
    );
  }

  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">Device alert history</caption>
        <thead>
          <tr>
            <th scope="col">Measured at</th>
            <th scope="col">Severity</th>
            <th scope="col">Metric</th>
            <th scope="col">Measured value</th>
            <th scope="col">Reason</th>
            <th scope="col">Notification status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{formatTimestamp(row.timestamp, { seconds: true })}</td>
              <td><StatusPill status={row.alert.severity} compact /></td>
              <td>{METRICS[row.alert.metric]?.label || row.alert.metric}</td>
              <td className="table-value">
                {formatMetricValue(row.alert.metric, row.value)} {row.unit}
              </td>
              <td>{row.alert.reason || "Reading outside the configured range"}</td>
              <td>{notificationLabel(row.alert.notificationStatus)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
