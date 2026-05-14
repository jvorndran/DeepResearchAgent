import type { ChartDef, HierarchyDatum } from "@/lib/types";

function isFiniteNumber(value: unknown): boolean {
  if (value == null || value === "") {
    return false;
  }
  return Number.isFinite(Number(value));
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function positiveFiniteNumber(value: unknown): boolean {
  return isFiniteNumber(value) && Number(value) > 0;
}

function segmentKey(value: string | undefined, fallback: string): string {
  return nonEmptyString(value) ? value : fallback;
}

function hierarchyValueKey(nodes: HierarchyDatum | HierarchyDatum[], preferred?: "size" | "value"): "size" | "value" {
  if (preferred) {
    return preferred;
  }
  const stack = Array.isArray(nodes) ? [...nodes] : [nodes];
  while (stack.length) {
    const node = stack.shift();
    if (!node) continue;
    if (node.size != null) return "size";
    if (node.value != null) return "value";
    if (Array.isArray(node.children)) stack.push(...node.children);
  }
  return "value";
}

function validateHierarchyNode(
  node: unknown,
  path: string,
  valueKey: "size" | "value",
  issues: string[],
  options: { requireChildren?: boolean } = {},
): void {
  if (!node || typeof node !== "object") {
    issues.push(`${path} must be an object`);
    return;
  }
  const item = node as HierarchyDatum;
  if (!nonEmptyString(item.name)) {
    issues.push(`${path} name is required`);
  }
  if (item.children != null) {
    if (!Array.isArray(item.children) || item.children.length === 0) {
      issues.push(`${path} children must include at least one item`);
      return;
    }
    item.children.forEach((child, index) => {
      validateHierarchyNode(child, `${path}.children[${index}]`, valueKey, issues);
    });
    return;
  }
  if (options.requireChildren) {
    issues.push(`${path} children must include at least one item`);
    return;
  }
  const value = item[valueKey] ?? (valueKey === "size" ? item.value : item.size);
  if (!positiveFiniteNumber(value)) {
    issues.push(`${path} ${valueKey} must be positive and finite`);
  }
}

export function validateChartRenderContract(chartId: string, chart: ChartDef): string[] {
  const issues: string[] = [];
  if (chart.id !== chartId) {
    issues.push(`chart id mismatch: expected ${chartId}, received ${chart.id}`);
  }
  if (!nonEmptyString(chart.title)) {
    issues.push("chart title is required");
  }

  if (
    chart.type === "line" ||
    chart.type === "bar" ||
    chart.type === "area" ||
    chart.type === "composed"
  ) {
    if (!Array.isArray(chart.data) || chart.data.length === 0) {
      issues.push("chart data must include at least one row");
      return issues;
    }
    if (chart.layout && chart.layout !== "horizontal" && chart.layout !== "vertical") {
      issues.push(`axis chart layout ${chart.layout} is unsupported`);
    }
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
      if (series.yAxisId && series.yAxisId !== "left" && series.yAxisId !== "right") {
        issues.push(`series ${series.dataKey} has unsupported yAxisId ${series.yAxisId}`);
      }
      if (
        chart.type === "composed" &&
        series.type &&
        series.type !== "line" &&
        series.type !== "bar" &&
        series.type !== "area"
      ) {
        issues.push(`series ${series.dataKey} has unsupported composed type ${series.type}`);
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
      if (series.stackId != null && !nonEmptyString(series.stackId)) {
        issues.push(`series ${series.dataKey} stackId must be non-empty when provided`);
      }
    }
    return issues;
  }

  if (chart.type === "scatter") {
    if (!Array.isArray(chart.data) || chart.data.length === 0) {
      issues.push("chart data must include at least one row");
      return issues;
    }
    for (const key of [chart.xKey, chart.yKey]) {
      if (!nonEmptyString(key)) {
        issues.push("scatter chart xKey and yKey are required");
        continue;
      }
      if (chart.data.every((row) => !isFiniteNumber(row[key]))) {
        issues.push(`scatter key ${key} has no finite numeric values`);
      }
    }
    if (chart.sizeKey) {
      if (!nonEmptyString(chart.sizeKey)) {
        issues.push("scatter chart sizeKey must be non-empty when provided");
      } else if (chart.data.every((row) => !positiveFiniteNumber(row[chart.sizeKey!]))) {
        issues.push(`scatter sizeKey ${chart.sizeKey} has no positive finite values`);
      }
    }
    return issues;
  }

  if (chart.type === "pie" || chart.type === "radialBar" || chart.type === "funnel") {
    if (!Array.isArray(chart.data) || chart.data.length === 0) {
      issues.push("chart data must include at least one row");
      return issues;
    }
    const nameKey = chart.type === "funnel" ? segmentKey(chart.nameKey, "name") : "name";
    const dataKey = chart.type === "pie" ? "value" : segmentKey(chart.dataKey, "value");
    chart.data.forEach((row, index) => {
      if (!nonEmptyString((row as Record<string, unknown>)[nameKey])) {
        issues.push(`${chart.type} item ${index} ${nameKey} is required`);
      }
      const value = (row as Record<string, unknown>)[dataKey];
      if (!positiveFiniteNumber(value)) {
        issues.push(`${chart.type} item ${index} ${dataKey} must be positive and finite`);
      }
    });
    return issues;
  }

  if (chart.type === "radar") {
    if (!Array.isArray(chart.data) || chart.data.length === 0) {
      issues.push("chart data must include at least one row");
      return issues;
    }
    if (!nonEmptyString(chart.angleKey)) {
      issues.push("radar chart angleKey is required");
    } else if (chart.data.some((row) => row[chart.angleKey] == null || row[chart.angleKey] === "")) {
      issues.push(`one or more radar rows are missing angleKey ${chart.angleKey}`);
    }
    if (!Array.isArray(chart.series) || chart.series.length === 0) {
      issues.push("radar chart series must include at least one item");
    }
    let positiveSeries = 0;
    for (const series of chart.series) {
      if (!nonEmptyString(series.dataKey)) {
        issues.push("series dataKey is required");
        continue;
      }
      if (chart.data.every((row) => !isFiniteNumber(row[series.dataKey]))) {
        issues.push(`series ${series.dataKey} has no finite numeric values`);
      }
      if (chart.data.some((row) => positiveFiniteNumber(row[series.dataKey]))) {
        positiveSeries += 1;
      }
      if (!nonEmptyString(series.label)) {
        issues.push(`series ${series.dataKey} label is required`);
      }
      if (!nonEmptyString(series.color)) {
        issues.push(`series ${series.dataKey} color is required`);
      }
    }
    if (positiveSeries === 0) {
      issues.push("radar chart has no positive finite values and may render invisible");
    }
    return issues;
  }

  if (chart.type === "treemap") {
    if (!Array.isArray(chart.data) || chart.data.length === 0) {
      issues.push("chart data must include at least one row");
      return issues;
    }
    const valueKey = hierarchyValueKey(chart.data, chart.valueKey);
    chart.data.forEach((node, index) => {
      validateHierarchyNode(node, `treemap node ${index}`, valueKey, issues);
    });
    return issues;
  }

  if (chart.type === "sunburst") {
    const valueKey = hierarchyValueKey(chart.data, chart.valueKey);
    validateHierarchyNode(chart.data, "sunburst root", valueKey, issues, { requireChildren: true });
    return issues;
  }

  if (chart.type === "sankey") {
    const data = chart.data;
    if (!data || !Array.isArray(data.nodes) || data.nodes.length === 0) {
      issues.push("sankey data.nodes must include at least one node");
      return issues;
    }
    if (!Array.isArray(data.links) || data.links.length === 0) {
      issues.push("sankey data.links must include at least one link");
      return issues;
    }
    data.nodes.forEach((node, index) => {
      if (!nonEmptyString(node.name)) {
        issues.push(`sankey node ${index} name is required`);
      }
    });
    data.links.forEach((link, index) => {
      if (!Number.isInteger(link.source) || link.source < 0 || link.source >= data.nodes.length) {
        issues.push(`sankey link ${index} source index is invalid`);
      }
      if (!Number.isInteger(link.target) || link.target < 0 || link.target >= data.nodes.length) {
        issues.push(`sankey link ${index} target index is invalid`);
      }
      if (!positiveFiniteNumber(link.value)) {
        issues.push(`sankey link ${index} value must be positive and finite`);
      }
    });
  }

  return issues;
}
