"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const DATE_LIKE = /date|_ts$|timestamp|month|quarter|day|year/i;
const SERIES_COLORS = ["#D4A643", "#4FB286", "#E2694B", "#7C93C9"];

/**
 * Picks a chart shape from the result columns/rows, or returns null when
 * the data isn't chart-shaped -- callers fall back to table-only in that
 * case rather than forcing a misleading chart onto arbitrary rows.
 */
export function pickChart(columns, rows) {
  if (!rows || rows.length < 2 || rows.length > 50 || !columns?.length) return null;

  const numericCols = columns.filter((c) => rows.every((r) => typeof r[c] === "number"));
  const otherCols = columns.filter((c) => !numericCols.includes(c));
  if (numericCols.length === 0 || otherCols.length === 0) return null;

  const category = otherCols[0];
  const isTimeSeries = DATE_LIKE.test(category);
  const series = numericCols.slice(0, 3); // cap at 3 series so the legend stays readable

  return {
    kind: isTimeSeries ? "line" : "bar",
    category,
    series,
  };
}

export default function ResultsChart({ columns, rows }) {
  const shape = pickChart(columns, rows);
  if (!shape) return null;

  const ChartComponent = shape.kind === "line" ? LineChart : BarChart;

  return (
    <div className="mt-3 rounded-lg border border-ink-600 bg-ink-800/60 p-3">
      <ResponsiveContainer width="100%" height={240}>
        <ChartComponent data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
          <CartesianGrid stroke="#242C38" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey={shape.category}
            tick={{ fill: "#8B93A1", fontSize: 11 }}
            axisLine={{ stroke: "#333D4C" }}
            tickLine={false}
          />
          <YAxis tick={{ fill: "#8B93A1", fontSize: 11 }} axisLine={{ stroke: "#333D4C" }} tickLine={false} />
          <Tooltip
            contentStyle={{
              background: "#151B23",
              border: "1px solid #333D4C",
              borderRadius: 6,
              fontSize: 12,
            }}
            labelStyle={{ color: "#F2EFE7" }}
          />
          {shape.series.length > 1 && <Legend wrapperStyle={{ fontSize: 11, color: "#8B93A1" }} />}
          {shape.series.map((key, i) =>
            shape.kind === "line" ? (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                strokeWidth={2}
                dot={false}
              />
            ) : (
              <Bar key={key} dataKey={key} fill={SERIES_COLORS[i % SERIES_COLORS.length]} radius={[3, 3, 0, 0]} />
            )
          )}
        </ChartComponent>
      </ResponsiveContainer>
    </div>
  );
}
