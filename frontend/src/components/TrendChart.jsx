import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  AriaComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { METRICS, formatMetricValue, formatTimestamp } from "../constants";


echarts.use([
  LineChart,
  AriaComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
]);


function pointStatus(record, metricKey) {
  return record.metrics?.[metricKey]?.status || "unknown";
}


function statusColor(status, fallback) {
  if (status === "critical") return "#fb7185";
  if (status === "warning") return "#fbbf24";
  return fallback;
}


function seriesForMetric(records, metricKey) {
  const config = METRICS[metricKey];
  if (metricKey === "blood_pressure") {
    return [
      {
        name: "收缩压",
        type: "line",
        smooth: 0.28,
        symbol: "circle",
        symbolSize: 7,
        lineStyle: { width: 2.5, color: config.color },
        itemStyle: { color: config.color },
        data: records.map((record) => ({
          value: record.metrics?.blood_pressure?.value?.systolic,
          itemStyle: { color: statusColor(pointStatus(record, metricKey), config.color) },
          symbolSize: ["warning", "critical"].includes(pointStatus(record, metricKey)) ? 11 : 7,
        })),
      },
      {
        name: "舒张压",
        type: "line",
        smooth: 0.28,
        symbol: "diamond",
        symbolSize: 7,
        lineStyle: { width: 2, type: "dashed", color: "#38bdf8" },
        itemStyle: { color: "#38bdf8" },
        data: records.map((record) => ({
          value: record.metrics?.blood_pressure?.value?.diastolic,
          itemStyle: { color: statusColor(pointStatus(record, metricKey), "#38bdf8") },
          symbolSize: ["warning", "critical"].includes(pointStatus(record, metricKey)) ? 11 : 7,
        })),
      },
    ];
  }

  return [
    {
      name: config.label,
      type: "line",
      smooth: 0.28,
      connectNulls: true,
      symbol: "circle",
      symbolSize: 7,
      lineStyle: { width: 2.5, color: config.color },
      areaStyle: { color: `${config.color}20` },
      data: records.map((record) => {
        const metric = record.metrics?.[metricKey];
        return {
          value: metric?.value ?? null,
          itemStyle: {
            color: statusColor(pointStatus(record, metricKey), config.color),
            borderColor: "#08111f",
            borderWidth: 2,
          },
          symbolSize: metric?.status === "normal" ? 7 : 11,
        };
      }),
    },
  ];
}


export default function TrendChart({ records, metricKey, loading, error }) {
  const chartElement = useRef(null);
  const config = METRICS[metricKey];
  const option = {
    animationDuration: 350,
    backgroundColor: "transparent",
    aria: {
      enabled: true,
      decal: { show: true },
      description: `${config.label}历史趋势，共 ${records.length} 个数据点`,
    },
    grid: { left: 12, right: 18, top: 42, bottom: 12, containLabel: true },
    legend: {
      show: metricKey === "blood_pressure",
      top: 4,
      right: 8,
      textStyle: { color: "#a8b4c8" },
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: "#101a2c",
      borderColor: "#33445f",
      textStyle: { color: "#f8fafc" },
      formatter(parameters) {
        const index = parameters[0]?.dataIndex ?? 0;
        const record = records[index];
        const header = formatTimestamp(record?.timestamp, { seconds: true });
        const values = parameters
          .map((parameter) => {
            const raw = parameter.data?.value ?? parameter.data;
            return `${parameter.marker}${parameter.seriesName}：${raw ?? "--"}`;
          })
          .join("<br/>");
        return `${header}<br/>${values}`;
      },
    },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: records.map((record) => formatTimestamp(record.timestamp)),
      axisLine: { lineStyle: { color: "#33445f" } },
      axisTick: { show: false },
      axisLabel: { color: "#8090a8", hideOverlap: true, margin: 14 },
    },
    yAxis: {
      type: "value",
      scale: true,
      name: records[0]?.metrics?.[metricKey]?.unit || "",
      nameTextStyle: { color: "#8090a8", padding: [0, 0, 8, 0] },
      axisLabel: { color: "#8090a8" },
      splitLine: { lineStyle: { color: "rgba(148, 163, 184, 0.12)" } },
    },
    series: seriesForMetric(records, metricKey),
  };

  useEffect(() => {
    if (error || loading || !records.length || !chartElement.current) return undefined;
    const chart = echarts.init(chartElement.current, undefined, {
      renderer: "canvas",
    });
    chart.setOption(option, true);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(chartElement.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [error, loading, metricKey, records]);

  if (error) return <div key="error" className="empty-state chart-empty"><strong>历史趋势暂时无法加载</strong><span>请重试或选择更短的时间范围。</span></div>;

  if (loading) {
    return <div key="loading" className="chart-skeleton" aria-label="历史趋势加载中" />;
  }
  if (!records.length) {
    return (
      <div key="empty" className="empty-state chart-empty">
        <strong>暂无趋势数据</strong>
        <span>选择其他时间范围或确认设备已经上传数据。</span>
      </div>
    );
  }

  return (
    <div
      key="chart"
      ref={chartElement}
      className="trend-chart"
      aria-label={`${config.label}历史趋势图。最新值为 ${formatMetricValue(
        metricKey,
        records.at(-1)?.metrics?.[metricKey]?.value,
      )}`}
      role="img"
    />
  );
}
