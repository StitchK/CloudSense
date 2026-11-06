import { BellOff } from "lucide-react";
import {
  METRICS,
  formatMetricValue,
  formatTimestamp,
} from "../constants";
import StatusPill from "./StatusPill";


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


export default function AlertTable({ records, loading }) {
  const rows = rowsFromRecords(records);

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
            <th scope="col">当前值</th>
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
              <td>{row.alert.notificationStatus || "--"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
