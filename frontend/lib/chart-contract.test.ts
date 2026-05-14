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

  it("rejects axis charts whose series values are all null or blank", () => {
    const chart: ChartDef = {
      id: "macro",
      type: "line",
      title: "Macro Signal",
      description: "Macro data.",
      xAxisKey: "date",
      series: [{ dataKey: "value", label: "Value", color: "#3b82f6" }],
      data: [
        { date: "2026-01-01", value: "" },
        { date: "2026-02-01", value: null as unknown as number },
      ],
    };

    expect(validateChartRenderContract("macro", chart)).toContain(
      "series value has no finite numeric values",
    );
  });

  it("rejects unsupported composed-series render options", () => {
    const chart = {
      id: "macro",
      type: "composed",
      title: "Macro Signal",
      description: "Macro data.",
      xAxisKey: "date",
      series: [
        {
          dataKey: "value",
          label: "Value",
          color: "#3b82f6",
          type: "candlestick",
          yAxisId: "center",
        },
      ],
      data: [{ date: "2026-01-01", value: 1.2 }],
    } as unknown as ChartDef;

    expect(validateChartRenderContract("macro", chart)).toEqual([
      "series value has unsupported yAxisId center",
      "series value has unsupported composed type candlestick",
    ]);
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

  it("accepts governed polar, hierarchy, funnel, and flow chart families", () => {
    const charts: Record<string, ChartDef> = {
      radar: {
        id: "radar",
        type: "radar",
        title: "Risk Profile",
        description: "Normalized risk profile.",
        angleKey: "metric",
        series: [{ dataKey: "score", label: "Score", color: "#3b82f6" }],
        data: [{ metric: "Labor", score: 70 }],
      },
      radial: {
        id: "radial",
        type: "radialBar",
        title: "Signal Incidence",
        description: "Signal counts.",
        data: [{ name: "Labor", value: 12, color: "#3b82f6" }],
      },
      funnel: {
        id: "funnel",
        type: "funnel",
        title: "Filter Funnel",
        description: "Staged filters.",
        data: [{ name: "All", value: 120, color: "#3b82f6" }],
      },
      treemap: {
        id: "treemap",
        type: "treemap",
        title: "Contribution Map",
        description: "Contribution hierarchy.",
        data: [{ name: "Labor", size: 40, color: "#3b82f6" }],
      },
      sankey: {
        id: "sankey",
        type: "sankey",
        title: "Signal Flow",
        description: "Flow decomposition.",
        data: {
          nodes: [{ name: "Inputs" }, { name: "Labor" }],
          links: [{ source: 0, target: 1, value: 12 }],
        },
      },
      sunburst: {
        id: "sunburst",
        type: "sunburst",
        title: "Contribution Hierarchy",
        description: "Nested contributions.",
        data: { name: "Total", children: [{ name: "Labor", value: 40 }] },
      },
    };

    for (const [chartId, chart] of Object.entries(charts)) {
      expect(validateChartRenderContract(chartId, chart)).toEqual([]);
    }
  });

  it("rejects all-zero radar charts that collapse to invisible marks", () => {
    const chart: ChartDef = {
      id: "radar",
      type: "radar",
      title: "Current Risk Profile",
      description: "All current risk components are zero.",
      angleKey: "metric",
      series: [{ dataKey: "score", label: "Score", color: "#3b82f6" }],
      data: [
        { metric: "Curve", score: 0 },
        { metric: "Labor", score: 0 },
      ],
    };

    expect(validateChartRenderContract("radar", chart)).toContain(
      "radar chart has no positive finite values and may render invisible",
    );
  });

  it("rejects invalid hierarchy and flow chart contracts", () => {
    const treemap = {
      id: "treemap",
      type: "treemap",
      title: "Broken Treemap",
      description: "Invalid hierarchy.",
      data: [{ name: "Labor", children: [] }],
    } as unknown as ChartDef;
    expect(validateChartRenderContract("treemap", treemap)).toContain(
      "treemap node 0 children must include at least one item",
    );

    const sankey = {
      id: "sankey",
      type: "sankey",
      title: "Broken Sankey",
      description: "Invalid link.",
      data: {
        nodes: [{ name: "Inputs" }],
        links: [{ source: 0, target: 2, value: Number.POSITIVE_INFINITY }],
      },
    } as unknown as ChartDef;
    expect(validateChartRenderContract("sankey", sankey)).toEqual([
      "sankey link 0 target index is invalid",
      "sankey link 0 value must be positive and finite",
    ]);
  });
});
