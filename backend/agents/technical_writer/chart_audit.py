"""Deterministic chart audit helpers for report.json artifacts."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import ValidationError

from core.report_schema import ResearchReport

from ..report_artifacts import chart_marker_ids, load_report_json


_AXIS_CHART_TYPES = {"line", "bar", "area", "composed"}
_SEGMENT_CHART_TYPES = {"pie", "radialBar", "funnel"}
_HIERARCHY_CHART_TYPES = {"treemap", "sunburst"}
_SUPPORTED_CHART_TYPES = (
    _AXIS_CHART_TYPES
    | _SEGMENT_CHART_TYPES
    | _HIERARCHY_CHART_TYPES
    | {"scatter", "radar", "sankey"}
)
_ALLOWED_SERIES_TYPES = {"line", "bar", "area"}
_ALLOWED_AXIS_IDS = {"left", "right"}
_CHART_REQUEST_KEYWORDS = (
    "chart",
    "charts",
    "chart pack",
    "chart-pack",
    "dashboard",
    "plot",
    "plots",
    "renderable",
    "visual",
    "visual evidence",
    "visual-evidence",
    "visualize",
    "overlay",
)


def query_requests_charts(query: str) -> bool:
    """Return True when the user query explicitly asks for visual/chart output."""
    lowered = query.lower()
    return any(keyword in lowered for keyword in _CHART_REQUEST_KEYWORDS)


def _is_finite_number(value: object) -> bool:
    if value is None or value == "":
        return False
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return numeric == numeric and numeric not in {float("inf"), float("-inf")}


def _is_nonfinite_number(value: object) -> bool:
    return isinstance(value, float) and not _is_finite_number(value)


def _walk_values(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


def _parse_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed)


def _finite_values(data: list[Any], key: str) -> list[float]:
    values: list[float] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        value = row.get(key)
        if _is_finite_number(value):
            values.append(float(value))
    return values


def _is_positive_finite_number(value: object) -> bool:
    return _is_finite_number(value) and float(value) > 0


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _segment_data_key(chart: dict[str, Any]) -> str:
    key = chart.get("dataKey")
    return key if isinstance(key, str) and key.strip() else "value"


def _segment_name_key(chart: dict[str, Any]) -> str:
    if chart.get("type") != "funnel":
        return "name"
    key = chart.get("nameKey")
    return key if isinstance(key, str) and key.strip() else "name"


def _hierarchy_value_key(value: Any, preferred: Any = None) -> str:
    if preferred in {"size", "value"}:
        return str(preferred)
    stack = list(value) if isinstance(value, list) else [value]
    while stack:
        node = stack.pop(0)
        if not isinstance(node, dict):
            continue
        if node.get("size") is not None:
            return "size"
        if node.get("value") is not None:
            return "value"
        children = node.get("children")
        if isinstance(children, list):
            stack.extend(children)
    return "value"


def _audit_hierarchy_node(
    node: Any,
    path: str,
    value_key: str,
    *,
    require_children: bool = False,
) -> list[str]:
    issues: list[str] = []
    if not isinstance(node, dict):
        return [f"{path} must be an object"]
    if not str(node.get("name") or "").strip():
        issues.append(f"{path} name is required")

    children = node.get("children")
    if children is not None:
        if not isinstance(children, list) or not children:
            issues.append(f"{path} children must include at least one item")
            return issues
        for index, child in enumerate(children):
            issues.extend(_audit_hierarchy_node(child, f"{path}.children[{index}]", value_key))
        return issues

    if require_children:
        issues.append(f"{path} children must include at least one item")
        return issues

    fallback_key = "value" if value_key == "size" else "size"
    value = node.get(value_key)
    if value is None:
        value = node.get(fallback_key)
    if not _is_positive_finite_number(value):
        issues.append(f"{path} {value_key} must be positive and finite")
    return issues


def _axis_timestamp_extent(data: list[Any], x_axis_key: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    timestamps = [
        timestamp
        for row in data
        if isinstance(row, dict)
        for timestamp in [_parse_timestamp(row.get(x_axis_key))]
        if timestamp is not None
    ]
    if not timestamps:
        return None
    return min(timestamps), max(timestamps)


def _reference_area_label(area: dict[str, Any], index: int) -> str:
    label = str(area.get("label") or "").strip()
    return label or f"reference area {index}"


def _audit_axis_references(
    chart: dict[str, Any],
    data: list[Any],
    x_axis_key: str,
) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    extent = _axis_timestamp_extent(data, x_axis_key)
    if extent is None:
        return blockers, warnings

    min_date, max_date = extent
    reference_areas = chart.get("referenceAreas")
    if isinstance(reference_areas, list):
        for index, area in enumerate(reference_areas):
            if not isinstance(area, dict):
                blockers.append(f"referenceAreas[{index}] must be an object")
                continue
            start = _parse_timestamp(area.get("x1") or area.get("start"))
            end = _parse_timestamp(area.get("x2") or area.get("end") or area.get("x1"))
            if start is None or end is None:
                continue
            if end < min_date or start > max_date:
                blockers.append(
                    f"{_reference_area_label(area, index)} is outside plotted x-axis range"
                )
            elif start < min_date or end > max_date:
                warnings.append(
                    f"{_reference_area_label(area, index)} extends beyond plotted x-axis range"
                )

    reference_lines = chart.get("referenceLines")
    if isinstance(reference_lines, list):
        for index, line in enumerate(reference_lines):
            if not isinstance(line, dict):
                blockers.append(f"referenceLines[{index}] must be an object")
                continue
            axis = line.get("axis")
            value = line.get("value")
            if value is None and line.get("x") is not None:
                axis = "x"
                value = line.get("x")
            if axis == "x":
                timestamp = _parse_timestamp(value)
                if timestamp is not None and (timestamp < min_date or timestamp > max_date):
                    label = str(line.get("label") or "").strip() or f"reference line {index}"
                    warnings.append(f"{label} is outside plotted x-axis range")

    return blockers, warnings


def chart_render_dict(report: ResearchReport) -> dict:
    """Validate the deterministic subset of the frontend Recharts render contract."""

    issues: dict[str, list[str]] = {}
    for chart_id, chart_model in report.charts.items():
        chart = chart_model.model_dump()
        chart_issues: list[str] = []
        if chart.get("id") != chart_id:
            chart_issues.append(f"chart id mismatch: expected {chart_id}, got {chart.get('id')}")
        if not str(chart.get("title") or "").strip():
            chart_issues.append("chart title is required")
        if any(_is_nonfinite_number(value) for value in _walk_values(chart)):
            chart_issues.append("chart contains non-finite numeric values")

        chart_type = chart.get("type")
        if chart_type in _AXIS_CHART_TYPES:
            data = chart.get("data")
            if not isinstance(data, list) or not data:
                chart_issues.append("chart data must include at least one row")
                issues[chart_id] = chart_issues
                continue
            layout = chart.get("layout")
            if layout is not None and layout not in {"horizontal", "vertical"}:
                chart_issues.append(f"axis chart layout {layout} is unsupported")
            x_axis_key = chart.get("xAxisKey")
            series = chart.get("series")
            if not isinstance(x_axis_key, str) or not x_axis_key.strip():
                chart_issues.append("axis chart xAxisKey is required")
            elif any(
                not isinstance(row, dict) or row.get(x_axis_key) in {None, ""}
                for row in data
            ):
                chart_issues.append(f"one or more rows are missing xAxisKey {x_axis_key}")
            if not isinstance(series, list) or not series:
                chart_issues.append("axis chart series must include at least one item")
            else:
                for item in series:
                    data_key = item.get("dataKey") if isinstance(item, dict) else None
                    if not isinstance(data_key, str) or not data_key.strip():
                        chart_issues.append("series dataKey is required")
                        continue
                    if not any(
                        isinstance(row, dict) and _is_finite_number(row.get(data_key))
                        for row in data
                    ):
                        chart_issues.append(f"series {data_key} has no finite numeric values")
                    y_axis_id = item.get("yAxisId")
                    if y_axis_id is not None and y_axis_id not in _ALLOWED_AXIS_IDS:
                        chart_issues.append(
                            f"series {data_key} has unsupported yAxisId {y_axis_id}"
                        )
                    series_type = item.get("type")
                    if (
                        chart_type == "composed"
                        and series_type is not None
                        and series_type not in _ALLOWED_SERIES_TYPES
                    ):
                        chart_issues.append(
                            f"series {data_key} has unsupported composed type {series_type}"
                        )
                    stack_id = item.get("stackId")
                    if stack_id is not None and not str(stack_id).strip():
                        chart_issues.append(
                            f"series {data_key} stackId must be non-empty when provided"
                        )
            if chart_issues:
                issues[chart_id] = chart_issues
            continue

        if chart_type == "scatter":
            data = chart.get("data")
            if not isinstance(data, list) or not data:
                chart_issues.append("chart data must include at least one row")
                issues[chart_id] = chart_issues
                continue
            for key_name in ("xKey", "yKey"):
                key = chart.get(key_name)
                if not isinstance(key, str) or not key.strip():
                    chart_issues.append(f"scatter chart {key_name} is required")
                    continue
                if not any(
                    isinstance(row, dict) and _is_finite_number(row.get(key))
                    for row in data
                ):
                    chart_issues.append(f"scatter key {key} has no finite numeric values")
            size_key = chart.get("sizeKey")
            if size_key is not None:
                if not isinstance(size_key, str) or not size_key.strip():
                    chart_issues.append("scatter chart sizeKey must be non-empty when provided")
                elif not any(
                    isinstance(row, dict) and _is_positive_finite_number(row.get(size_key))
                    for row in data
                ):
                    chart_issues.append(
                        f"scatter sizeKey {size_key} has no positive finite values"
                    )

        if chart_type == "radar":
            data = chart.get("data")
            if not isinstance(data, list) or not data:
                chart_issues.append("chart data must include at least one row")
                issues[chart_id] = chart_issues
                continue
            angle_key = chart.get("angleKey")
            series = chart.get("series")
            if not isinstance(angle_key, str) or not angle_key.strip():
                chart_issues.append("radar chart angleKey is required")
            elif any(
                not isinstance(row, dict) or row.get(angle_key) in {None, ""}
                for row in data
            ):
                chart_issues.append(f"one or more radar rows are missing angleKey {angle_key}")
            if not isinstance(series, list) or not series:
                chart_issues.append("radar chart series must include at least one item")
            else:
                positive_series = 0
                for item in series:
                    data_key = item.get("dataKey") if isinstance(item, dict) else None
                    if not isinstance(data_key, str) or not data_key.strip():
                        chart_issues.append("series dataKey is required")
                        continue
                    if not any(
                        isinstance(row, dict) and _is_finite_number(row.get(data_key))
                        for row in data
                    ):
                        chart_issues.append(f"series {data_key} has no finite numeric values")
                    if any(
                        isinstance(row, dict) and _is_positive_finite_number(row.get(data_key))
                        for row in data
                    ):
                        positive_series += 1
                    if not str(item.get("label") or "").strip():
                        chart_issues.append(f"series {data_key} label is required")
                    if not str(item.get("color") or "").strip():
                        chart_issues.append(f"series {data_key} color is required")
                if positive_series == 0:
                    chart_issues.append(
                        "radar chart has no positive finite values and may render invisible"
                    )

        if chart_type in _SEGMENT_CHART_TYPES:
            data = chart.get("data")
            if not isinstance(data, list) or not data:
                chart_issues.append("chart data must include at least one row")
                issues[chart_id] = chart_issues
                continue
            data_key = _segment_data_key(chart)
            name_key = _segment_name_key(chart)
            for index, row in enumerate(data):
                if not isinstance(row, dict):
                    chart_issues.append(f"{chart_type} item {index} must be an object")
                    continue
                if not str(row.get(name_key) or "").strip():
                    chart_issues.append(f"{chart_type} item {index} {name_key} is required")
                if not _is_positive_finite_number(row.get(data_key)):
                    chart_issues.append(
                        f"{chart_type} item {index} {data_key} must be positive and finite"
                    )

        if chart_type == "treemap":
            data = chart.get("data")
            if not isinstance(data, list) or not data:
                chart_issues.append("chart data must include at least one row")
                issues[chart_id] = chart_issues
                continue
            value_key = _hierarchy_value_key(data, chart.get("valueKey"))
            for index, node in enumerate(data):
                chart_issues.extend(
                    _audit_hierarchy_node(node, f"treemap node {index}", value_key)
                )

        if chart_type == "sunburst":
            data = chart.get("data")
            value_key = _hierarchy_value_key(data, chart.get("valueKey"))
            chart_issues.extend(
                _audit_hierarchy_node(
                    data,
                    "sunburst root",
                    value_key,
                    require_children=True,
                )
            )

        if chart_type == "sankey":
            data = chart.get("data")
            if not isinstance(data, dict):
                chart_issues.append("sankey data must be an object")
            else:
                nodes = data.get("nodes")
                links = data.get("links")
                if not isinstance(nodes, list) or not nodes:
                    chart_issues.append("sankey data.nodes must include at least one node")
                    nodes = []
                if not isinstance(links, list) or not links:
                    chart_issues.append("sankey data.links must include at least one link")
                    links = []
                for index, node in enumerate(nodes):
                    if not isinstance(node, dict) or not str(node.get("name") or "").strip():
                        chart_issues.append(f"sankey node {index} name is required")
                for index, link in enumerate(links):
                    if not isinstance(link, dict):
                        chart_issues.append(f"sankey link {index} must be an object")
                        continue
                    source = link.get("source")
                    target = link.get("target")
                    if not isinstance(source, int) or source < 0 or source >= len(nodes):
                        chart_issues.append(f"sankey link {index} source index is invalid")
                    if not isinstance(target, int) or target < 0 or target >= len(nodes):
                        chart_issues.append(f"sankey link {index} target index is invalid")
                    if not _is_positive_finite_number(link.get("value")):
                        chart_issues.append(
                            f"sankey link {index} value must be positive and finite"
                        )

        if chart_issues:
            issues[chart_id] = chart_issues

    return {
        "valid": not issues,
        "issues": issues,
        "checked_charts": list(report.charts.keys()),
    }


def chart_semantics_dict(report: ResearchReport) -> dict:
    """Audit chart data semantics beyond schema validity."""

    blockers: dict[str, list[str]] = {}
    warnings: dict[str, list[str]] = {}

    for chart_id, chart_model in report.charts.items():
        chart = chart_model.model_dump()
        chart_blockers: list[str] = []
        chart_warnings: list[str] = []
        chart_type = chart.get("type")
        data = chart.get("data")

        if chart_type not in _SUPPORTED_CHART_TYPES:
            chart_blockers.append(f"unsupported chart type {chart_type}")

        if chart_type in _AXIS_CHART_TYPES and isinstance(data, list):
            x_axis_key = chart.get("xAxisKey")
            series = chart.get("series")
            if isinstance(x_axis_key, str) and x_axis_key and isinstance(series, list):
                seen_x_values: set[str] = set()
                duplicate_x_values = 0
                all_series_keys = [
                    item.get("dataKey")
                    for item in series
                    if isinstance(item, dict) and isinstance(item.get("dataKey"), str)
                ]
                finite_row_indexes: list[int] = []
                empty_rows = 0
                for index, row in enumerate(data):
                    if not isinstance(row, dict):
                        chart_blockers.append(f"row {index} must be an object")
                        continue
                    x_value = str(row.get(x_axis_key) or "").strip()
                    if x_value:
                        if x_value in seen_x_values:
                            duplicate_x_values += 1
                        seen_x_values.add(x_value)
                    row_has_finite_series = any(
                        _is_finite_number(row.get(key)) for key in all_series_keys
                    )
                    if row_has_finite_series:
                        finite_row_indexes.append(index)
                    else:
                        empty_rows += 1

                if duplicate_x_values:
                    chart_blockers.append(
                        f"{duplicate_x_values} duplicate x-axis rows may render ambiguously"
                    )
                if finite_row_indexes:
                    stale_tail_rows = len(data) - 1 - max(finite_row_indexes)
                    if stale_tail_rows > 0:
                        chart_blockers.append(
                            f"{stale_tail_rows} stale tail rows contain no finite series values"
                        )
                    if empty_rows and empty_rows / len(data) >= 0.25:
                        chart_warnings.append(
                            f"{empty_rows} rows contain no finite series values"
                        )

                ranges = [
                    (key, max(values) - min(values))
                    for key in all_series_keys
                    for values in [_finite_values(data, key)]
                    if len(values) >= 2
                ]
                positive_ranges = [item for item in ranges if item[1] > 0]
                explicit_axis_ids = [
                    item.get("yAxisId")
                    for item in series
                    if isinstance(item, dict) and item.get("yAxisId") in _ALLOWED_AXIS_IDS
                ]
                if "right" in explicit_axis_ids and "left" not in explicit_axis_ids:
                    chart_warnings.append("dual-axis chart assigns series to right axis only")
                if len(set(explicit_axis_ids)) >= 2 and len(positive_ranges) >= 2:
                    min_range = min(value for _, value in positive_ranges)
                    max_range = max(value for _, value in positive_ranges)
                    if min_range > 0 and max_range / min_range < 2:
                        chart_warnings.append(
                            "dual-axis chart uses separate axes for similarly scaled series"
                        )
                elif not explicit_axis_ids and len(positive_ranges) >= 2:
                    min_range = min(value for _, value in positive_ranges)
                    max_range = max(value for _, value in positive_ranges)
                    if min_range > 0 and max_range / min_range >= 100:
                        chart_warnings.append(
                            "series ranges differ materially; verify axis assignment"
                        )

                ref_blockers, ref_warnings = _audit_axis_references(chart, data, x_axis_key)
                chart_blockers.extend(ref_blockers)
                chart_warnings.extend(ref_warnings)

        if chart_type == "pie" and isinstance(data, list):
            non_positive = [
                index
                for index, row in enumerate(data)
                if isinstance(row, dict)
                and _is_finite_number(row.get("value"))
                and float(row["value"]) <= 0
            ]
            if non_positive:
                chart_warnings.append(f"pie slices at indexes {non_positive} are non-positive")

        if chart_blockers:
            blockers[chart_id] = chart_blockers
        if chart_warnings:
            warnings[chart_id] = chart_warnings

    return {
        "valid": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "checked_charts": list(report.charts.keys()),
    }


def chart_marker_dict(report: ResearchReport) -> dict:
    marker_ids = chart_marker_ids(report.markdown)
    defined = list(report.charts.keys())
    broken = [mid for mid in marker_ids if mid not in report.charts]
    unreferenced = [chart_id for chart_id in defined if chart_id not in marker_ids]
    seen: set[str] = set()
    duplicate_markers = []
    for marker_id in marker_ids:
        if marker_id in seen and marker_id not in duplicate_markers:
            duplicate_markers.append(marker_id)
        seen.add(marker_id)
    metadata_chart_count = report.metadata.chart_count
    return {
        "valid": len(broken) == 0 and len(unreferenced) == 0 and len(duplicate_markers) == 0,
        "broken_references": broken,
        "unreferenced_charts": unreferenced,
        "duplicate_markers": duplicate_markers,
        "chart_count": len(marker_ids),
        "metadata_chart_count": metadata_chart_count,
        "chart_count_mismatch": metadata_chart_count != len(marker_ids),
        "defined_charts": defined,
    }


def _audit_payload(
    *,
    passes_audit: bool,
    report_path: str,
    chart_markers: dict,
    chart_render: dict,
    chart_semantics: dict,
    blockers: list[str],
    warnings: list[str],
    load_error: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "passes_audit": passes_audit,
        "report_path": report_path,
        "chart_count": len(chart_markers.get("defined_charts", [])),
        "chart_markers": chart_markers,
        "chart_render": chart_render,
        "chart_semantics": chart_semantics,
        "warnings": warnings,
        "blockers": blockers,
    }
    if load_error is not None:
        payload["load_error"] = load_error
    return json.dumps(payload)


def run_report_chart_audit(report_json_path: str) -> str:
    """Run the chart-focused artifact audit used by improver chart mode."""

    path = Path(report_json_path)
    data, load_err = load_report_json(report_json_path)
    if load_err or data is None:
        return _audit_payload(
            passes_audit=False,
            report_path=str(path),
            chart_markers={},
            chart_render={},
            chart_semantics={},
            warnings=[],
            blockers=[load_err or "Unknown load error"],
            load_error=load_err,
        )

    try:
        report = ResearchReport(**data)
    except ValidationError as exc:
        return _audit_payload(
            passes_audit=False,
            report_path=str(path),
            chart_markers={},
            chart_render={},
            chart_semantics={},
            warnings=[],
            blockers=[f"Schema validation failed: {exc}"],
        )

    markers = chart_marker_dict(report)
    render = chart_render_dict(report)
    semantics = chart_semantics_dict(report)
    blockers: list[str] = []
    warnings: list[str] = []

    if not markers["valid"]:
        if markers["broken_references"]:
            blockers.append(f"broken chart references: {markers['broken_references']}")
        if markers["unreferenced_charts"]:
            blockers.append(
                "charts defined in report.json but not referenced in markdown: "
                f"{markers['unreferenced_charts']}"
            )
        if markers.get("duplicate_markers"):
            blockers.append(f"duplicate chart markers: {markers['duplicate_markers']}")
    if (
        not markers["defined_charts"]
        and query_requests_charts(report.query)
    ):
        blockers.append("query requested charts but report.json contains zero chart definitions")
    if markers.get("chart_count_mismatch"):
        blockers.append(
            "metadata chart_count does not match markdown chart markers: "
            f"metadata={markers.get('metadata_chart_count')} markers={markers.get('chart_count')}"
        )
    if not render["valid"]:
        blockers.append(f"charts fail frontend Recharts render contract: {render['issues']}")
    if not semantics["valid"]:
        blockers.append(f"charts fail chart data semantics audit: {semantics['blockers']}")
    for chart_id, chart_warnings in semantics["warnings"].items():
        for warning in chart_warnings:
            warnings.append(f"{chart_id}: {warning}")

    return _audit_payload(
        passes_audit=not blockers,
        report_path=str(path.resolve()),
        chart_markers=markers,
        chart_render=render,
        chart_semantics=semantics,
        warnings=warnings,
        blockers=blockers,
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Audit report.json chart artifacts")
    parser.add_argument("report_json_path")
    args = parser.parse_args()

    payload = json.loads(run_report_chart_audit(args.report_json_path))
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("passes_audit") else 1


if __name__ == "__main__":
    raise SystemExit(main())
