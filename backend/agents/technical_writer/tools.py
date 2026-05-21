"""
LangChain tools for the Technical Writer subagent — plan outline, save report.json,
static validation gate.
"""

from __future__ import annotations

import json
import re
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from langchain.tools import ToolRuntime

from core.context import ResearchContext
from core.report_schema import DataSource, ReportMetadata, ResearchReport

from ..artifact_fact_consistency import (
    artifact_fact_consistency_blocker,
    artifact_fact_consistency_dict,
)
from ..requested_coverage import (
    assess_requested_subject_evidence,
    compact_requested_geography_coverage,
    compact_requested_subject_evidence,
    requested_geography_coverage_blocker,
    requested_subject_evidence_report_blocker,
)
from agents.quant_macro_stats.artifacts.numeric_fact_contracts import (
    normalize_numeric_facts,
    numeric_fact_conflicting_current_value_contexts,
    numeric_fact_current_state_duration_misuse,
    numeric_fact_literal_required,
)
from ..report_artifacts import (
    chart_handoff_blocker,
    chart_handoff_dict,
    chart_marker_ids,
    inject_auto_report_footer,
    normalize_query_text,
    original_query_contract_dict,
)

from .report_validation import run_report_static_gate

from .constants import OUTPUT_BASE_DIR

_MACRO_QUERY_KEYWORDS = {
    "macro",
    "fred",
    "gdp",
    "cpi",
    "inflation",
    "unemployment",
    "payroll",
    "labor",
    "interest rate",
    "fed funds",
    "treasury",
    "yield",
    "recession",
    "consumer",
    "sentiment",
    "saving rate",
    "personal consumption",
    "disposable personal income",
    "delinquency",
}

_SUPPORTED_CHART_TYPES = {
    "line",
    "bar",
    "area",
    "composed",
    "scatter",
    "pie",
    "treemap",
    "radar",
    "radialBar",
    "funnel",
    "sankey",
    "sunburst",
}
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_PLAN_CONTEXT_FILENAME = ".technical_writer_plan_context.json"


def _is_macro_report(query_type: str, original_query: str) -> bool:
    """Infer macro report shape when the caller passes a generic query type."""
    macro_types = {"macro_indicator", "trend_analysis", "correlation_analysis"}
    if query_type in macro_types:
        return True

    lowered_query = original_query.lower()
    if any(keyword in lowered_query for keyword in _MACRO_QUERY_KEYWORDS):
        return True

    return False


def _plan_context_path(runtime: ToolRuntime[ResearchContext]) -> Path | None:
    output_dir = getattr(runtime.context, "output_dir", None)
    if not output_dir:
        return None
    return Path(output_dir) / _PLAN_CONTEXT_FILENAME


def _save_plan_context(
    runtime: ToolRuntime[ResearchContext],
    *,
    charts_json_path: str,
    original_query: str,
    helper_evidence: dict[str, Any] | None = None,
) -> None:
    path = _plan_context_path(runtime)
    if path is None:
        return
    payload = {
        "charts_json_path": charts_json_path,
        "original_query": original_query,
    }
    if helper_evidence:
        payload["helper_evidence"] = helper_evidence
    try:
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        return


def _load_plan_context(runtime: ToolRuntime[ResearchContext]) -> dict[str, Any]:
    path = _plan_context_path(runtime)
    if path is None:
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    context: dict[str, Any] = {
        key: normalize_query_text(value) if key == "original_query" else value.strip()
        for key in ("charts_json_path", "original_query")
        if isinstance((value := parsed.get(key)), str) and value.strip()
    }
    value = parsed.get("helper_evidence")
    if isinstance(value, dict) and value:
        context["helper_evidence"] = value
    return context


def _extract_research_query_from_markdown(markdown: str) -> str:
    """Recover the original query from the writer-required Research Query section."""
    lines = markdown.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower() != "## research query":
            continue

        query_lines: list[str] = []
        for next_line in lines[idx + 1 :]:
            next_stripped = next_line.strip()
            if next_stripped.startswith("## "):
                break
            if next_stripped:
                query_lines.append(next_stripped)
        return " ".join(query_lines).strip()
    return ""


def _runtime_original_query(runtime: ToolRuntime[ResearchContext]) -> str:
    return normalize_query_text(getattr(runtime.context, "query", None))


def _original_query_mismatch_response(
    *,
    report_path: str,
    candidate_query: str,
    expected_query: str,
    source: str,
) -> str:
    contract = original_query_contract_dict(candidate_query, expected_query)
    message = (
        "original_query_mismatch: "
        f"{source} does not match runtime.context.query after whitespace normalization."
    )
    return json.dumps(
        {
            "status": "error",
            "error": "original_query_mismatch",
            "failure_category": "original_query_mismatch",
            "required_upstream": "technical-writer",
            "report_path": report_path,
            "original_query_contract": contract,
            "blockers": [message],
            "message": message,
        }
    )


def _labelize_key(key: str) -> str:
    """Turn a data key like `gdp_growth_pct` into a readable label."""
    return key.replace("_", " ").strip().title()


def _infer_chart_description(chart_copy: dict, chart_id: str) -> str:
    title = chart_copy.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return f"Chart for {chart_id.replace('_', ' ')}."


def _infer_chart_title(chart_copy: dict, chart_id: str) -> str:
    """Return a usable chart title for schema validation and display."""
    title = chart_copy.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()

    layout = chart_copy.get("layout")
    if isinstance(layout, dict):
        layout_title = layout.get("title")
        if isinstance(layout_title, str) and layout_title.strip():
            return layout_title.strip()

    return _labelize_key(chart_id)


def _recharts_children(chart_copy: dict) -> list[dict]:
    children = chart_copy.get("children")
    if not isinstance(children, list):
        return []
    return [child for child in children if isinstance(child, dict)]


def _axis_key_from_recharts_children(children: list[dict]) -> str | None:
    for child in children:
        child_type = str(child.get("type", "")).lower()
        props = child.get("props") if isinstance(child.get("props"), dict) else {}
        data_key = props.get("dataKey")
        if child_type == "xaxis" and isinstance(data_key, str) and data_key:
            return data_key
    return None


def _series_from_recharts_children(children: list[dict]) -> list[dict]:
    canonical_series: list[dict] = []
    series_types = {"line", "bar", "area"}
    for child in children:
        child_type = str(child.get("type", "")).lower()
        if child_type not in series_types:
            continue
        props = child.get("props") if isinstance(child.get("props"), dict) else {}
        data_key = props.get("dataKey")
        if not isinstance(data_key, str) or not data_key:
            continue
        label = props.get("title") or props.get("name") or props.get("label") or _labelize_key(data_key)
        color = props.get("stroke") or props.get("fill") or props.get("color") or "#3b82f6"
        canonical_series.append(
            {
                "dataKey": data_key,
                "label": label,
                "color": color,
                "type": child_type,
            }
        )
    return canonical_series


def _series_from_y_keys(y_keys: list, colors: list | None = None, names: list | None = None) -> list[dict]:
    """Normalize legacy yKeys arrays into report chart series entries."""
    colors = colors or []
    names = names or []
    series: list[dict] = []
    for idx, item in enumerate(y_keys):
        if isinstance(item, str):
            data_key = item
            if not data_key:
                continue
            series.append(
                {
                    "dataKey": data_key,
                    "label": names[idx] if idx < len(names) else _labelize_key(data_key),
                    "color": colors[idx] if idx < len(colors) else "#3b82f6",
                }
            )
            continue

        if not isinstance(item, dict):
            continue
        data_key = item.get("dataKey") or item.get("key")
        if not isinstance(data_key, str) or not data_key:
            continue
        series_item = {
            "dataKey": data_key,
            "label": item.get("label") or item.get("name") or _labelize_key(data_key),
            "color": item.get("color", "#3b82f6"),
        }
        if item.get("axis") in {"left", "right"}:
            series_item["yAxisId"] = item["axis"]
        series.append(series_item)
    return series


def _series_from_keyed_config(series_config: dict) -> list[dict]:
    """Normalize `{data_key: {label, color, ...}}` chart configs from quant scripts."""
    series: list[dict] = []
    for data_key, config in series_config.items():
        if not isinstance(data_key, str) or not data_key:
            continue
        if isinstance(config, dict):
            series_item = {
                "dataKey": config.get("dataKey") or config.get("key") or data_key,
                "label": config.get("label") or config.get("name") or _labelize_key(data_key),
                "color": config.get("color") or "#3b82f6",
            }
            if config.get("type"):
                series_item["type"] = config["type"]
            if config.get("yAxisId") in {"left", "right"}:
                series_item["yAxisId"] = config["yAxisId"]
            elif config.get("axis") in {"left", "right"}:
                series_item["yAxisId"] = config["axis"]
        else:
            series_item = {
                "dataKey": data_key,
                "label": _labelize_key(data_key),
                "color": "#3b82f6",
            }
        if isinstance(series_item["dataKey"], str) and series_item["dataKey"]:
            series.append(series_item)
    return series


def _series_from_config_y_axis(config: dict) -> list[dict]:
    """Normalize legacy `config.yAxis` lists into canonical series entries."""
    y_axis = config.get("yAxis") or config.get("y_axis")
    if not isinstance(y_axis, list):
        return []
    colors = config.get("colors") if isinstance(config.get("colors"), list) else []
    series: list[dict] = []
    for idx, item in enumerate(y_axis):
        if not isinstance(item, dict):
            continue
        data_key = item.get("dataKey") or item.get("key")
        if not isinstance(data_key, str) or not data_key:
            continue
        series_item = {
            "dataKey": data_key,
            "label": item.get("label") or item.get("name") or _labelize_key(data_key),
            "color": item.get("color") or (colors[idx] if idx < len(colors) else "#3b82f6"),
        }
        y_axis_id = item.get("yAxisId") or item.get("axis")
        if y_axis_id in {"left", "right"}:
            series_item["yAxisId"] = y_axis_id
        elif len(y_axis) > 1:
            series_item["yAxisId"] = "left" if idx == 0 else "right"
        if item.get("type") in {"line", "bar", "area"}:
            series_item["type"] = item["type"]
        series.append(series_item)
    return series


def _normalize_reference_line(line: Any) -> Any:
    """Normalize legacy Recharts x/y reference lines to the frontend contract."""
    if not isinstance(line, dict):
        return line

    normalized = dict(line)
    axis = normalized.get("axis")
    value = normalized.get("value")
    if axis not in {"x", "y"}:
        if normalized.get("x") is not None:
            axis = "x"
            value = normalized.get("x")
        elif normalized.get("y") is not None:
            axis = "y"
            value = normalized.get("y")
    elif value is None and normalized.get(axis) is not None:
        value = normalized.get(axis)

    if axis in {"x", "y"}:
        normalized["axis"] = axis
    if value is not None:
        normalized["value"] = value
    if "dashed" not in normalized and normalized.get("strokeDasharray"):
        normalized["dashed"] = True

    normalized.pop("x", None)
    normalized.pop("y", None)
    normalized.pop("strokeDasharray", None)
    return normalized


def _normalize_reference_lines(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    return [_normalize_reference_line(item) for item in value]


def _coerce_radar_to_bar(chart_copy: dict) -> dict:
    """Represent unsupported radar charts as canonical grouped bar charts."""
    data = chart_copy.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return chart_copy

    sample = data[0]
    x_axis_key = (
        "period"
        if "period" in sample
        else next((key for key, value in sample.items() if isinstance(value, str)), None)
    )
    if not x_axis_key:
        x_axis_key = next(iter(sample.keys()))

    colors = ["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"]
    numeric_keys = [
        key
        for key, value in sample.items()
        if key != x_axis_key and isinstance(value, (int, float)) and not isinstance(value, bool)
    ]

    chart_copy["type"] = "bar"
    chart_copy["chart_type"] = "bar"
    chart_copy["xAxisKey"] = chart_copy.get("xAxisKey") or x_axis_key
    chart_copy["series"] = chart_copy.get("series") or [
        {
            "dataKey": key,
            "label": _labelize_key(key),
            "color": colors[idx % len(colors)],
        }
        for idx, key in enumerate(numeric_keys)
    ]
    if isinstance(chart_copy.get("description"), str):
        chart_copy["description"] = chart_copy["description"].replace("Radar chart", "Bar chart")
    return chart_copy


def _infer_category_key_from_rows(data: Any, preferred: tuple[str, ...]) -> str | None:
    if not isinstance(data, list):
        return None
    first_row = next((row for row in data if isinstance(row, dict)), None)
    if not isinstance(first_row, dict):
        return None
    for key in preferred:
        if key in first_row:
            return key
    return next(
        (
            key
            for key, value in first_row.items()
            if isinstance(value, str) or key.lower() in {"date", "period", "name", "label"}
        ),
        next(iter(first_row.keys()), None),
    )


def _infer_numeric_series_from_rows(data: Any, category_key: str | None) -> list[dict]:
    if not isinstance(data, list):
        return []
    first_row = next((row for row in data if isinstance(row, dict)), None)
    if not isinstance(first_row, dict):
        return []
    colors = ["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"]
    series: list[dict] = []
    for key, value in first_row.items():
        if key == category_key or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        series.append(
            {
                "dataKey": key,
                "label": _labelize_key(key),
                "color": colors[len(series) % len(colors)],
            }
        )
    return series


def _normalize_radar_chart_schema(chart_copy: dict) -> None:
    if not isinstance(chart_copy.get("angleKey"), str):
        angle_key = (
            chart_copy.get("categoryKey")
            or chart_copy.get("subjectKey")
            or chart_copy.get("nameKey")
            or _infer_category_key_from_rows(
                chart_copy.get("data"),
                ("subject", "metric", "dimension", "name", "label", "period"),
            )
        )
        if isinstance(angle_key, str) and angle_key:
            chart_copy["angleKey"] = angle_key
    if "series" not in chart_copy:
        chart_copy["series"] = _infer_numeric_series_from_rows(
            chart_copy.get("data"),
            chart_copy.get("angleKey"),
        )


def _normalize_segment_chart_values(chart_copy: dict) -> None:
    data = chart_copy.get("data")
    if not isinstance(data, list):
        return
    normalized_rows = []
    for row in data:
        if not isinstance(row, dict):
            normalized_rows.append(row)
            continue
        row_copy = dict(row)
        if "value" not in row_copy and "size" in row_copy:
            row_copy["value"] = row_copy["size"]
        if "name" not in row_copy:
            for alias in ("label", "stage", "category", "metric"):
                if isinstance(row_copy.get(alias), str) and row_copy[alias].strip():
                    row_copy["name"] = row_copy[alias]
                    break
        normalized_rows.append(row_copy)
    chart_copy["data"] = normalized_rows


def _flatten_panel_axis_data(chart_copy: dict) -> None:
    """Merge multi-panel axis chart data into the canonical row-list shape."""
    panel_data = chart_copy.get("data")
    if not isinstance(panel_data, dict):
        return

    x_axis_key = chart_copy.get("xAxisKey")
    if not isinstance(x_axis_key, str) or not x_axis_key:
        x_axis_key = "date"

    rows_by_x: dict[str, dict] = {}
    inferred_series: list[dict] = []
    seen_series_keys: set[str] = set()

    for panel in panel_data.values():
        if not isinstance(panel, dict):
            continue

        for item in panel.get("series", []):
            if not isinstance(item, dict):
                continue
            data_key = item.get("dataKey") or item.get("key")
            if not isinstance(data_key, str) or not data_key or data_key in seen_series_keys:
                continue
            seen_series_keys.add(data_key)
            canonical_item = dict(item)
            canonical_item["dataKey"] = data_key
            canonical_item["label"] = (
                item.get("label") or item.get("name") or _labelize_key(data_key)
            )
            canonical_item["color"] = item.get("color") or "#3b82f6"
            inferred_series.append(canonical_item)

        rows = panel.get("data")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            x_value = row.get(x_axis_key)
            if x_value is None:
                continue
            row_key = str(x_value)
            merged_row = rows_by_x.setdefault(row_key, {x_axis_key: x_value})
            merged_row.update(row)

    chart_copy["data"] = [
        rows_by_x[key]
        for key in sorted(rows_by_x)
    ]
    if "series" not in chart_copy and inferred_series:
        chart_copy["series"] = inferred_series


def _normalize_chart_definitions(charts_on_disk: dict) -> dict:
    """Coerce legacy chart shapes into the ResearchReport schema."""
    normalized: dict = {}
    chart_type_aliases = {
        "composite": "composed",
        "combo": "composed",
        "dualaxis": "composed",
        "dual_axis": "composed",
        "dualaxislinebar": "composed",
        "dual_axis_line_bar": "composed",
        "duallaxischart": "composed",
        "linechart": "line",
        "multiline": "line",
        "linewithzones": "line",
        "barchart": "bar",
        "areachart": "area",
        "composedchart": "composed",
        "compositechart": "composed",
        "scatterchart": "scatter",
        "piechart": "pie",
        "treemapchart": "treemap",
        "radarchart": "radar",
        "radialbar": "radialBar",
        "radialbarchart": "radialBar",
        "funnelchart": "funnel",
        "sankeychart": "sankey",
        "sunburstchart": "sunburst",
    }

    for chart_id, chart_def in charts_on_disk.items():
        if not isinstance(chart_def, dict):
            normalized[chart_id] = chart_def
            continue

        chart_copy = dict(chart_def)
        chart_copy.setdefault("id", chart_id)
        layout = chart_copy.get("layout") if isinstance(chart_copy.get("layout"), dict) else {}
        for top_level_key in (
            "title",
            "description",
            "xAxisKey",
            "series",
            "referenceLines",
            "referenceAreas",
        ):
            if top_level_key not in chart_copy and top_level_key in layout:
                chart_copy[top_level_key] = layout[top_level_key]
        if "referenceAreas" not in chart_copy and isinstance(chart_copy.get("reference_areas"), list):
            chart_copy["referenceAreas"] = chart_copy["reference_areas"]
        if "referenceLines" not in chart_copy and isinstance(chart_copy.get("reference_lines"), list):
            chart_copy["referenceLines"] = chart_copy["reference_lines"]
        if "referenceLines" in chart_copy:
            chart_copy["referenceLines"] = _normalize_reference_lines(
                chart_copy["referenceLines"]
            )
        chart_copy.setdefault("description", _infer_chart_description(chart_copy, chart_id))
        if isinstance(chart_copy.get("layout"), dict):
            layout_value = layout.get("layout") or layout.get("chartLayout") or layout.get("orientation")
            if layout_value in {"horizontal", "vertical"}:
                chart_copy["layout"] = layout_value
            else:
                chart_copy.pop("layout", None)

        if "type" not in chart_copy and isinstance(chart_copy.get("chart_type"), str):
            chart_copy["type"] = chart_copy["chart_type"]
        if "type" not in chart_copy and isinstance(chart_copy.get("chartType"), str):
            chart_copy["type"] = chart_copy["chartType"]
        if isinstance(chart_copy.get("type"), str):
            normalized_type = re.sub(r"[\s_-]+", "", chart_copy["type"]).lower()
            chart_copy["type"] = chart_type_aliases.get(normalized_type, normalized_type)
        chart_copy.setdefault("title", _infer_chart_title(chart_copy, chart_id))

        config = chart_copy.get("config") if isinstance(chart_copy.get("config"), dict) else {}
        recharts_children = _recharts_children(chart_copy)

        if chart_copy.get("type") not in _SUPPORTED_CHART_TYPES:
            continue

        if chart_copy.get("type") == "radar":
            _normalize_radar_chart_schema(chart_copy)

        if chart_copy.get("type") in {"line", "bar", "area", "composed"}:
            _flatten_panel_axis_data(chart_copy)

            if "xAxisKey" not in chart_copy:
                child_x_axis_key = _axis_key_from_recharts_children(recharts_children)
                if child_x_axis_key:
                    chart_copy["xAxisKey"] = child_x_axis_key
            if "xAxisKey" not in chart_copy and isinstance(config.get("xKey"), str):
                chart_copy["xAxisKey"] = config["xKey"]
            if "xAxisKey" not in chart_copy and isinstance(config.get("xAxis"), dict):
                x_axis_data_key = config["xAxis"].get("dataKey")
                if isinstance(x_axis_data_key, str) and x_axis_data_key:
                    chart_copy["xAxisKey"] = x_axis_data_key
            if "xAxisKey" not in chart_copy and isinstance(chart_copy.get("xKey"), str):
                chart_copy["xAxisKey"] = chart_copy["xKey"]
            if "xAxisKey" not in chart_copy and isinstance(chart_copy.get("x_key"), str):
                chart_copy["xAxisKey"] = chart_copy["x_key"]
            if "xAxisKey" not in chart_copy and isinstance(chart_copy.get("x_axis"), dict):
                x_axis_data_key = chart_copy["x_axis"].get("data_key")
                if isinstance(x_axis_data_key, str) and x_axis_data_key:
                    chart_copy["xAxisKey"] = x_axis_data_key
            if "xAxisKey" not in chart_copy and isinstance(chart_copy.get("data"), list):
                first_row = next(
                    (row for row in chart_copy["data"] if isinstance(row, dict)),
                    {},
                )
                chart_copy["xAxisKey"] = next(
                    (
                        key
                        for key, value in first_row.items()
                        if isinstance(value, str) or key.lower() in {"date", "period"}
                    ),
                    next(iter(first_row.keys()), "date"),
                )

            if "series" not in chart_copy:
                child_series = _series_from_recharts_children(recharts_children)
                if child_series:
                    chart_copy["series"] = child_series
                config_series = config.get("series")
                if "series" not in chart_copy and isinstance(config_series, list) and config_series:
                    chart_copy["series"] = [
                        {
                            "dataKey": item.get("dataKey") or item.get("key", ""),
                            "label": item.get("label")
                            or item.get("name")
                            or _labelize_key(item.get("dataKey") or item.get("key", "")),
                            "color": item.get("color", "#3b82f6"),
                        }
                        for item in config_series
                        if isinstance(item, dict) and (item.get("dataKey") or item.get("key"))
                    ]
                config_y_axis_series = _series_from_config_y_axis(config)
                if "series" not in chart_copy and config_y_axis_series:
                    chart_copy["series"] = config_y_axis_series
                series_config = chart_copy.get("series_config")
                if "series" not in chart_copy and isinstance(series_config, list):
                    chart_copy["series"] = [
                        {
                            "dataKey": item.get("dataKey") or item.get("key", ""),
                            "label": item.get("label")
                            or item.get("name")
                            or _labelize_key(item.get("dataKey") or item.get("key", "")),
                            "color": item.get("color", "#3b82f6"),
                        }
                        for item in series_config
                        if isinstance(item, dict) and (item.get("dataKey") or item.get("key"))
                    ]
                if "series" not in chart_copy and isinstance(series_config, dict):
                    flattened_series_config = []
                    for axis_name, axis_items in series_config.items():
                        if not isinstance(axis_items, list):
                            continue
                        for item in axis_items:
                            if not isinstance(item, dict):
                                continue
                            data_key = item.get("dataKey") or item.get("key")
                            if not data_key:
                                continue
                            series_item = {
                                "dataKey": data_key,
                                "label": item.get("label")
                                or item.get("name")
                                or _labelize_key(data_key),
                                "color": item.get("color", "#3b82f6"),
                            }
                            if axis_name in {"left_axis", "right_axis"}:
                                series_item["yAxisId"] = "left" if axis_name == "left_axis" else "right"
                            flattened_series_config.append(series_item)
                    if flattened_series_config:
                        chart_copy["series"] = flattened_series_config
                    else:
                        keyed_series = _series_from_keyed_config(series_config)
                        if keyed_series:
                            chart_copy["series"] = keyed_series
                elif "series" not in chart_copy and isinstance(config.get("yKeys"), list):
                    chart_copy["series"] = _series_from_y_keys(
                        config.get("yKeys", []),
                        config.get("colors", []),
                        config.get("names", []),
                    )
                elif "series" not in chart_copy and isinstance(chart_copy.get("yKeys"), list):
                    chart_copy["series"] = _series_from_y_keys(chart_copy.get("yKeys", []))
                elif "series" not in chart_copy and isinstance(chart_copy.get("y_keys"), list):
                    chart_copy["series"] = _series_from_y_keys(chart_copy.get("y_keys", []))
                elif "series" not in chart_copy and isinstance(chart_copy.get("data"), list):
                    first_row = next(
                        (row for row in chart_copy["data"] if isinstance(row, dict)),
                        {},
                    )
                    x_axis_key = chart_copy.get("xAxisKey")
                    numeric_keys = [
                        key
                        for key, value in first_row.items()
                        if key != x_axis_key
                        and isinstance(value, (int, float))
                        and not isinstance(value, bool)
                    ]
                    colors = ["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"]
                    chart_copy["series"] = [
                        {
                            "dataKey": key,
                            "label": _labelize_key(key),
                            "color": colors[idx % len(colors)],
                        }
                        for idx, key in enumerate(numeric_keys)
                    ]
            elif isinstance(chart_copy.get("series"), list):
                canonical_series = []
                for item in chart_copy["series"]:
                    if not isinstance(item, dict):
                        continue
                    data_key = item.get("dataKey") or item.get("key")
                    if not isinstance(data_key, str) or not data_key:
                        continue
                    canonical_item = dict(item)
                    canonical_item["dataKey"] = data_key
                    canonical_item["label"] = (
                        item.get("label") or item.get("name") or _labelize_key(data_key)
                    )
                    canonical_item["color"] = item.get("color") or "#3b82f6"
                    canonical_series.append(canonical_item)
                chart_copy["series"] = canonical_series

        if chart_copy.get("type") == "scatter" and "xKey" not in chart_copy:
            config_series = config.get("series") if isinstance(config.get("series"), list) else []
            first_config_series = (
                config_series[0] if config_series and isinstance(config_series[0], dict) else {}
            )
            x_key = config.get("xKey") or chart_copy.get("xAxisKey", "x")
            y_key = (
                first_config_series.get("key")
                or first_config_series.get("dataKey")
                or chart_copy.get("yKey")
                or "y"
            )
            chart_copy["xKey"] = x_key
            chart_copy["yKey"] = y_key
            chart_copy["xLabel"] = chart_copy.get("xLabel") or _labelize_key(x_key)
            chart_copy["yLabel"] = (
                chart_copy.get("yLabel") or first_config_series.get("name") or _labelize_key(y_key)
            )
            chart_copy["color"] = (
                chart_copy.get("color") or first_config_series.get("color") or "#3b82f6"
            )

        if chart_copy.get("type") in {"pie", "radialBar", "funnel"}:
            _normalize_segment_chart_values(chart_copy)

        normalized[chart_id] = chart_copy

    return normalized


def _chart_id_from_item(item: dict) -> str | None:
    """Return the chart identifier from known chart.json shapes."""
    for key in ("id", "chart_id", "name"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _chart_map_from_parsed_json(parsed: Any) -> dict:
    """Return a chart-id keyed map from supported charts.json root shapes."""
    if isinstance(parsed, list):
        return {
            chart_id: item
            for item in parsed
            if isinstance(item, dict)
            for chart_id in [_chart_id_from_item(item)]
            if chart_id
        }

    if not isinstance(parsed, dict):
        return {}

    charts_list = parsed.get("charts")
    if isinstance(charts_list, list):
        return {
            chart_id: item
            for item in charts_list
            if isinstance(item, dict)
            for chart_id in [_chart_id_from_item(item)]
            if chart_id
        }

    if all(isinstance(value, dict) for value in parsed.values()):
        return parsed

    return {}


def _series_fact(series: dict[str, Any]) -> str | None:
    data_key = series.get("dataKey") or series.get("key")
    if not isinstance(data_key, str) or not data_key.strip():
        return None
    label = series.get("label") or series.get("name") or _labelize_key(data_key)
    series_type = series.get("type")
    if isinstance(series_type, str) and series_type.strip():
        return f"{label} ({data_key}, {series_type})"
    return f"{label} ({data_key})"


def _provenance_fact(provenance: Any) -> str | None:
    if not isinstance(provenance, dict):
        return None

    pieces: list[str] = []
    for key in (
        "source_series",
        "source_files",
        "raw_window",
        "raw_latest_observation",
        "displayed_window",
        "displayed_latest_label",
        "frequency",
        "resampling",
        "normalization",
        "limitations",
    ):
        value = provenance.get(key)
        if value is None or value == "" or value == [] or value == {}:
            continue
        pieces.append(f"{key}={_compact_provenance_value(value, key=key)}")
    if not pieces:
        return None
    return "provenance=" + " | ".join(pieces[:10])


def _compact_provenance_value(value: Any, *, key: str) -> str:
    if isinstance(value, dict):
        items = []
        for item_key, item_value in list(value.items())[:8]:
            if key == "source_files":
                item_value = Path(str(item_value)).name
            items.append(f"{item_key}:{item_value}")
        return ", ".join(items)
    if isinstance(value, list):
        items = value[:8]
        if key == "source_files":
            items = [Path(str(item)).name for item in items]
        return ", ".join(str(item) for item in items)
    return str(value)


def _reference_line_fact(line: Any) -> str | None:
    normalized = _normalize_reference_line(line)
    if not isinstance(normalized, dict):
        return None
    axis = normalized.get("axis")
    value = normalized.get("value")
    if axis not in {"x", "y"} or value is None:
        return None
    label = str(normalized.get("label") or "").strip()
    axis_value = f"{axis}={value}"
    return f"{label} ({axis_value})" if label else axis_value


def _compact_chart_facts_for_draft(charts_map: dict[str, Any]) -> str:
    """Return concise chart facts so prose matches the renderable artifacts."""

    if not charts_map:
        return ""

    normalized = _normalize_chart_definitions(charts_map)
    lines = [
        "Chart facts from charts.json. Describe only the listed chart type, series, axes, reference bands, nodes, and data categories; do not invent overlays, rankings, or fields absent from these facts."
    ]
    for chart_id, chart in list(normalized.items())[:10]:
        if not isinstance(chart, dict):
            continue
        chart_type = chart.get("type") or "unknown"
        title = chart.get("title") or chart_id
        pieces = [f"- {chart_id}: type={chart_type}; title={title}"]
        description = chart.get("description")
        if isinstance(description, str) and description.strip():
            pieces.append(f"description={description.strip()}")
        provenance = _provenance_fact(chart.get("provenance"))
        if provenance:
            pieces.append(provenance)

        if chart_type in {"line", "bar", "area", "composed"}:
            x_key = chart.get("xAxisKey") or chart.get("xKey")
            if isinstance(x_key, str) and x_key:
                pieces.append(f"xAxisKey={x_key}")
            series_facts = [
                fact
                for item in chart.get("series", [])
                if isinstance(item, dict)
                for fact in [_series_fact(item)]
                if fact
            ]
            if series_facts:
                pieces.append("series=" + "; ".join(series_facts[:8]))
            reference_areas = chart.get("referenceAreas")
            if isinstance(reference_areas, list) and reference_areas:
                labels = [
                    str(area.get("label")).strip()
                    for area in reference_areas[:6]
                    if isinstance(area, dict) and area.get("label")
                ]
                pieces.append(
                    "referenceAreas="
                    + (", ".join(labels) if labels else str(len(reference_areas)))
                )
            reference_lines = chart.get("referenceLines")
            if isinstance(reference_lines, list) and reference_lines:
                facts = [
                    fact
                    for line in reference_lines[:6]
                    for fact in [_reference_line_fact(line)]
                    if fact
                ]
                if facts:
                    pieces.append("referenceLines=" + ", ".join(facts))

        elif chart_type == "scatter":
            for key in ("xKey", "yKey", "sizeKey", "colorKey"):
                value = chart.get(key)
                if isinstance(value, str) and value:
                    pieces.append(f"{key}={value}")
            data = chart.get("data")
            if isinstance(data, list) and data:
                labels = [
                    str(row.get("analog") or row.get("name") or row.get("label")).strip()
                    for row in data[:6]
                    if isinstance(row, dict)
                    and (row.get("analog") or row.get("name") or row.get("label"))
                ]
                if labels:
                    pieces.append("points=" + ", ".join(labels))

        elif chart_type == "radar":
            angle_key = chart.get("angleKey")
            if isinstance(angle_key, str) and angle_key:
                pieces.append(f"angleKey={angle_key}")
            series_facts = [
                fact
                for item in chart.get("series", [])
                if isinstance(item, dict)
                for fact in [_series_fact(item)]
                if fact
            ]
            if series_facts:
                pieces.append("series=" + "; ".join(series_facts[:8]))
            data = chart.get("data")
            if isinstance(data, list) and data:
                labels = [
                    str(row.get(angle_key) or row.get("metric") or row.get("name")).strip()
                    for row in data[:8]
                    if isinstance(row, dict)
                    and (row.get(angle_key) or row.get("metric") or row.get("name"))
                ]
                if labels:
                    pieces.append("metrics=" + ", ".join(labels))

        elif chart_type == "sankey":
            data = chart.get("data") if isinstance(chart.get("data"), dict) else {}
            nodes = data.get("nodes") if isinstance(data, dict) else []
            links = data.get("links") if isinstance(data, dict) else []
            if isinstance(nodes, list) and nodes:
                node_names = [
                    str(node.get("name")).strip()
                    for node in nodes[:8]
                    if isinstance(node, dict) and node.get("name")
                ]
                if node_names:
                    pieces.append("nodes=" + ", ".join(node_names))
            if isinstance(links, list) and links:
                pieces.append(f"links={len(links)}")

        elif chart_type in {"pie", "treemap", "radialBar", "funnel", "sunburst"}:
            data = chart.get("data")
            if isinstance(data, list) and data:
                labels = [
                    str(row.get("name") or row.get("label") or row.get("metric")).strip()
                    for row in data[:8]
                    if isinstance(row, dict)
                    and (row.get("name") or row.get("label") or row.get("metric"))
                ]
                if labels:
                    pieces.append("segments=" + ", ".join(labels))

        lines.append("; ".join(pieces))

    return "\n".join(lines)[:4500]


def _resolve_charts_json_path(
    runtime: ToolRuntime[ResearchContext], charts_json_path: str
) -> str:
    """Pick the first existing charts.json — caller path, then canonical job output_dir."""
    candidates: list[Path] = []
    raw_path = charts_json_path.strip()
    looks_like_json_path = raw_path.endswith(".json") and "\n" not in raw_path and len(raw_path) <= 512
    if raw_path and looks_like_json_path:
        p = Path(raw_path).expanduser()
        candidates.append(p)
        if not p.is_absolute():
            candidates.append(Path.cwd() / p)
    od = runtime.context.output_dir
    if od:
        candidates.append(Path(od) / "charts.json")
    for c in candidates:
        try:
            resolved = c.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return str(resolved)
    return str(Path(od) / "charts.json") if od else (raw_path if looks_like_json_path else "")


def _compact_execution_summary(
    runtime: ToolRuntime[ResearchContext],
    execution_summary: str,
    original_query: str = "",
) -> str:
    """Return writer-useful summary text from inline JSON or a job-local JSON path."""
    value = (execution_summary or "").strip()
    if not value:
        return ""

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None
    else:
        if isinstance(parsed, dict):
            return _append_source_context_summary(
                _compact_execution_summary_payload(parsed, original_query=original_query),
                runtime,
                parsed,
            )
        return json.dumps(parsed, ensure_ascii=False)[:4000]

    if "\n" in value or len(value) > 512:
        return value[:4000]
    if not value.endswith(".json"):
        return value[:4000]

    candidates: list[Path] = []
    p = Path(value).expanduser()
    candidates.append(p)
    if not p.is_absolute():
        candidates.append(Path.cwd() / p)
        if runtime.context.output_dir:
            candidates.append(Path(runtime.context.output_dir) / p.name)

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        try:
            output_dir = Path(runtime.context.output_dir).resolve()
        except OSError:
            output_dir = None
        if output_dir and output_dir not in resolved.parents and resolved != output_dir:
            continue
        if resolved.is_file():
            try:
                value = resolved.read_text(encoding="utf-8")
            except OSError:
                break
            break

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value[:4000]

    if isinstance(parsed, dict):
        return _append_source_context_summary(
            _compact_execution_summary_payload(parsed, original_query=original_query),
            runtime,
            parsed,
        )
    return json.dumps(parsed, ensure_ascii=False)[:4000]


def _execution_summary_payload(
    runtime: ToolRuntime[ResearchContext],
    execution_summary: str,
) -> dict[str, Any]:
    """Return execution_summary JSON from inline text or a job-local path."""
    def _job_local_payload() -> dict[str, Any]:
        output_dir = getattr(runtime.context, "output_dir", None)
        if not output_dir:
            return {}
        candidate = Path(output_dir) / "execution_summary.json"
        try:
            parsed = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    value = (execution_summary or "").strip()
    if not value:
        return _job_local_payload()

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None
    else:
        return parsed if isinstance(parsed, dict) else {}

    if "\n" in value or len(value) > 512 or not value.endswith(".json"):
        return _job_local_payload()

    candidates: list[Path] = []
    p = Path(value).expanduser()
    candidates.append(p)
    if not p.is_absolute():
        candidates.append(Path.cwd() / p)
        if runtime.context.output_dir:
            candidates.append(Path(runtime.context.output_dir) / p.name)

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        try:
            output_dir = Path(runtime.context.output_dir).resolve()
        except OSError:
            output_dir = None
        if output_dir and output_dir not in resolved.parents and resolved != output_dir:
            continue
        if not resolved.is_file():
            continue
        try:
            parsed = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _job_local_payload()
        return parsed if isinstance(parsed, dict) else {}
    return _job_local_payload()


def _fmt_summary_number(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value:
            return None
        return f"{value:.4g}"
    return str(value).strip() if str(value).strip() else None


def _append_source_context_summary(
    compact: str,
    runtime: ToolRuntime[ResearchContext],
    parsed: dict[str, Any],
) -> str:
    context = _compact_source_context_files(runtime, parsed)
    if not context:
        return compact
    combined = compact + "\n\n" + context if compact else context
    return combined[:8000]


def _compact_source_context_files(
    runtime: ToolRuntime[ResearchContext],
    parsed: dict[str, Any],
) -> str | None:
    files = parsed.get("source_context_files")
    if not isinstance(files, list) or not files:
        return None

    lines: list[str] = []
    for value in files[:12]:
        if not isinstance(value, str):
            continue
        path = _safe_source_context_path(runtime, value)
        if path is None:
            continue
        rows = _read_csv_context_rows(path)
        if not rows:
            continue
        name = path.name.lower()
        if "worldbank" in name:
            lines.extend(_summarize_worldbank_rows(rows))
        elif "census" in name:
            lines.extend(_summarize_census_rows(rows))
        elif "sec_edgar_company_facts" in name:
            lines.extend(_summarize_sec_rows(path, rows))

    if not lines:
        return None
    return (
        "Exact supplemental source-context values from saved public-data CSVs. "
        "Use these values when discussing international peers, regional consumers, "
        "and company fundamentals; do not estimate replacements:\n"
        + "\n".join(dict.fromkeys(lines))
    )


def _safe_source_context_path(
    runtime: ToolRuntime[ResearchContext],
    value: str,
) -> Path | None:
    path = Path(value).expanduser()
    candidates = [path]
    if not path.is_absolute():
        output_dir = getattr(runtime.context, "output_dir", None)
        if output_dir:
            candidates.append(Path(output_dir) / path.name)
        candidates.append(_BACKEND_DIR / path)

    allowed_roots = [_BACKEND_DIR / "data", Path(OUTPUT_BASE_DIR)]
    output_dir = getattr(runtime.context, "output_dir", None)
    if output_dir:
        allowed_roots.append(Path(output_dir))
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.suffix.lower() != ".csv" or not resolved.is_file():
            continue
        try:
            if any(
                root.resolve() == resolved or root.resolve() in resolved.parents
                for root in allowed_roots
            ):
                return resolved
        except OSError:
            continue
    return None


def _read_csv_context_rows(path: Path, limit: int = 500) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            return [row for _, row in zip(range(limit), reader)]
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


def _latest_numeric_row(
    rows: list[dict[str, str]],
    year_key: str,
) -> dict[str, str] | None:
    valid = []
    for row in rows:
        try:
            year = int(float(row.get(year_key, "")))
        except (TypeError, ValueError):
            continue
        valid.append((year, row))
    if not valid:
        return None
    valid.sort(key=lambda item: item[0])
    return valid[-1][1]


def _summarize_worldbank_rows(rows: list[dict[str, str]]) -> list[str]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        indicator = row.get("indicator_id") or row.get("indicator_name")
        country = row.get("country_code") or row.get("country_name")
        if indicator and country:
            grouped.setdefault((indicator, country), []).append(row)

    by_indicator: dict[str, list[str]] = {}
    for (indicator, country), group in grouped.items():
        latest = _latest_numeric_row(
            [row for row in group if _fmt_summary_number(row.get("value")) is not None],
            "year",
        )
        if not latest:
            continue
        value = _fmt_summary_number(latest.get("value"))
        year = latest.get("year")
        if value is None or not year:
            continue
        label = latest.get("indicator_name") or indicator
        by_indicator.setdefault(label, []).append(f"{country} {year}={value}")

    lines = []
    for label, values in by_indicator.items():
        if values:
            lines.append(f"- World Bank {label}: " + "; ".join(values[:8]))
    return lines


def _summarize_census_rows(rows: list[dict[str, str]]) -> list[str]:
    target_states = {"California", "Texas", "Florida", "New York"}
    lines = []
    for row in rows:
        state = row.get("NAME")
        if state not in target_states:
            continue
        fields = []
        for key, label in (
            ("DP05_0001E", "population"),
            ("DP03_0062E", "median_income"),
            ("DP04_0089E", "median_home_value"),
        ):
            value = _fmt_summary_number(row.get(key))
            if value is not None:
                fields.append(f"{label}={value}")
        if fields:
            lines.append(f"- Census ACS {state}: " + ", ".join(fields))
    return lines


def _summarize_sec_rows(path: Path, rows: list[dict[str, str]]) -> list[str]:
    ticker_match = re.search(r"([A-Za-z]{1,5})_sec_edgar_company_facts", path.name)
    ticker = ticker_match.group(1).upper() if ticker_match else "company"
    latest = _latest_numeric_row(rows, "fiscal_year")
    if not latest:
        return []
    fields = []
    for key in ("fiscal_year", "revenue", "net_income", "assets", "liabilities", "shares"):
        value = _fmt_summary_number(latest.get(key))
        if value is not None:
            fields.append(f"{key}={value}")
    return [f"- SEC EDGAR {ticker} latest: " + ", ".join(fields)] if fields else []


def _compact_by_year_payload(parsed: dict) -> str | None:
    lines: list[str] = []
    for key, rows in parsed.items():
        if not (isinstance(key, str) and key.endswith("_by_year") and isinstance(rows, dict)):
            continue
        year_rows: list[tuple[int, dict[str, Any]]] = []
        for year, row in rows.items():
            if not isinstance(row, dict):
                continue
            try:
                year_int = int(row.get("year") or row.get("fiscal_year") or year)
            except (TypeError, ValueError):
                continue
            year_rows.append((year_int, row))
        if len(year_rows) < 2:
            continue
        year_rows.sort(key=lambda item: item[0])
        first_year, first_row = year_rows[0]
        last_year, last_row = year_rows[-1]
        field_lines: list[str] = []
        for field, first_value in first_row.items():
            if field in {"year", "fiscal_year"}:
                continue
            last_value = last_row.get(field)
            if not isinstance(first_value, (int, float)) or isinstance(first_value, bool):
                continue
            if not isinstance(last_value, (int, float)) or isinstance(last_value, bool):
                continue
            if first_value != first_value or last_value != last_value:
                continue
            delta = last_value - first_value
            pieces = [
                f"{first_year}={_fmt_summary_number(first_value)}",
                f"{last_year}={_fmt_summary_number(last_value)}",
                f"change={_fmt_summary_number(delta)}",
            ]
            periods = last_year - first_year
            if periods > 0 and first_value > 0 and last_value > 0:
                cagr = (last_value / first_value) ** (1 / periods) - 1
                pieces.append(f"CAGR={cagr * 100:.2f}%")
            field_lines.append(f"  - {_labelize_key(field)}: " + ", ".join(pieces))
        if field_lines:
            lines.append(
                f"- {_labelize_key(key)} exact endpoints ({first_year}-{last_year}):\n"
                + "\n".join(field_lines[:10])
            )
    if not lines:
        return None
    return "Exact annual series endpoints from execution_summary.json:\n" + "\n".join(lines[:4])


def _compact_top_level_metric_table(parsed: dict, key: str, heading: str) -> str | None:
    rows = parsed.get(key)
    if not isinstance(rows, dict) or not rows:
        return None
    lines = []
    for name, row in list(rows.items())[:12]:
        if not isinstance(row, dict):
            continue
        fields = []
        for metric, value in row.items():
            formatted = _fmt_summary_number(value)
            if formatted is not None:
                fields.append(f"{metric}={formatted}")
        if fields:
            lines.append(f"- {name}: " + ", ".join(fields[:8]))
    if not lines:
        return None
    return heading + ":\n" + "\n".join(lines)


_HEADLINE_SCALAR_KEYS = (
    "latest_unemployment_rate",
    "latest_cpi_yoy",
    "latest_core_pce_yoy",
    "latest_yield_curve_bps",
    "latest_yield_spread_bp",
    "latest_yield_spread",
    "latest_fed_funds_rate",
    "latest_composite_risk",
    "recession_probability_current",
    "current_regime",
    "unrate_forecast_6m",
    "aapl_revenue_cagr_2021_2025",
    "msft_revenue_cagr_2021_2025",
    "national_median_income",
    "rri_current_value",
    "rri_current",
    "rri_threshold",
    "sahm",
    "sahm_rule_value",
    "sahm_triggered",
    "unrate",
    "unemployment_rate",
    "unemployment_current",
    "unemployment_yoy_change",
    "real_wage_yoy_latest",
    "saving_rate_latest",
    "consumer_sentiment_latest",
    "consumer_sentiment_percentile_vs_history",
    "credit_growth_yoy_latest",
    "delinquency_rate_latest",
    "latest_UMCSENT",
    "latest_PSAVERT",
    "latest_DRCLACBS",
    "latest_UNRATE",
    "latest_real_wage_idx",
    "latest_spread",
    "income_growth_yoy_latest",
    "pce_growth_yoy_latest",
    "us_inflation_latest_annual",
    "us_gdp_growth_latest_annual",
    "aapl_revenue_latest_fy",
    "msft_revenue_latest_fy",
    "aapl_net_margin_latest",
    "msft_net_margin_latest",
    "cpi_yoy",
    "fedfunds_rate",
    "real_fed_funds_rate",
    "yield_curve",
    "t10y3m",
    "yield_curve_10y3m",
    "gdp_yoy_growth",
    "gdp_yoy",
    "output_gap",
    "taylor_rule_implied_rate",
)


def _fmt_scalar_metric(value: Any) -> str | None:
    if isinstance(value, bool):
        return str(value).lower()
    return _fmt_summary_number(value)


def _compact_headline_scalar_metrics(parsed: dict) -> str | None:
    """Put exact headline scalars first so prose does not drift from quant outputs."""
    lines: list[str] = []
    seen: set[str] = set()

    statistical_summary = parsed.get("statistical_summary")
    statistical_sources: list[Any] = [statistical_summary]
    all_values: Any = None
    if isinstance(statistical_summary, dict):
        all_values = statistical_summary.get("all_values")
        statistical_sources.extend(
            [
                statistical_summary.get("key_ratios"),
                all_values,
            ]
        )

    for source in (parsed, *statistical_sources):
        if not isinstance(source, dict):
            continue
        if source is all_values:
            for series, row in source.items():
                if not isinstance(row, dict) or "latest" not in row:
                    continue
                key = f"{series}.latest"
                if key in seen:
                    continue
                formatted = _fmt_scalar_metric(row.get("latest"))
                if formatted is None:
                    continue
                seen.add(key)
                date = row.get("latest_date")
                suffix = f" ({date})" if date else ""
                lines.append(f"- {key}: {formatted}{suffix}")
            continue
        for key in _HEADLINE_SCALAR_KEYS:
            if key in seen or key not in source:
                continue
            formatted = _fmt_scalar_metric(source.get(key))
            if formatted is None:
                continue
            seen.add(key)
            lines.append(f"- {key}: {formatted}")

    if not lines:
        return None
    return "Exact headline metrics from execution_summary.json:\n" + "\n".join(lines)


def _compact_shallow_statistical_summary(stats_payload: dict[str, Any]) -> str | None:
    """Preserve simple computed tables and nested values without dumping long histories."""
    if not isinstance(stats_payload, dict) or not stats_payload:
        return None

    lines: list[str] = []
    for key, value in stats_payload.items():
        if key in {"all_values", "descriptive_stats", "rolling_correlations_latest"}:
            continue
        if not isinstance(value, (list, dict)):
            formatted = _fmt_scalar_metric(value)
            if formatted is not None:
                lines.append(f"- {key}: {formatted}")
                continue

        if isinstance(value, list):
            row_lines: list[str] = []
            for row in value[:6]:
                if isinstance(row, dict):
                    fields = [
                        f"{field}={_fmt_summary_number(field_value)}"
                        for field, field_value in row.items()
                        if _fmt_summary_number(field_value) is not None
                    ]
                    if fields:
                        row_lines.append("; ".join(fields[:8]))
                else:
                    item = str(row).strip()
                    if item:
                        row_lines.append(item)
            if row_lines:
                lines.append(f"- {key}: " + " | ".join(row_lines))
            continue

        if isinstance(value, dict):
            fields: list[str] = []
            for field, field_value in value.items():
                if not isinstance(field_value, (list, dict)):
                    formatted_field = _fmt_summary_number(field_value)
                    if formatted_field is not None:
                        fields.append(f"{field}={formatted_field}")
                        continue
                if isinstance(field_value, list):
                    items = [str(item).strip() for item in field_value[:4] if str(item).strip()]
                    if items:
                        fields.append(f"{field}=[" + "; ".join(items) + "]")
            if fields:
                normalized_key = key.lower()
                normalized_fields = {str(field).lower() for field in value}
                if (
                    ("correlation" in normalized_key or normalized_key.endswith("_corr"))
                    and not any(
                        field in normalized_fields
                        for field in {
                            "n",
                            "nobs",
                            "n_obs",
                            "sample_size",
                            "p",
                            "p_value",
                            "pvalue",
                        }
                    )
                ):
                    fields.append(
                        "evidence_caveat=exploratory correlation only; "
                        "sample size and p-values were not reported, so avoid causal "
                        "or statistically precise claims"
                    )
                lines.append(f"- {key}: " + "; ".join(fields[:8]))

    if not lines:
        return None
    return (
        "Exact statistical_summary values from execution_summary.json. "
        "Use these values as controlling facts and do not substitute stale public-memory numbers:\n"
        + "\n".join(lines[:24])
    )


def _compact_macro_evidence_payload(parsed: dict[str, Any]) -> str | None:
    lines: list[str] = []
    snapshot = parsed.get("latest_snapshot")
    if isinstance(snapshot, dict) and snapshot:
        fields = [
            f"{key}={_fmt_summary_number(value) if isinstance(value, (int, float)) else value}"
            for key, value in snapshot.items()
            if value is not None
        ]
        if fields:
            lines.append("- latest_snapshot: " + "; ".join(fields[:16]))

    changes = parsed.get("latest_year_changes")
    if isinstance(changes, list) and changes:
        change_rows = []
        for row in changes[:12]:
            if not isinstance(row, dict):
                continue
            indicator = row.get("indicator")
            change = _fmt_summary_number(row.get("change"))
            latest = _fmt_summary_number(row.get("latest_value"))
            unit = row.get("unit")
            if indicator and change is not None:
                suffix = f" {unit}" if unit else ""
                latest_part = f", latest={latest}" if latest is not None else ""
                change_rows.append(f"{indicator}: change={change}{suffix}{latest_part}")
        if change_rows:
            lines.append("- latest_year_changes: " + "; ".join(change_rows))

    analogs = parsed.get("analog_similarity_ranking")
    if isinstance(analogs, list) and analogs:
        analog_rows = []
        for row in analogs[:8]:
            if not isinstance(row, dict):
                continue
            fields = []
            for key in (
                "distance_score",
                "labor_gap",
                "inflation_gap",
                "rates_gap",
                "consumer_gap",
            ):
                if row.get(key) is not None:
                    fields.append(f"{key}={_fmt_summary_number(row.get(key))}")
            if row.get("analog") and fields:
                analog_rows.append(f"{row['analog']}: " + ", ".join(fields))
        if analog_rows:
            lines.append(
                "- analog_similarity_ranking, closest first: " + "; ".join(analog_rows)
            )

    category_scores = parsed.get("category_scores")
    if isinstance(category_scores, list) and category_scores:
        scores = []
        for row in category_scores[:8]:
            if not isinstance(row, dict):
                continue
            name = row.get("name")
            value = _fmt_summary_number(row.get("value"))
            if name and value is not None:
                scores.append(f"{name}={value}")
        if scores:
            lines.append("- category_stress_scores_0_100: " + "; ".join(scores))

    chart_map = parsed.get("chart_insight_map")
    if isinstance(chart_map, dict) and chart_map:
        insights = [
            f"{chart_id}: {insight}"
            for chart_id, insight in list(chart_map.items())[:10]
            if isinstance(insight, str) and insight.strip()
        ]
        if insights:
            lines.append("- chart_insight_map: " + "; ".join(insights))

    limitations = parsed.get("limitations")
    if isinstance(limitations, list) and limitations:
        items = [str(item).strip() for item in limitations[:10] if str(item).strip()]
        if items:
            lines.append("- limitations: " + "; ".join(items))

    if not lines:
        return None
    return (
        "Structured macro evidence from execution_summary.json. Use these rows as "
        "controlling computed facts:\n" + "\n".join(lines)
    )


def _compact_source_unit_payload(parsed: dict[str, Any]) -> str | None:
    metadata = parsed.get("source_unit_metadata")
    comparisons = parsed.get("unit_comparisons")
    errors = parsed.get("source_unit_errors")
    lines: list[str] = []

    if isinstance(metadata, list) and metadata:
        rendered = []
        for row in metadata[:16]:
            if not isinstance(row, dict):
                continue
            key = row.get("source_key") or row.get("series_id") or row.get("title")
            units = row.get("units")
            family = row.get("unit_family")
            basis = row.get("unit_basis")
            if not key or not (units or family or basis):
                continue
            pieces = [str(key)]
            if row.get("series_id") and row.get("series_id") != key:
                pieces.append(f"series_id={row.get('series_id')}")
            if units:
                pieces.append(f"units={units}")
            if family:
                pieces.append(f"unit_family={family}")
            if basis:
                pieces.append(f"unit_basis={basis}")
            rendered.append("; ".join(pieces))
        if rendered:
            lines.append("- source_unit_metadata: " + " | ".join(rendered))

    if isinstance(comparisons, list) and comparisons:
        rendered = []
        for row in comparisons[:12]:
            if not isinstance(row, dict):
                continue
            comparison_id = row.get("id") or row.get("comparison_id") or "comparison"
            pieces = [
                str(comparison_id),
                f"status={row.get('status')}",
                f"compatible={row.get('compatible')}",
            ]
            if row.get("metric"):
                pieces.append(f"metric={row.get('metric')}")
            if row.get("conversion"):
                pieces.append(f"conversion={row.get('conversion')}")
            if row.get("error"):
                pieces.append(f"error={row.get('error')}")
            rendered.append("; ".join(pieces))
        if rendered:
            lines.append("- unit_comparisons: " + " | ".join(rendered))

    if isinstance(errors, list) and errors:
        lines.append("- source_unit_errors: " + " | ".join(str(item) for item in errors[:8]))
    elif isinstance(errors, str) and errors.strip():
        lines.append("- source_unit_errors: " + errors.strip())

    if not lines:
        return None
    return (
        "Source-unit contract from execution_summary.json. Use only comparisons "
        "with status=passed or status=converted; do not write direct gap, "
        "divergence, or ratio claims for failed or missing unit comparisons:\n"
        + "\n".join(lines)
    )


def _numeric_facts_from_summary(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[object] = [parsed.get("numeric_facts")]
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        for item in normalize_numeric_facts(candidate):
            fact_id = str(item.get("id") or item.get("source_key") or "")
            if not fact_id or fact_id in seen:
                continue
            seen.add(fact_id)
            facts.append(item)
    return facts


def _compact_numeric_facts_payload(parsed: dict[str, Any]) -> str | None:
    facts = _numeric_facts_from_summary(parsed)
    if not facts:
        return None

    rendered: list[str] = []
    for fact in facts[:30]:
        display = fact.get("display_value")
        source_key = fact.get("source_key")
        if not display or not source_key:
            continue
        fields = [
            f"{fact.get('id') or source_key}={display}",
            f"raw={fact.get('raw_value')}",
            f"tolerance={fact.get('tolerance')}",
            f"source_key={source_key}",
        ]
        if fact.get("as_of_date") is not None:
            fields.append(f"as_of={fact.get('as_of_date')}")
        if fact.get("metric"):
            fields.append(f"metric={fact.get('metric')}")
        if fact.get("operation"):
            fields.append(f"operation={fact.get('operation')}")
        if fact.get("transform_basis"):
            fields.append(f"transform_basis={fact.get('transform_basis')}")
        if fact.get("semantic_role"):
            fields.append(f"semantic_role={fact.get('semantic_role')}")
        if fact.get("literal_required") is False:
            fields.append("literal_required=false")
        if fact.get("state_description"):
            fields.append(f"state_description={fact.get('state_description')}")
        rendered.append("(" + "; ".join(str(field) for field in fields) + ")")

    if not rendered:
        return None
    return (
        "Display-ready numeric facts from execution_summary.json. Use "
        "display_value verbatim when literal_required is true; when "
        "literal_required=false, use state_description instead of forcing the "
        "numeric display_value into prose:\n- " + "\n- ".join(rendered)
    )


_HELPER_TABLE_KEYS = (
    "latest_fundamentals",
    "company_history_rows",
    "trend_diagnostics",
    "macro_overlay",
    "company_macro_sensitivity",
    "scenario_score_rows",
    "scenario_projection_rows",
    "current_signal_facts",
    "signal_score_rows",
    "signal_event_rows",
    "signal_false_positive_windows",
    "lead_time_rows",
    "replay_rows",
    "forecast_rows",
    "forecast_table",
    "walk_forward_backtest_rows",
    "model_validation_rows",
    "model_comparison_by_horizon",
    "model_comparison_rows",
    "forecast_band_rows",
    "historical_failure_episodes",
    "predictor_contributions",
    "historical_window_coverage",
    "analog_similarity_ranking",
    "analog_profiles",
    "analog_profile_rows",
    "composite_score_rows",
    "regime_evidence_rows",
    "regime_history_rows",
    "regime_analog_rows",
    "missing_indicator_rows",
)
_HELPER_DIAGNOSTIC_KEYS = (
    "validation_diagnostics",
    "event_backtest_metrics",
    "signal_validation_metrics",
    "share_count_diagnostics",
    "latest_signal_observation",
    "signal_design",
    "forecast_origin",
    "validation_window",
    "diagnostics",
    "comparison_design",
    "replay_design",
    "current_regime_row",
    "regime_design",
    "composite_current_row",
    "composite_validation_metrics",
    "composite_validation_design",
    "feature_coverage",
    "feature_transforms",
    "normalization_stats",
    "weights_or_model",
    "thresholds",
)


def _is_non_empty_payload(value: Any) -> bool:
    if isinstance(value, (dict, list)):
        return bool(value)
    return value is not None and value != ""


def _helper_evidence_for_draft(
    parsed: dict[str, Any],
    original_query: str = "",
) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    facts = _numeric_facts_from_summary(parsed)
    if facts:
        evidence["numeric_facts"] = facts

    requested_geo = compact_requested_geography_coverage(original_query, parsed)
    if requested_geo:
        evidence["requested_geography_coverage"] = requested_geo
    requested_subject = compact_requested_subject_evidence(original_query, parsed)
    if requested_subject:
        evidence["requested_subject_evidence"] = requested_subject

    for key in (
        "source_coverage",
        "methods_used",
        "chart_ids",
        "limitations",
        "source_context_files",
        "source_unit_metadata",
        "unit_comparisons",
        "source_unit_errors",
        "current_signal_facts",
    ):
        value = parsed.get(key)
        if _is_non_empty_payload(value):
            evidence[key] = value

    tables = {
        key: value
        for key in _HELPER_TABLE_KEYS
        if _is_non_empty_payload((value := parsed.get(key)))
    }
    diagnostics = {
        key: value
        for key in _HELPER_DIAGNOSTIC_KEYS
        if _is_non_empty_payload((value := parsed.get(key)))
    }
    if tables:
        evidence["tables"] = tables
    if diagnostics:
        evidence["diagnostics"] = diagnostics
    return evidence


def _render_mapping_fields(row: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    fields: list[str] = []
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        formatted = _fmt_summary_number(value)
        fields.append(f"{key}={formatted if formatted is not None else value}")
    return fields


def _compact_helper_evidence_payload(
    parsed: dict[str, Any],
    original_query: str = "",
) -> str | None:
    evidence = _helper_evidence_for_draft(parsed, original_query=original_query)
    if not evidence:
        return None

    lines = [
        "Generic helper-produced evidence from execution_summary.json. Validate "
        "draft claims against numeric_facts, source coverage, methods, chart IDs, "
        "tables, diagnostics, and limitations; state unavailable evidence rather "
        "than inventing values."
    ]

    numeric_facts_summary = _compact_numeric_facts_payload(parsed)
    if numeric_facts_summary:
        lines.append(numeric_facts_summary)

    source_coverage = evidence.get("source_coverage")
    if isinstance(source_coverage, dict):
        rendered = []
        for key, value in list(source_coverage.items())[:12]:
            if not isinstance(value, dict):
                continue
            fields = _render_mapping_fields(value, ("status", "limitation"))
            if fields:
                rendered.append(f"{key}: " + "; ".join(fields))
        if rendered:
            lines.append("- source_coverage: " + " | ".join(rendered))

    requested_geo = evidence.get("requested_geography_coverage")
    if isinstance(requested_geo, dict):
        fields = []
        for key in ("required", "status", "scope"):
            if key in requested_geo:
                fields.append(f"{key}={requested_geo[key]}")
        dimensions = requested_geo.get("requested_dimensions")
        if isinstance(dimensions, list) and dimensions:
            fields.append("requested_dimensions=" + ", ".join(str(item) for item in dimensions[:8]))
        evidence_keys = requested_geo.get("evidence_keys")
        if isinstance(evidence_keys, list) and evidence_keys:
            fields.append("evidence_keys=" + ", ".join(str(item) for item in evidence_keys[:8]))
        unavailable = requested_geo.get("unavailable_sources")
        if isinstance(unavailable, list) and unavailable:
            fields.append(
                "unavailable_sources=" + ", ".join(str(item) for item in unavailable[:8])
            )
        blocker = requested_geo.get("blocker")
        if isinstance(blocker, str) and blocker.strip():
            fields.append("blocker=" + blocker.strip())
        if fields:
            lines.append("- requested_geography_coverage: " + "; ".join(fields))

    requested_subject = evidence.get("requested_subject_evidence")
    if isinstance(requested_subject, dict):
        fields = []
        for key in ("required", "status", "scope"):
            if key in requested_subject:
                fields.append(f"{key}={requested_subject[key]}")
        subjects = requested_subject.get("requested_subjects")
        if isinstance(subjects, list) and subjects:
            fields.append("requested_subjects=" + ", ".join(str(item) for item in subjects[:8]))
        direct_keys = requested_subject.get("direct_evidence_keys")
        if isinstance(direct_keys, list) and direct_keys:
            fields.append("direct_evidence_keys=" + ", ".join(str(item) for item in direct_keys[:8]))
        proxy_keys = requested_subject.get("proxy_evidence_keys")
        if isinstance(proxy_keys, list) and proxy_keys:
            fields.append("proxy_evidence_keys=" + ", ".join(str(item) for item in proxy_keys[:8]))
        unavailable = requested_subject.get("unavailable_sources")
        if isinstance(unavailable, list) and unavailable:
            fields.append(
                "unavailable_sources=" + ", ".join(str(item) for item in unavailable[:8])
            )
        blocker = requested_subject.get("blocker")
        if isinstance(blocker, str) and blocker.strip():
            fields.append("blocker=" + blocker.strip())
        if fields:
            lines.append("- requested_subject_evidence: " + "; ".join(fields))

    methods = evidence.get("methods_used")
    if isinstance(methods, list) and methods:
        lines.append("- methods_used: " + ", ".join(str(item) for item in methods[:12]))

    chart_ids = evidence.get("chart_ids")
    if isinstance(chart_ids, list) and chart_ids:
        lines.append("- chart_ids: " + ", ".join(str(item) for item in chart_ids[:20]))

    diagnostics = evidence.get("diagnostics")
    if isinstance(diagnostics, dict):
        rendered_diagnostic_keys: set[str] = set()
        share_count_diagnostics = diagnostics.get("share_count_diagnostics")
        if isinstance(share_count_diagnostics, dict) and share_count_diagnostics:
            rendered_diagnostic_keys.add("share_count_diagnostics")
            rendered = []
            for ticker, diagnostic in list(share_count_diagnostics.items())[:10]:
                if not isinstance(diagnostic, dict):
                    continue
                label = diagnostic.get("ticker") or ticker
                fields = _render_mapping_fields(
                    diagnostic,
                    (
                        "status",
                        "comparability",
                        "full_window_start_year",
                        "full_window_end_year",
                        "full_window_trend",
                        "latest_comparable_start_year",
                        "latest_comparable_end_year",
                        "latest_comparable_trend",
                        "latest_comparable_change_pct",
                        "limitation",
                    ),
                )
                if fields:
                    rendered.append(f"{label}: " + "; ".join(fields))
            if rendered:
                lines.append("- share_count_diagnostics: " + " | ".join(rendered))

        for diagnostic_key, diagnostic in diagnostics.items():
            if diagnostic_key in rendered_diagnostic_keys:
                continue
            if not isinstance(diagnostic, dict) or not diagnostic:
                continue
            diagnostic_keys = [
                str(key) for key in list(diagnostic.keys())[:10] if key != "metrics"
            ]
            fields = _render_mapping_fields(
                diagnostic,
                tuple(diagnostic_keys),
            )
            metrics = diagnostic.get("metrics")
            if isinstance(metrics, dict):
                fields.extend(
                    _render_mapping_fields(
                        metrics,
                        tuple(str(key) for key in list(metrics.keys())[:10]),
                    )
                )
            if fields:
                lines.append(f"- {diagnostic_key}: " + "; ".join(fields))

    tables = evidence.get("tables")
    if isinstance(tables, dict):
        rendered_table_keys: set[str] = set()
        coverage_rows = tables.get("historical_window_coverage")
        if isinstance(coverage_rows, list) and coverage_rows:
            rendered_table_keys.add("historical_window_coverage")
            rendered = []
            for row in coverage_rows[:12]:
                if not isinstance(row, dict) or not row.get("label"):
                    continue
                fields = _render_mapping_fields(
                    row,
                    (
                        "status",
                        "requested",
                        "observed_months",
                        "expected_months",
                        "coverage_ratio",
                    ),
                )
                if row.get("requested_years"):
                    fields.append(f"requested_years={row.get('requested_years')}")
                if fields:
                    rendered.append(f"{row.get('label')}: " + "; ".join(fields))
            if rendered:
                lines.append("- historical_window_coverage: " + " | ".join(rendered))

        ranking_rows = tables.get("analog_similarity_ranking")
        if isinstance(ranking_rows, list) and ranking_rows:
            rendered_table_keys.add("analog_similarity_ranking")
            rendered = []
            for row in ranking_rows[:10]:
                if not isinstance(row, dict) or not (row.get("label") or row.get("analog")):
                    continue
                label = row.get("label") or row.get("analog")
                fields = _render_mapping_fields(
                    row,
                    (
                        "raw_distance",
                        "distance_score",
                        "normalized_similarity",
                        "status",
                    ),
                )
                if fields:
                    rendered.append(f"{label}: " + "; ".join(fields))
            if rendered:
                lines.append("- analog_similarity_ranking: " + " | ".join(rendered))

        profile_rows = tables.get("analog_profiles")
        if isinstance(profile_rows, dict) and profile_rows:
            rendered_table_keys.add("analog_profiles")
            rendered = []
            for label, profile in list(profile_rows.items())[:8]:
                if not isinstance(profile, dict):
                    continue
                fields = _render_mapping_fields(
                    profile,
                    tuple(str(key) for key in list(profile.keys())[:8]),
                )
                if fields:
                    rendered.append(f"{label}: " + "; ".join(fields))
            if rendered:
                lines.append("- analog_profiles: " + " | ".join(rendered))

        latest = tables.get("latest_fundamentals")
        if isinstance(latest, dict):
            rendered_table_keys.add("latest_fundamentals")
            for ticker, facts in list(latest.items())[:8]:
                if not isinstance(facts, dict):
                    continue
                fields = _render_mapping_fields(
                    facts,
                    (
                        "fiscal_year",
                        "revenue_b",
                        "revenue_growth_pct",
                        "revenue_cagr_pct",
                        "gross_margin_pct",
                        "operating_margin_pct",
                        "net_margin_pct",
                        "operating_cash_flow_b",
                        "free_cash_flow_b",
                        "cash_and_securities_b",
                        "long_term_debt_b",
                        "diluted_eps",
                    ),
                )
                if fields:
                    lines.append(f"- latest_fundamentals.{ticker}: " + "; ".join(fields))

        for table_key in (
            "trend_diagnostics",
            "company_macro_sensitivity",
            "scenario_score_rows",
            "scenario_projection_rows",
            "current_signal_facts",
            "signal_score_rows",
            "signal_event_rows",
            "signal_false_positive_windows",
            "lead_time_rows",
            "replay_rows",
            "analog_profile_rows",
        ):
            rows = tables.get(table_key)
            if not isinstance(rows, list) or not rows:
                continue
            rendered_table_keys.add(table_key)
            rendered = []
            for row in rows[:10]:
                if not isinstance(row, dict):
                    continue
                label = (
                    row.get("ticker")
                    or row.get("scenario")
                    or row.get("signal_id")
                    or row.get("regime")
                    or row.get("indicator")
                    or row.get("category")
                    or row.get("event_label")
                    or row.get("label")
                    or row.get("window_label")
                    or row.get("signal_date")
                    or row.get("event_date")
                    or row.get("date")
                    or table_key
                )
                fields = _render_mapping_fields(
                    row,
                    (
                        "start",
                        "end",
                        "date",
                        "status",
                        "signal_id",
                        "score",
                        "value",
                        "met_threshold",
                        "triggered",
                        "above_threshold",
                        "threshold_distance",
                        "as_of_date",
                        "chart_id",
                        "data_key",
                        "max_score_date",
                        "components_triggered",
                        "max_score",
                        "components_at_peak",
                        "window_label",
                        "signal_date",
                        "target_date",
                        "signal_value",
                        "threshold",
                        "direction",
                        "event_date",
                        "prior_signal_date",
                        "lead_periods",
                        "periods",
                        "unrate_change_pp",
                        "indpro_change_pct",
                        "real_pce_change_pct",
                        "sentiment_decline_pts",
                        "auc",
                        "brier_score",
                        "revenue_cagr_pct",
                        "latest_revenue_growth_pct",
                        "latest_fiscal_year",
                        "latest_avg_fedfunds_pct",
                        "latest_recession_months",
                        "high_rate_fiscal_year_count",
                        "net_margin_change_last_3y_pp",
                        "delta_vs_current",
                        "subject",
                        "base_period",
                        "projection_period",
                        "base_revenue",
                        "base_revenue_unit",
                        "revenue_growth_pct",
                        "projected_revenue",
                        "projected_revenue_unit",
                        "gross_margin_pct",
                        "projected_gross_profit",
                        "projected_gross_profit_unit",
                        "operating_expense",
                        "operating_expense_unit",
                        "projected_operating_income",
                        "operating_income_unit",
                        "chart_label",
                        "revenue_data_key",
                        "gross_profit_data_key",
                        "operating_income_data_key",
                    ),
                )
                if label and fields:
                    rendered.append(f"{label}: " + "; ".join(fields))
            if rendered:
                lines.append(f"- {table_key}: " + " | ".join(rendered))

        for table_key, rows in tables.items():
            if table_key in rendered_table_keys:
                continue
            rendered = []
            if isinstance(rows, list):
                for row in rows[:10]:
                    if not isinstance(row, dict):
                        continue
                    label = (
                        row.get("label")
                        or row.get("scenario")
                        or row.get("regime")
                        or row.get("indicator")
                        or row.get("category")
                        or row.get("date")
                        or row.get("start")
                        or row.get("signal_date")
                        or row.get("event_date")
                        or row.get("target_date")
                        or row.get("prediction_date")
                        or row.get("horizon")
                        or table_key
                    )
                    field_keys = tuple(str(key) for key in list(row.keys())[:8])
                    fields = _render_mapping_fields(row, field_keys)
                    if label and fields:
                        rendered.append(f"{label}: " + "; ".join(fields))
            elif isinstance(rows, dict):
                fields = _render_mapping_fields(
                    rows,
                    tuple(str(key) for key in list(rows.keys())[:8]),
                )
                if fields:
                    rendered.append("; ".join(fields))
            if rendered:
                lines.append(f"- {table_key}: " + " | ".join(rendered))

    limitations = evidence.get("limitations")
    if isinstance(limitations, list) and limitations:
        lines.append("- limitations: " + "; ".join(str(item) for item in limitations[:10]))

    return "\n".join(lines)


_NUMERIC_TOKEN_RE = re.compile(r"(?<![\w.])-?\$?\d[\d,]*(?:\.\d+)?%?(?![\w.])")


def _numeric_candidates(text: str) -> list[float]:
    values: list[float] = []
    for match in _NUMERIC_TOKEN_RE.finditer(text):
        token = match.group(0).replace("$", "").replace(",", "").replace("%", "")
        try:
            values.append(float(token))
        except ValueError:
            continue
    return values


def _contains_numeric_fact_value(text: str, fact: dict[str, Any]) -> bool:
    display = str(fact.get("display_value") or "").strip()
    if display:
        if display in text:
            return True
        without_currency = display.replace("$", "").strip()
        if without_currency and without_currency in text:
            return True

    try:
        raw_value = float(fact.get("raw_value"))
    except (TypeError, ValueError):
        return False
    try:
        tolerance = abs(float(fact.get("tolerance", 0)))
    except (TypeError, ValueError):
        tolerance = 0.0
    return any(abs(candidate - raw_value) <= tolerance for candidate in _numeric_candidates(text))


def _metric_markers_for_fact(fact: dict[str, Any]) -> tuple[str, ...]:
    metric = str(fact.get("metric") or "").lower()
    label = str(fact.get("label") or "").lower()
    marker_map = {
        "revenue_b": ("revenue", "sales", "growth narrative"),
        "net_income_b": ("net income", "profit", "earnings"),
        "net_margin_pct": ("margin", "profitability"),
        "gross_margin_pct": ("gross margin", "margin"),
        "operating_margin_pct": ("operating margin", "margin"),
        "operating_cash_flow_b": ("cash flow", "cash-flow"),
        "free_cash_flow_b": ("free cash flow", "cash-flow"),
        "cash_and_securities_b": ("balance sheet", "cash", "liquidity"),
        "long_term_debt_b": ("balance sheet", "debt", "leverage"),
        "diluted_eps": ("eps", "earnings per share"),
    }
    markers = list(marker_map.get(metric, ()))
    markers.extend(token for token in re.split(r"[^a-z0-9]+", metric) if len(token) > 2)
    markers.extend(token for token in re.split(r"[^a-z0-9]+", label) if len(token) > 2)
    return tuple(dict.fromkeys(markers))


def _numeric_fact_validation_blockers(
    summary: dict[str, Any], markdown: str, original_query: str
) -> list[str]:
    facts = _numeric_facts_from_summary(summary)
    if not facts:
        return []

    query_and_markdown = f"{original_query}\n{markdown}".lower()
    missing: list[str] = []
    contradictions: list[str] = []
    semantic_misuse: list[str] = []
    markdown_lower = markdown.lower()
    for fact in facts:
        subject = str(fact.get("subject") or "").strip()
        metric = str(fact.get("metric") or fact.get("id") or fact.get("source_key") or "").strip()
        if subject and subject.lower() not in markdown_lower:
            continue
        markers = _metric_markers_for_fact(fact)
        if markers and not any(marker in query_and_markdown for marker in markers):
            continue
        label = " ".join(part for part in (subject, metric) if part)
        label = label or str(
            fact.get("label") or fact.get("id") or fact.get("source_key") or "numeric fact"
        )
        if numeric_fact_current_state_duration_misuse(markdown, fact):
            semantic_misuse.append(label)
            continue
        if not numeric_fact_literal_required(fact):
            continue
        if numeric_fact_conflicting_current_value_contexts(markdown, fact):
            contradictions.append(label)
            continue
        if not _contains_numeric_fact_value(markdown, fact):
            missing.append(label)

    if semantic_misuse:
        return [
            "Report treats current-state zero-duration numeric_facts as historical "
            f"durations for {', '.join(semantic_misuse[:8])}. Regenerate the "
            "affected prose from state_description instead of saying an episode "
            "lasted 0 days/weeks/months."
        ]
    if contradictions:
        return [
            "Report contradicts helper-produced chart-latest numeric_facts for "
            f"{', '.join(contradictions[:8])}. Regenerate current-value prose "
            "from the execution_summary display_value fields."
        ]
    if not missing:
        return []
    return [
        "Report omits or contradicts helper-produced numeric_facts for "
        f"{', '.join(missing[:8])}. Regenerate the relevant section from "
        "the execution_summary display_value fields."
    ]


def _compact_feature_acceptance_payload(parsed: dict) -> str | None:
    """Summarize the full-research acceptance artifacts without long histories."""
    parts: list[str] = []

    latest_yoy = parsed.get("latest_yoy")
    if isinstance(latest_yoy, dict) and latest_yoy:
        values = [
            f"{key}={_fmt_summary_number(value)}"
            for key, value in latest_yoy.items()
            if _fmt_summary_number(value) is not None
        ]
        if values:
            parts.append(
                "Exact latest consumer, labor, inflation, and income values from execution_summary.json. "
                "Use these values as controlling facts; do not claim uncomputed YoY values or signs:\n"
                + "- latest_yoy: "
                + "; ".join(values)
            )

    scenarios_active = parsed.get("scenarios_active")
    if isinstance(scenarios_active, dict) and scenarios_active:
        parts.append(
            "Exact current scenario trigger status from execution_summary.json. "
            "These are boolean trigger states, not probabilities:\n"
            + "- "
            + "; ".join(f"{key}={str(value).lower()}" for key, value in scenarios_active.items())
        )

    consumer = parsed.get("consumer_stress")
    if isinstance(consumer, dict):
        lines = []
        for key in ("real_ahe_yoy_pct", "saving_rate", "delinquency_rate"):
            if consumer.get(key) is not None:
                lines.append(f"- {key}: {_fmt_summary_number(consumer.get(key))}")
        regional = consumer.get("regional_context")
        if isinstance(regional, dict):
            if regional.get("weighted_national_median") is not None:
                lines.append(
                    "- weighted_national_median_income: "
                    + str(_fmt_summary_number(regional.get("weighted_national_median")))
                )
            states = regional.get("top_states")
            if isinstance(states, list) and states:
                state_lines = []
                for row in states[:8]:
                    if not isinstance(row, dict):
                        continue
                    state = row.get("state")
                    if not state:
                        continue
                    fields = []
                    for key in ("population", "median_income"):
                        if row.get(key) is not None:
                            fields.append(f"{key}={_fmt_summary_number(row.get(key))}")
                    if fields:
                        state_lines.append(f"{state}: " + ", ".join(fields))
                if state_lines:
                    lines.append("- top_states: " + " | ".join(state_lines))
        if lines:
            parts.append(
                "Exact consumer-stress and regional values from execution_summary.json:\n"
                + "\n".join(lines)
            )

    state_comparison = parsed.get("state_comparison")
    if isinstance(state_comparison, list) and state_comparison:
        lines = []
        for row in state_comparison[:10]:
            if not isinstance(row, dict):
                continue
            state = row.get("state") or row.get("name")
            if not state:
                continue
            fields = []
            for key in ("pop", "population", "income", "median_income", "med_inc", "med_home"):
                if row.get(key) is not None:
                    fields.append(f"{key}={_fmt_summary_number(row.get(key))}")
            if fields:
                lines.append(f"- {state}: " + ", ".join(fields))
        if lines:
            parts.append(
                "Exact state comparison values from execution_summary.json. "
                "Use these state income/population values as controlling facts; "
                "do not add home values, rent-burden estimates, or national medians "
                "unless they also appear in execution_summary.json:\n"
                + "\n".join(lines)
            )

    worldbank = parsed.get("worldbank_peers")
    if isinstance(worldbank, dict):
        rows = worldbank.get("data")
        if isinstance(rows, dict) and rows:
            lines = []
            if worldbank.get("year") is not None:
                lines.append(f"- latest_year: {worldbank.get('year')}")
            for country, values in list(rows.items())[:8]:
                if not isinstance(values, dict):
                    continue
                fields = []
                for key in ("gdp_growth", "cpi", "inflation"):
                    if values.get(key) is not None:
                        fields.append(f"{key}={_fmt_summary_number(values.get(key))}")
                if fields:
                    lines.append(f"- {country}: " + ", ".join(fields))
            if lines:
                parts.append(
                    "Exact World Bank peer comparison from execution_summary.json:\n"
                    + "\n".join(lines)
                )

    intl = parsed.get("international_comparison")
    if isinstance(intl, dict):
        rows = intl.get("table")
        if isinstance(rows, list) and rows:
            lines = []
            if intl.get("latest_year") is not None:
                lines.append(f"- latest_year: {intl.get('latest_year')}")
            for row in rows[:8]:
                if not isinstance(row, dict):
                    continue
                country = row.get("country")
                if not country:
                    continue
                fields = []
                for key in ("gdp_growth", "inflation"):
                    if row.get(key) is not None:
                        fields.append(f"{key}={_fmt_summary_number(row.get(key))}")
                if fields:
                    lines.append(f"- {country}: " + ", ".join(fields))
            if lines:
                parts.append(
                    "Exact international peer comparison from execution_summary.json:\n"
                    + "\n".join(lines)
                )

    downturn = parsed.get("prior_downturn_comparison")
    if isinstance(downturn, dict):
        lines = []
        current = downturn.get("current")
        if isinstance(current, dict):
            fields = [
                f"{key}={_fmt_summary_number(value)}"
                for key, value in current.items()
                if _fmt_summary_number(value) is not None
            ]
            if fields:
                lines.append("- current: " + "; ".join(fields))
        if downturn.get("assessment"):
            lines.append("- assessment: " + str(downturn.get("assessment")))
        if lines:
            parts.append(
                "Exact prior-downturn comparison anchors from execution_summary.json:\n"
                + "\n".join(lines)
            )

    return "\n\n".join(parts) if parts else None


def _compact_validation_and_simulation_payload(parsed: dict) -> str | None:
    """Render reusable validation and historical replay rows for report drafting."""

    lines: list[str] = []

    def _append_row_group(label: str, rows: object, *, limit: int = 10) -> None:
        if not isinstance(rows, list) or not rows:
            return
        rendered: list[str] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            fields = []
            for key, value in list(row.items())[:12]:
                if value is None or isinstance(value, (dict, list)):
                    continue
                formatted = _fmt_summary_number(value)
                fields.append(f"{key}={formatted if formatted is not None else value}")
            if fields:
                rendered.append("; ".join(fields))
        if rendered:
            lines.append(f"- {label}: " + " | ".join(rendered))

    def _append_mapping(label: str, value: object, *, limit: int = 12) -> None:
        if not isinstance(value, dict) or not value:
            return
        fields = []
        for key, item in list(value.items())[:limit]:
            if isinstance(item, dict):
                nested = []
                for nested_key, nested_value in list(item.items())[:limit]:
                    formatted = _fmt_summary_number(nested_value)
                    if formatted is None:
                        if nested_value is None:
                            nested.append(f"{nested_key}=null")
                        elif not isinstance(nested_value, (dict, list)):
                            nested.append(f"{nested_key}={nested_value}")
                    else:
                        nested.append(f"{nested_key}={formatted}")
                if nested:
                    lines.append(f"- {label}.{key}: " + "; ".join(nested))
                continue
            if isinstance(item, list):
                continue
            formatted = _fmt_summary_number(item)
            fields.append(f"{key}={formatted if formatted is not None else item}")
        if fields:
            lines.append(f"- {label}: " + "; ".join(fields))

    for key in (
        "walk_forward_backtest_rows",
        "model_validation_rows",
        "model_comparison_by_horizon",
        "model_comparison_rows",
        "historical_failure_episodes",
        "signal_event_rows",
        "signal_false_positive_windows",
        "replay_rows",
    ):
        _append_row_group(key, parsed.get(key))

    for key in (
        "event_backtest_metrics",
        "signal_validation_metrics",
        "validation_diagnostics",
    ):
        _append_mapping(key, parsed.get(key))

    diagnostics = parsed.get("diagnostics")
    if isinstance(diagnostics, dict):
        for key, value in list(diagnostics.items())[:12]:
            _append_mapping(f"diagnostics.{key}", value)

    if not lines:
        return None
    return (
        "Reusable validation and simulation evidence from execution_summary.json:\n"
        + "\n".join(lines)
    )


def _compact_execution_summary_payload(
    parsed: dict,
    *,
    original_query: str = "",
) -> str:
    parts: list[str] = []
    compact_limit = 4000
    stats = parsed.get("statistical_summary")
    stats_payload = stats if isinstance(stats, dict) else {}

    source_unit_summary = _compact_source_unit_payload(parsed)
    if source_unit_summary:
        parts.append(source_unit_summary)
        compact_limit = max(compact_limit, 8000)

    helper_evidence_summary = _compact_helper_evidence_payload(
        parsed,
        original_query=original_query,
    )
    if helper_evidence_summary:
        parts.append(helper_evidence_summary)
        compact_limit = max(compact_limit, 9000)

    acceptance_summary = _compact_feature_acceptance_payload(parsed)
    if acceptance_summary:
        parts.append(acceptance_summary)
        compact_limit = max(compact_limit, 8000)

    validation_summary = _compact_validation_and_simulation_payload(parsed)
    if validation_summary:
        parts.append(validation_summary)
        compact_limit = max(compact_limit, 8000)

    macro_evidence_summary = _compact_macro_evidence_payload(parsed)
    if macro_evidence_summary:
        parts.append(macro_evidence_summary)
        compact_limit = max(compact_limit, 8000)

    scalar_summary = _compact_headline_scalar_metrics(parsed)
    if scalar_summary:
        parts.append(scalar_summary)

    shallow_stats_summary = _compact_shallow_statistical_summary(stats_payload)
    if shallow_stats_summary:
        parts.append(shallow_stats_summary)

    by_year_summary = _compact_by_year_payload(parsed)
    if by_year_summary:
        parts.append(by_year_summary)

    top_level_summary_stats = _compact_top_level_metric_table(
        parsed,
        "summary_stats",
        "Exact summary statistics from execution_summary.json",
    )
    if top_level_summary_stats:
        parts.append(top_level_summary_stats)

    top_level_correlations = _compact_top_level_metric_table(
        parsed,
        "correlations",
        "Exact correlations from execution_summary.json",
    )
    if top_level_correlations:
        parts.append(top_level_correlations)

    descriptive_stats = stats_payload.get("descriptive_stats")
    if isinstance(descriptive_stats, dict) and descriptive_stats:
        lines = []
        for series, row in list(descriptive_stats.items())[:12]:
            if not isinstance(row, dict):
                continue
            fields = []
            for key in ("latest", "mean", "std", "min", "max"):
                if row.get(key) is not None:
                    fields.append(f"{key}={row.get(key)}")
            if fields:
                lines.append(f"- {series}: " + ", ".join(fields))
        if lines:
            parts.append("Descriptive statistics from execution_summary.json:\n" + "\n".join(lines))

    rolling = stats_payload.get("rolling_correlations_latest")
    if isinstance(rolling, dict) and rolling:
        lines = [f"- {key}: {value}" for key, value in rolling.items() if value is not None]
        if lines:
            parts.append("Latest rolling correlations from execution_summary.json:\n" + "\n".join(lines))

    lead_correlations = stats_payload.get("lead_correlations")
    if isinstance(lead_correlations, dict) and lead_correlations:
        lines = []
        for name, row in lead_correlations.items():
            if not isinstance(row, dict):
                continue
            fields = []
            if row.get("r") is not None:
                fields.append(f"r={row.get('r')}")
            if row.get("p_value") is not None:
                fields.append(f"p_value={row.get('p_value')}")
            if fields:
                lines.append(f"- {name}: " + ", ".join(fields))
        if lines:
            parts.append("Fixed-horizon lead correlations from execution_summary.json:\n" + "\n".join(lines))

    cross_corr_peaks = stats_payload.get("cross_correlation_peak_lags")
    if isinstance(cross_corr_peaks, dict) and cross_corr_peaks:
        lines = []
        for target, row in cross_corr_peaks.items():
            if not isinstance(row, dict):
                continue
            fields = []
            lag = row.get("peak_lag_months")
            corr = row.get("peak_r")
            if lag is not None:
                fields.append(f"peak_lag_months={lag}")
            if corr is not None:
                fields.append(f"peak_r={corr}")
            if fields:
                lines.append(f"- {target}: " + ", ".join(fields))
        if lines:
            parts.append(
                "Exact cross-correlation peak lags from execution_summary.json. "
                "Preserve the sign convention exactly as reported; do not flip signs in prose:\n"
                + "\n".join(lines)
            )

    recession_summaries = stats_payload.get("recession_summaries")
    if isinstance(recession_summaries, list) and recession_summaries:
        lines = []
        for row in recession_summaries[:8]:
            if not isinstance(row, dict):
                continue
            start = row.get("recession_start")
            end = row.get("recession_end")
            if not start:
                continue
            fields = []
            for key in (
                "duration_months",
                "avg_spread_12m_before",
                "min_spread_12m_before",
                "spread_inverted_before",
                "lead_time_months_from_first_inversion",
                "unr_change_during_recession",
                "indpro_yoy_avg_during",
            ):
                if row.get(key) is not None:
                    fields.append(f"{key}={row.get(key)}")
            label = f"{start} to {end}" if end else str(start)
            if fields:
                lines.append(f"- {label}: " + ", ".join(fields))
        if lines:
            parts.append("Recession-window summaries from execution_summary.json:\n" + "\n".join(lines))

    key_points = parsed.get("key_narrative_points")
    if isinstance(key_points, list) and key_points:
        points = [str(point).strip() for point in key_points[:12] if str(point).strip()]
        if points:
            parts.append("Key computed findings from execution_summary.json:\n" + "\n".join(f"- {point}" for point in points))

    macro_stats = parsed.get("macro_series_stats")
    if isinstance(macro_stats, list) and macro_stats:
        lines = []
        for row in macro_stats[:10]:
            if not isinstance(row, dict):
                continue
            series = row.get("series")
            latest = row.get("latest")
            mean = row.get("mean")
            signal = row.get("stress_signal")
            fields = []
            if latest is not None:
                fields.append(f"latest={latest}")
            if mean is not None:
                fields.append(f"mean={mean}")
            if signal is not None:
                fields.append(f"signal={signal}")
            if series and fields:
                lines.append(f"- {series}: " + ", ".join(fields))
        if lines:
            parts.append("Macro indicator stats:\n" + "\n".join(lines))

    regional_top10 = parsed.get("regional_top10")
    if isinstance(regional_top10, list) and regional_top10:
        lines = []
        for row in regional_top10[:10]:
            if not isinstance(row, dict):
                continue
            state = row.get("state") or row.get("state_name")
            fields = []
            if row.get("pop") is not None:
                fields.append(f"population={row.get('pop')}")
            if row.get("med_inc") is not None:
                fields.append(f"median_income={row.get('med_inc')}")
            if row.get("pct_nat") is not None:
                fields.append(f"pct_of_national_median={row.get('pct_nat')}%")
            if state and fields:
                lines.append(f"- {state}: " + ", ".join(fields))
        if lines:
            parts.append(
                "Exact regional state consumer context from execution_summary.json. "
                "Copy these state names, median incomes, and national-ratio percentages exactly; "
                "do not estimate or round them differently:\n"
                + "\n".join(lines)
            )

    affordability = parsed.get("state_housing_affordability")
    if isinstance(affordability, dict):
        lines = []
        for key, label in (
            ("top5_most_stressed_low_income_to_value", "Most stressed states"),
            ("bottom5_least_stressed_high_income_to_value", "Least stressed states"),
            ("top5_highest_valuation_multiple", "Highest home-value/income multiples"),
        ):
            rows = affordability.get(key)
            if not isinstance(rows, list) or not rows:
                continue
            summaries = []
            for row in rows[:5]:
                if not isinstance(row, dict):
                    continue
                state = row.get("state_name") or row.get("state")
                ratio = row.get("income_to_value_ratio")
                multiple = row.get("value_to_income_multiple")
                if state and ratio is not None:
                    summaries.append(f"{state} income/value={ratio}")
                elif state and multiple is not None:
                    summaries.append(f"{state} value/income={multiple}")
            if summaries:
                lines.append(f"- {label}: " + "; ".join(summaries))
        for key, label in (
            ("national_median_income_to_value_ratio", "national median income/value"),
            ("national_median_value_to_income_multiple", "national median value/income"),
        ):
            if affordability.get(key) is not None:
                lines.append(f"- {label}: {affordability[key]}")
        if lines:
            parts.append("State-level affordability context:\n" + "\n".join(lines))

    correlations = parsed.get("correlation_matrix")
    if isinstance(correlations, dict):
        notable = correlations.get("notable_correlations")
        if isinstance(notable, list) and notable:
            items = [str(item).strip() for item in notable[:10] if str(item).strip()]
            if items:
                parts.append("Notable correlations:\n" + "\n".join(f"- {item}" for item in items))

    contractions = parsed.get("real_income_contractions")
    if isinstance(contractions, dict):
        lines = []
        if contractions.get("count") is not None:
            lines.append(f"- count: {contractions['count']}")
        if isinstance(contractions.get("note"), str) and contractions["note"].strip():
            lines.append(f"- note: {contractions['note'].strip()}")
        periods = contractions.get("periods")
        if isinstance(periods, list) and periods:
            examples = []
            for row in periods[:5]:
                if isinstance(row, dict):
                    date = row.get("date")
                    value = row.get("DSPIC96_YoY") or row.get("value")
                    if date is not None and value is not None:
                        examples.append(f"{date}: {value}")
            if examples:
                lines.append("- first examples: " + "; ".join(examples))
        if lines:
            parts.append("Real income contraction periods:\n" + "\n".join(lines))

    lead_lag = parsed.get("lead_lag_analysis")
    if isinstance(lead_lag, dict):
        metric_lines = []
        for target, result in lead_lag.items():
            if not isinstance(result, dict):
                continue
            fields = []
            for source_key, label in (
                ("best_lag", "best_lag_months"),
                ("best_correlation", "best_correlation"),
                ("best_p_value", "best_p_value"),
                ("best_nobs", "best_nobs"),
                ("significant_lags_count", "significant_lags_count"),
            ):
                value = result.get(source_key)
                if value is not None:
                    fields.append(f"{label}={value}")
            if fields:
                metric_lines.append(f"- {target}: " + ", ".join(fields))
        if metric_lines:
            parts.append(
                "Exact lead-lag metrics from execution_summary.json. Use these exact signs and values; "
                "negative best_lag_months means the predictor leads the target:\n"
                + "\n".join(metric_lines)
            )

    summary = parsed.get("statistical_summary")
    if isinstance(summary, str) and summary.strip():
        parts.append(summary.strip())

    caveats = parsed.get("caveats")
    if isinstance(caveats, dict) and caveats:
        caveat_text = "; ".join(f"{k}: {v}" for k, v in caveats.items())
        parts.append("Method caveats: " + caveat_text)
    elif isinstance(caveats, list) and caveats:
        caveat_items = [str(item).strip() for item in caveats[:10] if str(item).strip()]
        if caveat_items:
            parts.append("Method caveats:\n" + "\n".join(f"- {item}" for item in caveat_items))

    methods = parsed.get("methods_used")
    if isinstance(methods, list) and methods:
        parts.append("Methods used: " + ", ".join(str(method) for method in methods))

    if parts:
        return "\n\n".join(parts)[:compact_limit]
    return json.dumps(parsed, ensure_ascii=False)[:4000]


@tool
def plan_report_structure(
    query_type: str,
    charts_json_path: str,
    execution_summary: str,
    original_query: str,
    runtime: ToolRuntime[ResearchContext],
) -> str:
    """
    Plan the report structure by reading charts.json from disk.

    Call this FIRST before writing the report. Reads the charts.json file
    produced by the quant developer to discover available chart IDs, then
    returns a section outline with chart placement.

    Args:
        query_type: One of: "correlation_analysis", "trend_analysis",
                    "sector_comparison", "macro_indicator",
                    "earnings_analysis", "custom"
        charts_json_path: Path to the charts.json file on disk
                          (e.g. "outputs/abc123/charts.json")
        execution_summary: Compact JSON string printed to stdout by the quant
                           developer, or a job-local execution_summary.json path.
        original_query: The user's original research question

    Returns:
        JSON string with:
        - general_rules: High-level instructions on how to structure the report
        - query_type: Echoed back
        - chart_ids: List of chart IDs discovered from charts.json
        - recommended_word_count: Target word count for the report
        - charts_json_path: Resolved absolute path to charts.json (pass unchanged to `write_research_report`)
        - chart_facts_for_draft: Compact chart type, axis, series, and node facts from charts.json
        - execution_summary_for_draft: Writer-useful computed findings extracted from inline JSON or a job-local summary file
        - original_query: Echo of `original_query` (pass unchanged to `write_research_report`)
    """
    runtime_query = _runtime_original_query(runtime)
    original_query = runtime_query or normalize_query_text(original_query)
    charts_json_path = _resolve_charts_json_path(runtime, charts_json_path)
    execution_payload = _execution_summary_payload(runtime, execution_summary)
    helper_evidence_for_draft = _helper_evidence_for_draft(
        execution_payload,
        original_query=original_query,
    )
    _save_plan_context(
        runtime,
        charts_json_path=charts_json_path,
        original_query=original_query,
        helper_evidence=helper_evidence_for_draft or None,
    )

    # Load chart IDs from disk — never from caller context
    chart_ids: list[str] = []
    chart_facts_for_draft = ""
    try:
        raw = Path(charts_json_path).read_text(encoding="utf-8")
        charts_data = json.loads(raw)
        charts_map = _chart_map_from_parsed_json(charts_data)
        chart_ids = list(charts_map.keys())
        chart_facts_for_draft = _compact_chart_facts_for_draft(charts_map)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        chart_ids = []

    is_macro = _is_macro_report(query_type, original_query)

    if is_macro:
        general_rules = (
            "You are writing a Macro Report. Structure the report as you see fit using your own headings and subheadings. "
            "However, you MUST start with an 'Executive Summary' (Macro View and Key Findings). "
            "Following that, weave your analysis covering the macro environment, policy context, indicator analysis, "
            "market implications, and structural risks. "
            "Near the bottom, include `## Research Query` (restating the original question). "
            "Do not write a disclaimer block — the system appends a standard legal footer on save. "
            "CRITICAL: You MUST include every chart from the `chart_ids` list in your markdown using the syntax `<!-- CHART:id -->`. "
            "Use ONLY those exact chart IDs; never invent chart markers for requested-but-unavailable visuals. "
            "Place each chart marker immediately after the paragraph that discusses its data. "
            "Use `chart_facts_for_draft` as the controlling chart contract; do not describe chart series, overlays, reference bands, rankings, nodes, or fields that are absent from those facts."
        )
    else:
        general_rules = (
            "You are writing an Equity Report. Structure the report as you see fit using your own headings and subheadings. "
            "However, you MUST start with an 'Executive Summary' (The 'Call', Price Target Implications, and Key Findings). "
            "Following that, weave your analysis covering the investment thesis, catalysts, financial analysis, "
            "valuation, and investment risks. "
            "Near the bottom, include `## Research Query` (restating the original question). "
            "Do not write a disclaimer block — the system appends a standard legal footer on save. "
            "CRITICAL: You MUST include every chart from the `chart_ids` list in your markdown using the syntax `<!-- CHART:id -->`. "
            "Use ONLY those exact chart IDs; never invent chart markers for requested-but-unavailable visuals. "
            "Place each chart marker immediately after the paragraph that discusses its data. "
            "Use `chart_facts_for_draft` as the controlling chart contract; do not describe chart series, overlays, reference bands, rankings, nodes, or fields that are absent from those facts."
        )

    execution_summary_for_draft = _compact_execution_summary(
        runtime,
        execution_summary,
        original_query=original_query,
    )
    if chart_facts_for_draft:
        execution_summary_for_draft = (
            chart_facts_for_draft
            if not execution_summary_for_draft
            else chart_facts_for_draft + "\n\n" + execution_summary_for_draft
        )
    if (
        len(execution_summary_for_draft) > 4000
        and not helper_evidence_for_draft
    ):
        execution_summary_for_draft = execution_summary_for_draft[:4000]

    return json.dumps(
        {
            "general_rules": general_rules,
            "query_type": query_type,
            "chart_ids": chart_ids,
            "recommended_word_count": "1000+ words",
            "charts_json_path": charts_json_path,
            "chart_facts_for_draft": chart_facts_for_draft,
            "execution_summary_for_draft": execution_summary_for_draft,
            "helper_evidence_for_draft": helper_evidence_for_draft,
            "original_query": original_query,
            "echo_for_write_research_report": (
                "Pass `charts_json_path` and `original_query` into `write_research_report` "
                "exactly as given in this JSON (same strings)."
            ),
        }
    )


@tool
def write_research_report(
    runtime: ToolRuntime[ResearchContext],
    markdown: str,
    charts_json_path: str = "",
    data_sources: str = "[]",
    original_query: str = "",
    title: str = "",
    executive_summary: str = "",
    analysis_type: str = "custom",
    execution_summary: str = "",
) -> str:
    """
    Validate and save the LLM-written markdown narrative as report.json.

    YOU write the complete markdown narrative yourself before calling this tool.
    This tool only: reads charts.json from disk, embeds chart definitions into
    the report, validates mandatory elements, and saves report.json.

    Args:
        runtime: Injected by the agent runtime (not passed by the model).
        markdown: The COMPLETE markdown narrative you have written. Must include:
                  - ## Executive Summary (at the top, 2-3 sentences with specific numbers)
                  - Your own analysis sections with custom headings and subheadings
                  - <!-- CHART:id --> markers placed inline after the text that
                    references each chart (NOT clustered at the bottom)
                  - ## Research Query (verbatim original query, near the bottom)
                  - Do not add a disclaimer section (injected automatically on save)
        charts_json_path: Path to charts.json on disk (e.g. "outputs/abc123/charts.json")
        data_sources: JSON string containing DataSource dicts with small metadata only
                      (provider, description, tickers/series_ids, date_range, row_count)
        original_query: The user's original research question
        title: Descriptive report title (derived from query + key finding)
        executive_summary: 2-3 sentence plain-text summary (same content as the
                           ## Executive Summary section in markdown)
        analysis_type: One of: "correlation_analysis", "trend_analysis",
                       "sector_comparison", "macro_indicator",
                       "earnings_analysis", "custom"
        execution_summary: Optional inline JSON or job-local execution_summary.json path.
            Used for validation against helper-produced numeric facts and
            reusable evidence rows.

    Returns:
        JSON string with:
        - report_path: Absolute path where report.json was saved
        - chart_count: Number of <!-- CHART:id --> markers found in markdown
        - word_count: Approximate word count of markdown
        - validation_issues: List of non-blocking warnings (may be empty)
    """
    canonical_job_id = runtime.context.job_id
    out_dir = runtime.context.output_dir
    if not out_dir:
        out_dir = str(OUTPUT_BASE_DIR / canonical_job_id)
    report_path = str((Path(out_dir) / "report.json").resolve())
    plan_context = _load_plan_context(runtime)
    runtime_query = _runtime_original_query(runtime)
    supplied_query = normalize_query_text(original_query)
    markdown_query = normalize_query_text(_extract_research_query_from_markdown(markdown))
    if runtime_query:
        if supplied_query and supplied_query != runtime_query:
            return _original_query_mismatch_response(
                report_path=report_path,
                candidate_query=supplied_query,
                expected_query=runtime_query,
                source="supplied original_query",
            )
        if markdown_query and markdown_query != runtime_query:
            return _original_query_mismatch_response(
                report_path=report_path,
                candidate_query=markdown_query,
                expected_query=runtime_query,
                source="markdown Research Query section",
            )
        original_query = runtime_query
    if not str(charts_json_path).strip():
        charts_json_path = plan_context.get("charts_json_path", "")
    if not str(charts_json_path).strip():
        return json.dumps(
            {
                "status": "error",
                "error": (
                    "charts_json_path is required. Copy the resolved `charts_json_path` string "
                    "from the `plan_report_structure` tool result into this call unchanged."
                ),
            }
        )
    if not runtime_query and not supplied_query:
        original_query = markdown_query
    if not str(original_query).strip():
        original_query = plan_context.get("original_query", "")
    original_query = normalize_query_text(original_query)
    if not str(original_query).strip():
        return json.dumps(
            {
                "status": "error",
                "error": (
                    "original_query is required. Copy the `original_query` string from the "
                    "`plan_report_structure` tool result into this call unchanged."
                ),
            }
        )

    charts_json_path = _resolve_charts_json_path(runtime, charts_json_path)

    # Normalise data_sources — may arrive as JSON string or a single dict instead of list
    if isinstance(data_sources, str):
        try:
            data_sources = json.loads(data_sources)
        except (json.JSONDecodeError, TypeError):
            data_sources = []
    if isinstance(data_sources, dict):
        data_sources = [data_sources]
    if not isinstance(data_sources, list):
        data_sources = []

    # -------------------------------------------------------------------------
    # 1. Read full chart definitions from disk
    # -------------------------------------------------------------------------
    charts_on_disk: dict = {}
    try:
        raw_charts = Path(charts_json_path).read_text(encoding="utf-8")
        parsed = json.loads(raw_charts)
        charts_on_disk = _chart_map_from_parsed_json(parsed)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        charts_on_disk = {}

    charts_on_disk = _normalize_chart_definitions(charts_on_disk)

    # -------------------------------------------------------------------------
    # 3. Build DataSource objects
    # -------------------------------------------------------------------------
    ds_objects: list[DataSource] = []
    for ds in data_sources:
        try:
            ds_objects.append(DataSource(**ds))
        except Exception:
            ds_objects.append(
                DataSource(
                    provider=ds.get("provider", "Unknown"), description=ds.get("description", "")
                )
            )

    # -------------------------------------------------------------------------
    # 4. Derive title and executive_summary from markdown if not supplied
    # -------------------------------------------------------------------------
    if not title.strip():
        title = original_query[:80].strip()

    if not executive_summary.strip():
        lines = markdown.splitlines()
        in_exec = False
        for line in lines:
            if line.strip().lower().startswith("## executive summary"):
                in_exec = True
                continue
            if in_exec:
                if line.startswith("##"):
                    break
                if line.strip():
                    executive_summary = line.strip()
                    break
        if not executive_summary.strip():
            executive_summary = f"Analysis of: {original_query}"

    execution_payload = _execution_summary_payload(runtime, execution_summary)
    if plan_context.get("helper_evidence"):
        execution_payload = dict(execution_payload)
        helper_evidence = plan_context.get("helper_evidence")
        if isinstance(helper_evidence, dict):
            for key in (
                "numeric_facts",
                "requested_geography_coverage",
                "requested_subject_evidence",
                "source_coverage",
                "methods_used",
                "chart_ids",
                "limitations",
                "source_unit_metadata",
                "unit_comparisons",
                "source_unit_errors",
                "current_signal_facts",
            ):
                if helper_evidence.get(key):
                    execution_payload.setdefault(key, helper_evidence[key])
            for key, value in (helper_evidence.get("tables") or {}).items():
                execution_payload.setdefault(key, value)
            for key, value in (helper_evidence.get("diagnostics") or {}).items():
                execution_payload.setdefault(key, value)
    requested_geography_blocker = requested_geography_coverage_blocker(
        original_query,
        execution_payload,
    )
    if requested_geography_blocker:
        return json.dumps(
            {
                "status": "error",
                "error": "requested_coverage_missing",
                "failure_category": "requested_coverage_missing",
                "required_upstream": "quant-developer",
                "report_path": report_path,
                "blockers": [requested_geography_blocker],
                "message": requested_geography_blocker,
            }
        )
    requested_subject_blocker = requested_subject_evidence_report_blocker(
        original_query,
        execution_payload,
        "\n".join([title, executive_summary, markdown]),
    )
    if requested_subject_blocker:
        subject_assessment = assess_requested_subject_evidence(
            original_query,
            execution_payload,
        )
        return json.dumps(
            {
                "status": "error",
                "error": "requested_coverage_missing",
                "failure_category": "requested_coverage_missing",
                "required_upstream": (
                    "quant-developer"
                    if subject_assessment.status == "missing"
                    else "technical-writer"
                ),
                "report_path": report_path,
                "blockers": [requested_subject_blocker],
                "message": requested_subject_blocker,
            }
        )
    artifact_fact_consistency = artifact_fact_consistency_dict(
        execution_summary=execution_payload,
        charts=charts_on_disk,
    )
    artifact_fact_blocker = artifact_fact_consistency_blocker(artifact_fact_consistency)
    if artifact_fact_blocker:
        return json.dumps(
            {
                "status": "error",
                "error": "artifact_fact_mismatch",
                "failure_category": "artifact_fact_mismatch",
                "required_upstream": "quant-developer",
                "report_path": report_path,
                "artifact_fact_consistency": artifact_fact_consistency,
                "blockers": [artifact_fact_blocker],
                "message": artifact_fact_blocker,
            }
        )
    numeric_fact_blockers = _numeric_fact_validation_blockers(
        execution_payload, markdown, original_query
    )
    if numeric_fact_blockers:
        return json.dumps(
            {
                "status": "error",
                "error": "numeric_fact_mismatch",
                "failure_category": "numeric_fact_mismatch",
                "required_upstream": "technical-writer",
                "report_path": report_path,
                "blockers": numeric_fact_blockers,
                "message": numeric_fact_blockers[0],
            }
        )

    # -------------------------------------------------------------------------
    # 5. Assemble and validate ResearchReport (Pydantic validates chart shapes)
    # -------------------------------------------------------------------------
    chart_ids_in_markdown = chart_marker_ids(markdown)
    metadata = ReportMetadata(
        analysis_type=analysis_type,
        chart_count=len(chart_ids_in_markdown),
        word_count=len(markdown.split()),
    )

    report = ResearchReport(
        schema_version=1,
        job_id=canonical_job_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        query=original_query,
        title=title,
        executive_summary=executive_summary,
        markdown=markdown,
        charts=charts_on_disk,
        data_sources=ds_objects,
        metadata=metadata,
    )

    # -------------------------------------------------------------------------
    # 6. Save to disk with pre-write validation
    # -------------------------------------------------------------------------
    chart_handoff = chart_handoff_dict(report.model_dump(), execution_payload)
    handoff_blocker = chart_handoff_blocker(chart_handoff)
    if handoff_blocker and chart_handoff.get("missing_report_chart_ids"):
        return json.dumps(
            {
                "status": "error",
                "error": "chart_handoff_mismatch",
                "failure_category": "chart_handoff_mismatch",
                "required_upstream": "quant-developer",
                "report_path": report_path,
                "chart_handoff": chart_handoff,
                "blockers": [handoff_blocker],
                "message": handoff_blocker,
            }
        )
    validation_issues, report_saved = _save_report(report, report_path)

    return json.dumps(
        {
            "report_path": report_path,
            "chart_count": report_saved.metadata.chart_count,
            "word_count": report_saved.metadata.word_count,
            "validation_issues": validation_issues,
        }
    )


def _save_report(report: ResearchReport, output_path: str) -> tuple[list[str], ResearchReport]:
    """
    Inject canonical disclaimer footer, validate soft issues, and write report.json.

    Returns ``(issues, report_written)`` — ``report_written`` includes the injected footer
    and updated ``metadata.word_count``. The full static gate is ``validate_research_report_file``.
    """
    issues: list[str] = []

    new_md, _ = inject_auto_report_footer(report.markdown)
    report = report.model_copy(
        update={
            "markdown": new_md,
            "metadata": report.metadata.model_copy(
                update={"word_count": len(new_md.split())}
            ),
        }
    )

    if not report.executive_summary.strip():
        issues.append("Executive summary is empty")

    marker_ids = chart_marker_ids(report.markdown)
    for mid in marker_ids:
        if mid not in report.charts:
            issues.append(f"Chart marker <!-- CHART:{mid} --> references unknown chart ID '{mid}'")
    for chart_id in report.charts:
        if chart_id not in marker_ids:
            issues.append(
                f"Chart ID '{chart_id}' is defined in charts.json but missing a matching "
                f"<!-- CHART:{chart_id} --> marker in markdown"
            )

    try:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    except Exception as e:
        issues.append(f"Failed to write report.json: {e}")

    return issues, report


@tool
def validate_research_report_file(
    runtime: ToolRuntime[ResearchContext],
    report_json_path: str = "",
    auto_patch: bool = True,
) -> str:
    """
    Run the static report gate: Pydantic schema, chart marker resolution, chart coverage,
    chart render/data semantics, and optional safe auto-patches. Call after
    `write_research_report`.

    When `auto_patch` is True, may re-apply the canonical disclaimer footer (idempotent).
    For non-chart queries only, it may also remove broken `<!-- CHART:id -->` markers.

    `passes_gate` is false for load/schema errors, unresolved broken chart markers,
    charts defined in charts.json that are not referenced by a `<!-- CHART:id -->` marker,
    chart render/data semantics blockers, or report.query drift from the runtime user query.
    Check `warnings` for non-blocking hints (e.g. empty executive summary). Prose compliance
    is for quality-analyst review, not static regex.

    Args:
        report_json_path: Absolute path to `report.json`. If empty, uses
            `{output_dir}/report.json` from the current job context.
        auto_patch: If True, apply auto footer re-sync and chart-marker patches when applicable.

    Returns:
        JSON string with `passes_gate`, `report_path`, `format`, `charts`,
        `chart_render`, `chart_semantics`, `chart_handoff`,
        `artifact_fact_consistency`, `warnings`, `auto_patched`,
        `patches_applied`, and `blockers`.
        Revise markdown and call
        `write_research_report` again if structural `blockers` remain.
    """
    if str(report_json_path).strip():
        candidate = Path(report_json_path).expanduser().resolve()
        if candidate.is_dir():
            path = str(candidate / "report.json")
        else:
            path = str(candidate)
    else:
        out = runtime.context.output_dir
        if not out:
            return json.dumps(
                {
                    "passes_gate": False,
                    "report_path": "",
                    "load_error": "report_json_path is empty and job output_dir is not set",
                    "format": {},
                    "charts": {},
                    "warnings": [],
                    "auto_patched": False,
                    "patches_applied": [],
                    "blockers": [
                        "Set `report_json_path` to the absolute path of report.json, "
                        "or ensure the job has an output_dir."
                    ],
                }
            )
        path = str((Path(out) / "report.json").resolve())
    return run_report_static_gate(
        path,
        auto_patch=auto_patch,
        original_query=_runtime_original_query(runtime),
    )
