import { describe, expect, it } from "vitest";
import type { ChartDef } from "@/lib/types";
import { validateChartRenderContract } from "@/lib/chart-contract";

describe("validateChartRenderContract", () => {
  it("accepts a canonical Recharts axis chart", () => {
    const chart: ChartDef = {
      id: "macro",
      type: "line",
      title: "Macro Signal",
      description: "Macro data.",
      xAxisKey: "date",
      series: [{ dataKey: "value", label: "Value", color: "#3b82f6" }],
      data: [
        { date: "2026-01-01", value: 1.2 },
        { date: "2026-02-01", value: 1.4 },
      ],
    };

    expect(validateChartRenderContract("macro", chart)).toEqual([]);
  });

  it("rejects axis charts whose series keys do not exist in numeric rows", () => {
    const chart: ChartDef = {
      id: "macro",
      type: "line",
      title: "Macro Signal",
      description: "Macro data.",
      xAxisKey: "date",
      series: [{ dataKey: "missing", label: "Missing", color: "#3b82f6" }],
      data: [{ date: "2026-01-01", value: 1.2 }],
    };

    expect(validateChartRenderContract("macro", chart)).toContain(
      "series missing has no finite numeric values",
    );
  });

  it("rejects scatter charts without numeric x and y values", () => {
    const chart: ChartDef = {
      id: "scatter",
      type: "scatter",
      title: "Scatter",
      description: "Scatter data.",
      xKey: "x",
      yKey: "y",
      xLabel: "X",
      yLabel: "Y",
      color: "#3b82f6",
      data: [{ x: Number.NaN, y: Number.NaN }],
    };

    expect(validateChartRenderContract("scatter", chart)).toEqual([
      "scatter key x has no finite numeric values",
      "scatter key y has no finite numeric values",
    ]);
  });
});
