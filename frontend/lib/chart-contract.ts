import type { ChartDef } from "@/lib/types";

function isFiniteNumber(value: unknown): boolean {
  return Number.isFinite(Number(value));
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

export function validateChartRenderContract(chartId: string, chart: ChartDef): string[] {
  const issues: string[] = [];
  if (chart.id !== chartId) {
    issues.push(`chart id mismatch: expected ${chartId}, received ${chart.id}`);
  }
  if (!nonEmptyString(chart.title)) {
    issues.push("chart title is required");
  }
  if (!Array.isArray(chart.data) || chart.data.length === 0) {
    issues.push("chart data must include at least one row");
    return issues;
  }

  if (
    chart.type === "line" ||
    chart.type === "bar" ||
    chart.type === "area" ||
    chart.type === "composed"
  ) {
    if (!nonEmptyString(chart.xAxisKey)) {
      issues.push("axis chart xAxisKey is required");
    }
    if (!Array.isArray(chart.series) || chart.series.length === 0) {
      issues.push("axis chart series must include at least one item");
    }
    for (const [rowIndex, row] of chart.data.entries()) {
      if (!(chart.xAxisKey in row) || row[chart.xAxisKey] == null || row[chart.xAxisKey] === "") {
        issues.push(`row ${rowIndex} is missing xAxisKey ${chart.xAxisKey}`);
        break;
      }
    }
    for (const series of chart.series) {
      if (!nonEmptyString(series.dataKey)) {
        issues.push("series dataKey is required");
        continue;
      }
      const usableValues = chart.data.filter((row) => isFiniteNumber(row[series.dataKey]));
      if (usableValues.length === 0) {
        issues.push(`series ${series.dataKey} has no finite numeric values`);
      }
      if (!nonEmptyString(series.label)) {
        issues.push(`series ${series.dataKey} label is required`);
      }
      if (!nonEmptyString(series.color)) {
        issues.push(`series ${series.dataKey} color is required`);
      }
    }
    return issues;
  }

  if (chart.type === "scatter") {
    for (const key of [chart.xKey, chart.yKey]) {
      if (!nonEmptyString(key)) {
        issues.push("scatter chart xKey and yKey are required");
        continue;
      }
      if (chart.data.every((row) => !isFiniteNumber(row[key]))) {
        issues.push(`scatter key ${key} has no finite numeric values`);
      }
    }
    return issues;
  }

  if (chart.type === "pie") {
    chart.data.forEach((row, index) => {
      if (!nonEmptyString(row.name)) {
        issues.push(`pie slice ${index} name is required`);
      }
      if (!isFiniteNumber(row.value)) {
        issues.push(`pie slice ${index} value must be finite`);
      }
    });
  }

  return issues;
}
