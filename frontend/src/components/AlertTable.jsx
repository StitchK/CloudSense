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

  if (error) return <div className="empty-state" role="status"><strong>异常记录暂时无法加载</strong><span>请重试，当前无法确认此时间范围内是否有异常。</span></div>;

  if (loading) {
    return (
      <div className="table-skeleton" aria-label="异常记录加载中">
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
        <strong>当前范围内没有异常</strong>
        <span>Warning 和 Critical 事件会保留在这里。</span>
      </div>
    );
  }

  return (
    <div className="table-wrap">
      <table>
        <caption className="sr-only">设备异常记录</caption>
        <thead>
          <tr>
            <th scope="col">检测时间</th>
            <th scope="col">等级</th>
            <th scope="col">异常参数</th>
            <th scope="col">测量值</th>
            <th scope="col">原因</th>
            <th scope="col">通知状态</th>
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
              <td>{row.alert.reason || "指标超出设定范围"}</td>
              <td>{notificationLabel(row.alert.notificationStatus)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
