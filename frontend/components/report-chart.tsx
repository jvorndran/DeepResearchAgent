"use client";

import {
  LineChart, Line,
  BarChart, Bar,
  AreaChart, Area,
  ScatterChart, Scatter,
  PieChart, Pie,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import type { ChartDef } from "@/lib/types";

interface ReportChartProps {
  chartId: string;
  chart: ChartDef;
}

export default function ReportChart({ chartId, chart }: ReportChartProps) {
  return (
    <div className="h-[400px] w-full mt-8 mb-8" key={chartId}>
      <h3 className="text-lg font-semibold mb-2 text-center">{chart.title}</h3>
      <ResponsiveContainer width="100%" height="100%">
        {chart.type === "line" ? (
          <LineChart data={chart.data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={chart.xAxisKey} />
            <YAxis />
            <Tooltip />
            <Legend />
            {chart.series.map((s, i) => (
              <Line key={i} type="monotone" dataKey={s.dataKey} name={s.label} stroke={s.color} />
            ))}
          </LineChart>
        ) : chart.type === "bar" ? (
          <BarChart data={chart.data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={chart.xAxisKey} />
            <YAxis />
            <Tooltip />
            <Legend />
            {chart.series.map((s, i) => (
              <Bar key={i} dataKey={s.dataKey} name={s.label} fill={s.color} />
            ))}
          </BarChart>
        ) : chart.type === "area" ? (
          <AreaChart data={chart.data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={chart.xAxisKey} />
            <YAxis />
            <Tooltip />
            <Legend />
            {chart.series.map((s, i) => (
              <Area key={i} type="monotone" dataKey={s.dataKey} name={s.label} fill={s.color} stroke={s.color} />
            ))}
          </AreaChart>
        ) : chart.type === "scatter" ? (
          <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
            <CartesianGrid />
            <XAxis type="number" dataKey={chart.xKey} name={chart.xLabel} />
            <YAxis type="number" dataKey={chart.yKey} name={chart.yLabel} />
            <Tooltip cursor={{ strokeDasharray: "3 3" }} />
            <Legend />
            <Scatter name={chart.title} data={chart.data} fill={chart.color} />
          </ScatterChart>
        ) : (
          <PieChart>
            <Pie data={chart.data} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={150} fill="#8884d8" label />
            <Tooltip />
            <Legend />
          </PieChart>
        )}
      </ResponsiveContainer>
      <p className="text-sm text-muted-foreground text-center mt-2">{chart.description}</p>
    </div>
  );
}
