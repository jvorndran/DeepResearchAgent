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
from core.report_schema import DataSource, ReportMetadata, ResearchReport, ScenarioRow

from ..report_artifacts import chart_marker_ids, inject_auto_report_footer

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

_SCENARIO_QUERY_KEYWORDS = {
    "scenario",
    "scenarios",
    "stress test",
    "stress testing",
    "base case",
    "bull case",
    "bear case",
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


def _requires_scenario_table(original_query: str) -> bool:
    lowered_query = original_query.lower()
    return any(keyword in lowered_query for keyword in _SCENARIO_QUERY_KEYWORDS)


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
) -> None:
    path = _plan_context_path(runtime)
    if path is None:
        return
    payload = {
        "charts_json_path": charts_json_path,
        "original_query": original_query,
    }
    try:
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        return


def _load_plan_context(runtime: ToolRuntime[ResearchContext]) -> dict[str, str]:
    path = _plan_context_path(runtime)
    if path is None:
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        key: value.strip()
        for key in ("charts_json_path", "original_query")
        if isinstance((value := parsed.get(key)), str) and value.strip()
    }


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
                _compact_execution_summary_payload(parsed), runtime, parsed
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
            _compact_execution_summary_payload(parsed), runtime, parsed
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


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        cleaned: list[str] = []
        for item in value:
            if isinstance(item, dict):
                label = (
                    item.get("indicator_name")
                    or item.get("name")
                    or item.get("indicator")
                    or item.get("metric")
                )
                status = item.get("status")
                current = item.get("current_value")
                threshold = item.get("threshold")
                parts = [str(label).strip()] if label else []
                details = []
                if status is not None:
                    details.append(f"status={status}")
                if current is not None:
                    details.append(f"current={current}")
                if threshold is not None:
                    details.append(f"threshold={threshold}")
                if details:
                    parts.append("(" + ", ".join(details) + ")")
                text = " ".join(parts).strip() or str(item).strip()
            else:
                text = str(item).strip()
            if text:
                cleaned.append(text)
        return cleaned
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(";") if part.strip()]
    return []


def _coerce_scenario_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {"upside": "bull", "downside": "bear"}
    for alias, scenario in aliases.items():
        if text == alias or (
            text.startswith(alias)
            and len(text) > len(alias)
            and not text[len(alias)].isalnum()
        ):
            return scenario
    for scenario in ("base", "bull", "bear"):
        if text == scenario or text.startswith(f"{scenario} ") or text.startswith(f"{scenario}-"):
            return scenario
        if text.startswith(scenario) and len(text) > len(scenario) and not text[len(scenario)].isalnum():
            return scenario
    return text


def _coerce_confidence(value: Any) -> str:
    lowered = str(value or "").strip().lower()
    if "medium" in lowered:
        return "medium"
    if "moderate" in lowered or "elevated" in lowered:
        return "medium"
    if "high" in lowered:
        return "high"
    if "low" in lowered:
        return "low"
    numeric_match = re.search(r"[-+]?\d+(?:\.\d+)?\s*%?", lowered)
    numeric = numeric_match.group(0).replace("%", "").replace("~", "").strip() if numeric_match else ""
    try:
        probability = float(numeric)
    except ValueError:
        return lowered
    if "%" not in lowered and 0 <= probability <= 1:
        probability *= 100
    return _coerce_probability_confidence(probability)


def _coerce_probability_confidence(value: Any) -> str:
    try:
        probability = float(value)
    except (TypeError, ValueError):
        return "medium"
    if probability >= 65:
        return "high"
    if probability <= 25:
        return "low"
    return "medium"


def _coerce_uncertainty_notes(row: dict[str, Any]) -> str:
    for key in ("uncertainty_notes", "uncertainty", "notes"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    notes = _coerce_string_list(row.get("confidence_notes"))
    if notes:
        return "; ".join(notes)
    summary = row.get("narrative_summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return ""


def _get_case_insensitive(row: dict[str, Any], *keys: str) -> Any:
    """Fetch a dict value while tolerating title-cased compact quant payloads."""
    for key in keys:
        if key in row:
            return row[key]
    lowered = {str(key).lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is not None:
            return value
    return None


def _fallback_scenario_assumptions(row: dict[str, Any]) -> list[str]:
    excluded = {
        "scenario",
        "scenario_name",
        "assumptions",
        "key_assumptions",
        "indicator_triggers",
        "trigger_indicators",
        "triggers",
        "confidence",
        "confidence_level",
        "prob",
        "probability",
        "probability_assignment",
        "uncertainty_notes",
        "uncertainty",
        "notes",
    }
    assumptions = [
        f"{_labelize_key(str(key))}: {value}"
        for key, value in row.items()
        if str(key).lower() not in excluded and value not in (None, "")
    ]
    return assumptions or ["Scenario details were provided in compact form by the quantitative analysis."]


def _scenario_rows_from_mapping(rows: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Normalize compact quant scenario mappings into ScenarioRow-shaped dicts."""
    scenario_rows: list[dict[str, Any]] = []
    for raw_name, raw_value in rows.items():
        scenario_name = _coerce_scenario_name(raw_name)
        if scenario_name not in {"base", "bull", "bear"}:
            continue
        if isinstance(raw_value, dict):
            narrative = raw_value.get("narrative") or raw_value.get("summary") or raw_value.get("outlook")
            assumptions = raw_value.get("assumptions") or raw_value.get("key_assumptions")
            if assumptions is None:
                assumptions = [
                    f"{_labelize_key(key)}: {value}"
                    for key, value in raw_value.items()
                    if key
                    not in {
                        "confidence",
                        "confidence_level",
                        "indicator_triggers",
                        "trigger_indicators",
                        "narrative",
                        "summary",
                        "outlook",
                        "uncertainty_notes",
                        "uncertainty",
                        "notes",
                    }
                    and value is not None
                ]
                if narrative:
                    assumptions.insert(0, str(narrative))
            indicator_triggers = (
                raw_value.get("indicator_triggers")
                or raw_value.get("trigger_indicators")
                or raw_value.get("triggers")
            )
            if indicator_triggers is None:
                indicator_triggers = (
                    [str(narrative)]
                    if narrative
                    else ["Monitor scenario assumptions against incoming macro data"]
                )
            scenario_rows.append(
                {
                    "scenario": scenario_name,
                    "assumptions": assumptions,
                    "indicator_triggers": indicator_triggers,
                    "confidence": raw_value.get("confidence") or raw_value.get("confidence_level") or "medium",
                    "uncertainty_notes": _coerce_uncertainty_notes(raw_value)
                    or "Compact scenario payload did not include explicit uncertainty notes.",
                }
            )
        elif isinstance(raw_value, str) and raw_value.strip():
            scenario_rows.append(
                {
                    "scenario": scenario_name,
                    "assumptions": [raw_value.strip()],
                    "indicator_triggers": ["Monitor scenario assumptions against incoming macro data"],
                    "confidence": "medium",
                    "uncertainty_notes": "Compact scenario payload did not include explicit uncertainty notes.",
                }
            )
    return scenario_rows or None


def _scenario_table_from_execution_summary(payload: dict[str, Any]) -> list[ScenarioRow] | None:
    rows = payload.get("scenario_table")
    if rows is None and isinstance(payload.get("scenario_stress_test"), dict):
        rows = payload["scenario_stress_test"].get("scenario_table")
    if rows is None and isinstance(payload.get("scenario_analysis"), dict):
        rows = payload["scenario_analysis"].get("scenario_table")
    if rows is None and isinstance(payload.get("statistical_summary"), dict):
        rows = payload["statistical_summary"].get("scenarios")
    if rows is None:
        rows = payload.get("scenarios")
    if rows is None and isinstance(payload.get("scenario_results"), dict):
        scenario_results = payload["scenario_results"]
        detail = scenario_results.get("detail")
        rows = detail if isinstance(detail, dict) else scenario_results
    if isinstance(rows, dict):
        rows = _scenario_rows_from_mapping(rows)
    if not isinstance(rows, list):
        return None

    scenario_rows: list[ScenarioRow] = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        raw_scenario = _get_case_insensitive(row, "scenario", "scenario_name")
        raw_assumptions = _get_case_insensitive(row, "assumptions", "key_assumptions")
        raw_triggers = _get_case_insensitive(row, "indicator_triggers", "trigger_indicators", "triggers")
        raw_confidence = (
            _get_case_insensitive(row, "confidence", "confidence_level")
            or _coerce_probability_confidence(
                _get_case_insensitive(row, "probability_assignment", "probability", "prob")
            )
        )
        normalized = {
            "scenario": raw_scenario,
            "assumptions": raw_assumptions,
            "indicator_triggers": raw_triggers,
            "confidence": raw_confidence,
            "uncertainty_notes": _coerce_uncertainty_notes(row),
        }
        if normalized["scenario"] is not None:
            normalized["scenario"] = _coerce_scenario_name(normalized["scenario"])
        normalized["assumptions"] = _coerce_string_list(normalized["assumptions"])
        if not normalized["assumptions"]:
            normalized["assumptions"] = _fallback_scenario_assumptions(row)
        normalized["indicator_triggers"] = _coerce_string_list(normalized["indicator_triggers"])
        if not normalized["indicator_triggers"]:
            normalized["indicator_triggers"] = [
                "Monitor scenario assumptions against incoming macro and market data"
            ]
        normalized["confidence"] = _coerce_confidence(normalized["confidence"])
        if not normalized["uncertainty_notes"]:
            normalized["uncertainty_notes"] = (
                "Compact scenario payload did not include explicit uncertainty notes."
            )
        try:
            scenario_rows.append(ScenarioRow(**normalized))
        except Exception:
            return None
    return scenario_rows


def _split_markdown_table_cell(value: str) -> list[str]:
    cleaned = (
        value.replace("<br />", ";")
        .replace("<br/>", ";")
        .replace("<br>", ";")
        .replace("•", ";")
    )
    parts = [part.strip(" -") for part in cleaned.split(";") if part.strip(" -")]
    return parts or ([value.strip()] if value.strip() else [])


def _scenario_table_from_markdown(markdown: str) -> list[ScenarioRow] | None:
    """Recover ScenarioRow objects from a writer-rendered markdown table."""
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        if "|" not in line:
            continue
        raw_headers = [cell.strip().lower() for cell in line.strip().strip("|").split("|")]
        normalized_headers = [header.replace("_", " ").replace("-", " ") for header in raw_headers]
        if "scenario" not in normalized_headers:
            continue
        rows: list[ScenarioRow] = []
        for row_line in lines[i + 1 :]:
            if "|" not in row_line:
                if rows:
                    break
                continue
            cells = [cell.strip() for cell in row_line.strip().strip("|").split("|")]
            if cells and all(set(cell.replace(":", "").strip()) <= {"-"} for cell in cells):
                continue
            if len(cells) < len(normalized_headers):
                continue
            row = dict(zip(normalized_headers, cells, strict=False))
            scenario = _coerce_scenario_name(row.get("scenario"))
            if scenario not in {"base", "bull", "bear"}:
                continue
            assumption_cell = next((value for key, value in row.items() if "assumption" in key), "")
            trigger_cell = next(
                (value for key, value in row.items() if "trigger" in key or "indicator" in key),
                "",
            )
            if not assumption_cell:
                fallback_parts = []
                for key, value in row.items():
                    if key == "scenario" or "trigger" in key or "indicator" in key:
                        continue
                    if "confidence" in key or "uncertainty" in key or "note" in key or "caveat" in key:
                        continue
                    if str(value).strip():
                        fallback_parts.append(f"{_labelize_key(key)}: {value.strip()}")
                assumption_cell = "; ".join(fallback_parts)
            confidence = _coerce_confidence(row.get("confidence"))
            uncertainty = next(
                (
                    value
                    for key, value in row.items()
                    if "uncertainty" in key or "note" in key or "caveat" in key
                ),
                "",
            ).strip()
            try:
                rows.append(
                    ScenarioRow(
                        scenario=scenario,
                        assumptions=_split_markdown_table_cell(assumption_cell),
                        indicator_triggers=_split_markdown_table_cell(trigger_cell)
                        or ["Monitor the scenario table assumptions against incoming data"],
                        confidence=confidence or "medium",
                        uncertainty_notes=uncertainty
                        or "Scenario uncertainty was described in the report narrative.",
                    )
                )
            except Exception:
                continue
        if rows:
            by_name = {row.scenario: row for row in rows}
            if {"base", "bull", "bear"}.issubset(by_name):
                return [by_name["base"], by_name["bull"], by_name["bear"]]
    return None


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
        "and Apple/Microsoft fundamentals; do not estimate replacements:\n"
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
    "latest_unrate",
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


def _compact_macro_cycle_chart_pack_payload(parsed: dict[str, Any]) -> str | None:
    if parsed.get("analysis_type") != "macro_cycle_chart_pack":
        return None

    lines: list[str] = ["Exact macro-cycle chart-pack facts from execution_summary.json:"]
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

    return "\n".join(lines)


def _compact_feature_acceptance_payload(parsed: dict) -> str | None:
    """Summarize the full-research acceptance artifacts without long histories."""
    parts: list[str] = []
    stats = parsed.get("statistical_summary")
    stats_payload = stats if isinstance(stats, dict) else {}

    risk = parsed.get("recession_risk_index")
    if not isinstance(risk, dict):
        risk = stats_payload.get("composite_indicator")
    if not isinstance(risk, dict):
        risk = parsed.get("composite_predictive_indicator")
    if not isinstance(risk, dict):
        risk = parsed.get("composite_indicator")
    if isinstance(risk, dict):
        lines = []
        for key in (
            "current_score",
            "current_classification",
            "latest_index_value",
            "latest_percentile_0_100",
            "latest_signal",
        ):
            if risk.get(key) is not None:
                lines.append(f"- {key}: {_fmt_summary_number(risk.get(key))}")
        composite = risk.get("composite_full")
        if isinstance(composite, dict):
            for key in ("latest_index_value", "latest_percentile_0_100", "latest_signal"):
                if composite.get(key) is not None:
                    lines.append(f"- {key}: {_fmt_summary_number(composite.get(key))}")
            latest_features = composite.get("latest_feature_values")
            if isinstance(latest_features, dict) and latest_features:
                values = [
                    f"{name}={_fmt_summary_number(value)}"
                    for name, value in latest_features.items()
                    if _fmt_summary_number(value) is not None
                ]
                if values:
                    lines.append("- latest_feature_values: " + "; ".join(values))
            backtest = composite.get("backtest_summary")
            if isinstance(backtest, dict):
                metrics = backtest.get("metrics")
                if isinstance(metrics, dict):
                    fields = [
                        f"{name}={_fmt_summary_number(value)}"
                        for name, value in metrics.items()
                        if _fmt_summary_number(value) is not None
                    ]
                    if fields:
                        lines.append("- backtest_metrics: " + "; ".join(fields[:8]))
        backtest = risk.get("backtest_summary")
        if isinstance(backtest, dict):
            if backtest.get("status") is not None:
                lines.append(f"- backtest_status: {backtest.get('status')}")
            window = backtest.get("test_window")
            if isinstance(window, dict) and (window.get("start") or window.get("end")):
                lines.append(
                    "- backtest_window: "
                    + f"{window.get('start', 'unknown')} to {window.get('end', 'unknown')}"
                )
            metrics = backtest.get("metrics")
            if isinstance(metrics, dict):
                fields = [
                    f"{name}={_fmt_summary_number(value)}"
                    for name, value in metrics.items()
                    if _fmt_summary_number(value) is not None
                ]
                if fields:
                    lines.append("- backtest_metrics: " + "; ".join(fields[:8]))
        if lines:
            parts.append(
                "Exact recession-risk framework values from execution_summary.json:\n"
                + "\n".join(lines)
            )

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

    forecast = parsed.get("unemployment_forecast")
    if not isinstance(forecast, dict):
        forecast = stats_payload.get("forecast_result")
    if isinstance(forecast, dict):
        lines = []
        if forecast.get("current_unemployment") is not None:
            lines.append(f"- current_unemployment: {_fmt_summary_number(forecast.get('current_unemployment'))}")
        rows = forecast.get("forecast_months") or forecast.get("forecast_table")
        if isinstance(rows, list) and rows:
            rendered = []
            for row in rows[:6]:
                if not isinstance(row, dict):
                    continue
                pieces = []
                for key in ("date", "month", "value", "forecast", "lower_ci", "upper_ci"):
                    if row.get(key) is not None:
                        pieces.append(f"{key}={_fmt_summary_number(row.get(key))}")
                if pieces:
                    rendered.append("; ".join(pieces))
            if rendered:
                lines.append("- forecast_months: " + " | ".join(rendered))
        if forecast.get("model_spec"):
            lines.append(f"- model_spec: {forecast.get('model_spec')}")
        if lines:
            parts.append(
                "Exact short-term unemployment outlook from execution_summary.json:\n"
                + "\n".join(lines)
            )

    regime = parsed.get("regime_classification")
    if not isinstance(regime, dict):
        regime = stats_payload.get("regime_result")
    if isinstance(regime, dict):
        lines = []
        regime_label = regime.get("regime") or regime.get("regime_label")
        if regime_label is not None:
            lines.append(f"- regime: {regime_label}")
        if regime.get("justification"):
            lines.append(f"- justification: {regime.get('justification')}")
        if regime.get("regime_score") is not None:
            lines.append(f"- regime_score: {_fmt_summary_number(regime.get('regime_score'))}")
        if regime.get("score_momentum") is not None:
            lines.append(f"- score_momentum: {_fmt_summary_number(regime.get('score_momentum'))}")
        category_scores = regime.get("category_scores")
        if isinstance(category_scores, dict) and category_scores:
            lines.append(
                "- category_scores: "
                + "; ".join(f"{key}={_fmt_summary_number(value)}" for key, value in category_scores.items())
            )
        evidence = regime.get("evidence_table")
        if isinstance(evidence, list) and evidence:
            lines.append("- evidence_table:")
            for row in evidence[:8]:
                if not isinstance(row, dict):
                    continue
                pieces = []
                for key in ("category", "indicator", "value", "score", "signal"):
                    if row.get(key) is not None:
                        pieces.append(f"{key}={_fmt_summary_number(row.get(key))}")
                if pieces:
                    lines.append("  - " + ", ".join(pieces))
        if lines:
            parts.append(
                "Exact regime-classification evidence from execution_summary.json:\n"
                + "\n".join(lines)
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

    tech_earnings = parsed.get("tech_earnings")
    if isinstance(tech_earnings, dict) and tech_earnings:
        fields = []
        for key in sorted(tech_earnings):
            value = tech_earnings.get(key)
            formatted = _fmt_summary_number(value)
            if formatted is not None:
                fields.append(f"- {key}: {formatted}")
        if fields:
            parts.append(
                "Exact large-cap technology earnings values from execution_summary.json. "
                "Use these SEC-derived values as controlling facts and do not substitute "
                "newer public-memory fiscal-year figures:\n"
                + "\n".join(fields[:16])
            )

    company_summaries = []
    for label, key in (("AAPL", "apple_summary"), ("MSFT", "msft_summary")):
        summary = parsed.get(key)
        if not isinstance(summary, dict):
            continue
        fields = []
        for field in (
            "fiscal_year_start",
            "fiscal_year_latest",
            "revenue_cagr_pct",
            "revenue_growth_pct",
            "net_income_growth_pct",
            "gross_margin_pct",
            "net_margin_pct",
            "debt_to_assets_pct",
        ):
            if summary.get(field) is not None:
                fields.append(f"{field}={_fmt_summary_number(summary.get(field))}")
        if fields:
            company_summaries.append(f"- {label}: " + ", ".join(fields))
    if company_summaries:
        parts.append(
            "Exact SEC EDGAR Apple/Microsoft summary values from execution_summary.json. "
            "Use these company facts as controlling evidence; do not add segment mix, installed-base, "
            "or sensitivity percentages unless execution_summary.json provides them:\n"
            + "\n".join(company_summaries)
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

    earnings = parsed.get("apple_msft_earnings")
    if isinstance(earnings, dict):
        lines = []
        for ticker in ("AAPL", "MSFT"):
            rows = earnings.get(ticker)
            if not isinstance(rows, list) or not rows:
                continue
            latest = next((row for row in reversed(rows) if isinstance(row, dict)), None)
            if not latest:
                continue
            fields = []
            for key in ("fiscal_year", "revenue_growth_pct", "net_income_growth_pct", "margin_pct"):
                if latest.get(key) is not None:
                    fields.append(f"{key}={_fmt_summary_number(latest.get(key))}")
            if fields:
                lines.append(f"- {ticker} latest: " + ", ".join(fields))
        if earnings.get("earnings_risk_assessment"):
            lines.append("- earnings_risk_assessment: " + str(earnings.get("earnings_risk_assessment")))
        if lines:
            parts.append(
                "Exact Apple/Microsoft earnings-risk values from execution_summary.json:\n"
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


def _compact_regime_classifier_payload(parsed: dict) -> str | None:
    """Preserve regime-classifier outputs without letting long history arrays dominate."""
    regime_label = parsed.get("regime_label") or parsed.get("current_regime")
    regime_score = parsed.get("regime_score")
    if regime_score is None:
        regime_score = parsed.get("composite_score")
    category_scores = parsed.get("category_scores") or parsed.get("domain_scores")

    has_regime_payload = any(
        key in parsed
        for key in (
            "regime_label",
            "current_regime",
            "regime_score",
            "composite_score",
            "evidence_table",
            "historical_analogs",
            "false_positive_caveat",
            "false_positive_caveats",
        )
    )
    if not has_regime_payload:
        return None

    lines = [
        "Required regime-classifier fields from execution_summary.json. "
        "Render the regime label, evidence table, historical analogs, and false-positive caveat:"
    ]
    if parsed.get("current_month") is not None:
        lines.append(f"- current_month: {parsed.get('current_month')}")
    if regime_label is not None:
        lines.append(f"- regime_label: {regime_label}")
    if regime_score is not None:
        lines.append(f"- regime_score: {regime_score}")

    if isinstance(category_scores, dict) and category_scores:
        scores = "; ".join(f"{key}={value}" for key, value in category_scores.items())
        lines.append(f"- category_scores: {scores}")

    methodology = parsed.get("scoring_methodology")
    if isinstance(methodology, str) and methodology.strip():
        lines.append("- scoring_methodology: " + methodology.strip())

    stats = parsed.get("statistical_summary")
    if isinstance(stats, dict) and stats:
        stat_fields = []
        for key, value in stats.items():
            formatted = _fmt_summary_number(value)
            if formatted is not None:
                stat_fields.append(f"{key}={formatted}")
        if stat_fields:
            lines.append("- latest_statistical_summary: " + "; ".join(stat_fields[:12]))

    evidence = parsed.get("evidence_table")
    if isinstance(evidence, list) and evidence:
        lines.append("- evidence_table:")
        for row in evidence[:10]:
            if not isinstance(row, dict):
                continue
            pieces = []
            for key in (
                "category",
                "domain",
                "indicator",
                "value",
                "score",
                "domain_total_score",
                "weight",
                "contribution_to_composite",
                "rationale",
            ):
                if row.get(key) is not None:
                    pieces.append(f"{key}={row.get(key)}")
            sub_indicators = row.get("sub_indicators_used")
            if isinstance(sub_indicators, list) and sub_indicators:
                pieces.append("sub_indicators_used=" + "|".join(str(item) for item in sub_indicators[:8]))
            raw_values = row.get("raw_values_latest")
            if isinstance(raw_values, dict) and raw_values:
                raw_text = ";".join(
                    f"{key}={_fmt_summary_number(value)}"
                    for key, value in list(raw_values.items())[:8]
                    if _fmt_summary_number(value) is not None
                )
                if raw_text:
                    pieces.append("raw_values_latest=" + raw_text)
            if pieces:
                lines.append("  - " + ", ".join(pieces))

    analogs = parsed.get("historical_analogs")
    if isinstance(analogs, list):
        if analogs:
            lines.append("- historical_analogs:")
            for analog in analogs[:5]:
                if not isinstance(analog, dict):
                    continue
                pieces = []
                for key in ("date", "label", "regime_label", "regime_score", "distance"):
                    if analog.get(key) is not None:
                        pieces.append(f"{key}={analog.get(key)}")
                analog_scores = analog.get("domain_scores")
                if isinstance(analog_scores, dict) and analog_scores:
                    pieces.append(
                        "domain_scores="
                        + ";".join(f"{key}={value}" for key, value in analog_scores.items())
                    )
                if pieces:
                    lines.append("  - " + ", ".join(pieces))
        else:
            lines.append("- historical_analogs: none available from the local fixture/window")

    missing = parsed.get("missing_indicators")
    if isinstance(missing, list) and missing:
        missing_labels = []
        for item in missing[:10]:
            if isinstance(item, dict):
                missing_labels.append(str(item.get("indicator") or item.get("column") or item))
            else:
                missing_labels.append(str(item))
        lines.append("- missing_indicators: " + "; ".join(missing_labels))

    caveats = parsed.get("false_positive_caveats")
    if isinstance(caveats, list) and caveats:
        lines.append("- false_positive_caveats: " + "; ".join(str(item) for item in caveats[:5]))
    else:
        caveat = parsed.get("false_positive_caveat")
        if isinstance(caveat, str) and caveat.strip():
            lines.append("- false_positive_caveat: " + caveat.strip())

    if parsed.get("classification_boundary_margin") is not None:
        lines.append(f"- classification_boundary_margin: {parsed.get('classification_boundary_margin')}")
    transition_note = parsed.get("transition_note")
    if isinstance(transition_note, str) and transition_note.strip():
        lines.append("- transition_note: " + transition_note.strip())

    return "\n".join(lines)


def _compact_validation_and_simulation_payload(parsed: dict) -> str | None:
    """Preserve econometric validation and historical replay fields for report drafting."""

    lines: list[str] = []

    def _signal_framework_from(payload: dict) -> dict | None:
        summary = payload.get("signal_framework_summary")
        if isinstance(summary, dict):
            return summary
        simulations = payload.get("historical_simulations")
        if isinstance(simulations, dict):
            nested = simulations.get("signal_framework_backtest")
            if isinstance(nested, dict):
                return nested
        signal_backtest = payload.get("signal_backtest")
        if isinstance(signal_backtest, dict):
            nested_simulations = signal_backtest.get("historical_simulations")
            if isinstance(nested_simulations, dict):
                nested = nested_simulations.get("signal_framework_backtest")
                if isinstance(nested, dict):
                    return nested
        return None

    signal_framework = _signal_framework_from(parsed)
    if isinstance(signal_framework, dict):
        lines.append(
            "Controlling signal-framework backtest values from execution_summary.json. "
            "For signal-stack, false-positive, and prior-downturn claims, use these values "
            "instead of unrelated composite-index percentile or z-score diagnostics. "
            "`recession_count` is the total number of recessions tested; "
            "`recession_calls_correct` is the number that reached the alert threshold. "
            "Do not write that all recessions were correctly identified unless those two "
            "counts are equal:"
        )
        scalar_fields = []
        for key in (
            "total_observations",
            "observations",
            "recession_count",
            "recession_calls_correct",
            "false_alarms",
            "true_positive_rate",
            "precision",
            "threshold",
            "lookback_periods",
            "false_alarm_lookahead_periods",
        ):
            if signal_framework.get(key) is not None:
                scalar_fields.append(f"{key}={signal_framework.get(key)}")
        if scalar_fields:
            lines.append("- signal_framework_backtest: " + "; ".join(scalar_fields))
        current_signal = signal_framework.get("current_signal")
        if isinstance(current_signal, dict) and current_signal:
            fields = [
                f"{key}={value}"
                for key, value in current_signal.items()
                if value is not None
            ]
            if fields:
                lines.append("- current_signal: " + "; ".join(fields))
        pre_scores = signal_framework.get("pre_recession_scores")
        if isinstance(pre_scores, dict) and pre_scores:
            rows = []
            for label, row in list(pre_scores.items())[:20]:
                if not isinstance(row, dict):
                    continue
                score = row.get("score")
                triggered = row.get("components_triggered")
                max_date = row.get("max_score_date")
                parts = []
                if score is not None:
                    parts.append(f"score={score}")
                if triggered:
                    parts.append(f"components_triggered={triggered}")
                if max_date is not None:
                    parts.append(f"max_score_date={max_date}")
                if parts:
                    rows.append(f"{label}: " + ", ".join(parts))
            if rows:
                lines.append("- pre_recession_scores: " + " | ".join(rows))
        false_alarm_episodes = signal_framework.get("false_alarm_episodes")
        if isinstance(false_alarm_episodes, list) and false_alarm_episodes:
            rows = []
            for row in false_alarm_episodes[:8]:
                if not isinstance(row, dict):
                    continue
                period = row.get("period")
                max_score = row.get("max_score")
                components = row.get("components_at_peak")
                if period is not None:
                    rows.append(
                        f"{period}: max_score={max_score}, components_at_peak={components}"
                    )
            if rows:
                lines.append("- false_alarm_episodes: " + " | ".join(rows))

    def _append_numeric_mapping(label: str, values: object, *, limit: int = 16) -> None:
        if not isinstance(values, dict) or not values:
            return
        pieces = []
        for key, value in list(values.items())[:limit]:
            if isinstance(value, bool):
                formatted = None
            elif isinstance(value, int):
                formatted = str(value)
            elif isinstance(value, float):
                formatted = None if value != value else f"{value:.4f}".rstrip("0").rstrip(".")
            else:
                formatted = _fmt_summary_number(value)
            if formatted is None:
                if value is None:
                    pieces.append(f"{key}=null")
                continue
            pieces.append(f"{key}={formatted}")
        if pieces:
            lines.append(f"- {label}: " + "; ".join(pieces))

    def _append_backtest_row(label: str, row: object, *, limit: int = 12) -> None:
        if not isinstance(row, dict) or not row:
            return
        pieces = [f"{key}={value}" for key, value in list(row.items())[:limit] if value is not None]
        if pieces:
            lines.append(f"  - {label}: " + "; ".join(pieces))

    backtest = parsed.get("backtest_summary")
    if isinstance(backtest, dict) and backtest:
        lines.append(
            "Required econometric validation from execution_summary.json. "
            "Discuss out-of-sample performance, baseline comparison, and limitations:"
        )
        if backtest.get("status") is not None:
            lines.append(f"- backtest_status: {backtest.get('status')}")
        scalar_fields = []
        for key in (
            "average_auc",
            "average_brier_score",
            "auc",
            "brier_score",
            "accuracy",
            "precision",
            "recall",
            "f1_score",
            "method",
        ):
            if backtest.get(key) is not None:
                scalar_fields.append(f"{key}={backtest.get(key)}")
        if scalar_fields:
            lines.append("- backtest_summary: " + "; ".join(scalar_fields))
        for label, key in (
            ("current_z_scores", "current_z_scores"),
            ("pre_recession_avg_z_scores", "pre_recession_avg_z_scores"),
            ("current_values", "current_values"),
            ("historical_baseline_values", "historical_baseline_values"),
            ("pre_recession_values", "pre_recession_values"),
        ):
            _append_numeric_mapping(label, backtest.get(key))
        calibration = backtest.get("calibration")
        if isinstance(calibration, dict):
            calibration_text = "; ".join(
                f"{key}={value}" for key, value in calibration.items() if value is not None
            )
            if calibration_text:
                lines.append("- calibration: " + calibration_text)
        years = backtest.get("years")
        if isinstance(years, dict) and years:
            year_lines = []
            for year, metrics_for_year in list(years.items())[:30]:
                if not isinstance(metrics_for_year, dict):
                    continue
                fields = [
                    f"{metric}={value}"
                    for metric, value in metrics_for_year.items()
                    if value is not None
                ]
                if fields:
                    year_lines.append(f"{year}: " + ", ".join(fields[:4]))
            if year_lines:
                lines.append("- annual_oos_metrics: " + " | ".join(year_lines))
        horizon_results = backtest.get("horizon_results")
        if isinstance(horizon_results, list) and horizon_results:
            for row in horizon_results[:8]:
                if not isinstance(row, dict):
                    continue
                pieces = []
                for key in ("prediction_horizon", "test_observations", "best_model_by_mae"):
                    if row.get(key) is not None:
                        pieces.append(f"{key}={row.get(key)}")
                metrics = row.get("metrics")
                if isinstance(metrics, dict):
                    for key in ("mae", "rmse", "bias", "directional_accuracy"):
                        if metrics.get(key) is not None:
                            pieces.append(f"{key}={metrics.get(key)}")
                baseline = row.get("baseline_comparison")
                if isinstance(baseline, dict):
                    for label, values in list(baseline.items())[:2]:
                        if isinstance(values, dict) and values.get("mae") is not None:
                            pieces.append(f"{label}_mae={values.get('mae')}")
                if pieces:
                    lines.append("  - " + ", ".join(pieces))
        else:
            metrics = backtest.get("metrics")
            if isinstance(metrics, dict):
                metric_text = "; ".join(
                    f"{key}={value}" for key, value in metrics.items() if value is not None
                )
                if metric_text:
                    lines.append("- metrics: " + metric_text)
            false_positive = backtest.get("false_positive_analysis")
            if isinstance(false_positive, dict):
                fp_text = "; ".join(
                    f"{key}={value}" for key, value in false_positive.items() if value is not None
                )
                if fp_text:
                    lines.append("- false_positive_analysis: " + fp_text)
        nested_rows = {
            key: value
            for key, value in backtest.items()
            if isinstance(value, dict)
            and key
            not in {
                "calibration",
                "current_values",
                "current_z_scores",
                "false_positive_analysis",
                "historical_baseline_values",
                "pre_recession_avg_z_scores",
                "pre_recession_values",
                "years",
            }
        }
        if nested_rows:
            lines.append(
                "Exact nested backtest/model rows from execution_summary.json. "
                "Use these exact values; if a row has error=..., state that the comparison failed "
                "and do not fabricate RMSE, R², or baseline wins:"
            )
            for key, value in list(nested_rows.items())[:12]:
                if key == "recession_backtest":
                    lines.append("  - recession_backtest:")
                    for period, row in list(value.items())[:12]:
                        _append_backtest_row(str(period), row)
                else:
                    _append_backtest_row(str(key), value)
    else:
        false_positive = parsed.get("false_positive_analysis")
        if isinstance(false_positive, dict) and false_positive:
            fp_text = "; ".join(
                f"{key}={value}" for key, value in false_positive.items() if value is not None
            )
            if fp_text:
                lines.append(
                    "Exact signal backtest false-positive analysis from execution_summary.json: "
                    + fp_text
                )

    model_comparison = parsed.get("model_comparison")
    if isinstance(model_comparison, dict) and model_comparison:
        lines.append("Exact model comparison rows from execution_summary.json:")
        for model, row in list(model_comparison.items())[:10]:
            if not isinstance(row, dict):
                if row is not None:
                    lines.append(f"  - {model}: {row}")
                continue
            pieces = [f"model={model}"]
            for key in (
                "horizon",
                "mae",
                "rmse",
                "bias",
                "directional_accuracy",
                "accuracy",
                "precision",
                "recall",
                "f1_score",
                "auc",
                "rmse_oos",
                "r2_oos",
                "n_obs",
                "status",
                "error",
                "description",
            ):
                if row.get(key) is not None:
                    pieces.append(f"{key}={row.get(key)}")
            if pieces:
                lines.append("  - " + ", ".join(pieces))
    elif isinstance(model_comparison, list) and model_comparison:
        lines.append("Exact model comparison rows from execution_summary.json:")
        for row in model_comparison[:10]:
            if not isinstance(row, dict):
                continue
            pieces = []
            for key in (
                "horizon",
                "model",
                "mae",
                "rmse",
                "bias",
                "directional_accuracy",
                "accuracy",
                "precision",
                "recall",
                "f1_score",
                "auc",
                "rmse_oos",
                "r2_oos",
                "n_obs",
                "status",
                "error",
                "description",
            ):
                if row.get(key) is not None:
                    pieces.append(f"{key}={row.get(key)}")
            if pieces:
                lines.append("  - " + ", ".join(pieces))

    simulations = parsed.get("historical_simulations")
    if isinstance(simulations, dict) and simulations:
        lines.append(
            "Required historical simulation/replay values from execution_summary.json. "
            "Use these exact analog dates and forward outcomes; do not invent alternate replay metrics:"
        )
        for key in ("analog_count", "method"):
            if simulations.get(key) is not None:
                lines.append(f"- {key}: {simulations.get(key)}")
        for label, key in (
            ("simulation_current_values", "current_values"),
            ("simulation_pre_recession_values", "pre_recession_values"),
            ("simulation_historical_baseline_values", "historical_baseline_values"),
        ):
            _append_numeric_mapping(label, simulations.get(key))
        analog_dates = simulations.get("analog_dates")
        if isinstance(analog_dates, list) and analog_dates:
            lines.append("- analog_dates: " + "; ".join(str(item) for item in analog_dates[:15]))
        forward_horizons = simulations.get("forward_horizons")
        if isinstance(forward_horizons, dict) and forward_horizons:
            for horizon, row in forward_horizons.items():
                if not isinstance(row, dict):
                    continue
                pieces = [f"horizon={horizon}"]
                for key in (
                    "mean_unrate_change",
                    "median_unrate_change",
                    "std_unrate_change",
                    "pct_recession",
                    "mean",
                    "median",
                    "std",
                ):
                    if row.get(key) is not None:
                        pieces.append(f"{key}={row.get(key)}")
                lines.append("  - " + ", ".join(pieces))
    elif isinstance(simulations, list) and simulations:
        lines.append(
            "Required historical simulation/replay rows from execution_summary.json. "
            "Use these as analog evidence, not causal proof:"
        )
        for row in simulations[:8]:
            if not isinstance(row, dict):
                continue
            pieces = []
            for key in ("label", "start", "end", "status"):
                if row.get(key) is not None:
                    pieces.append(f"{key}={row.get(key)}")
            during = row.get("outcome_during_window")
            if isinstance(during, dict):
                for key in ("start", "end", "min", "max"):
                    if during.get(key) is not None:
                        pieces.append(f"outcome_{key}={during.get(key)}")
            subsequent = row.get("subsequent_outcome")
            if isinstance(subsequent, dict):
                for key in ("periods", "end", "min", "max"):
                    if subsequent.get(key) is not None:
                        pieces.append(f"subsequent_{key}={subsequent.get(key)}")
            if pieces:
                lines.append("  - " + ", ".join(pieces))

    replay = parsed.get("what_happened_next")
    if isinstance(replay, dict) and replay:
        design = replay.get("simulation_design")
        outcome_variable = None
        if isinstance(design, dict):
            outcome_variable = design.get("outcome_variable")
            design_bits = []
            for key in ("outcome_variable", "lookahead_periods"):
                if design.get(key) is not None:
                    design_bits.append(f"{key}={design.get(key)}")
            signals = design.get("signal_variables")
            if isinstance(signals, list) and signals:
                design_bits.append("signal_variables=" + ", ".join(str(item) for item in signals[:8]))
            if design_bits:
                lines.append(
                    "Exact what-happened-next replay design from execution_summary.json: "
                    + "; ".join(design_bits)
                    + ". Only describe forward outcomes for variables present in these replay rows; "
                    "state unavailable outcomes explicitly instead of substituting external benchmarks."
                )
        replay_rows = replay.get("historical_simulations")
        if isinstance(replay_rows, list) and replay_rows:
            lines.append(
                "Exact what-happened-next replay rows from execution_summary.json. "
                "Do not invent S&P 500, unemployment, production, or other forward outcomes "
                "unless those keys appear in the rows below:"
            )
            for row in replay_rows[:8]:
                if not isinstance(row, dict):
                    continue
                pieces = []
                for key in ("label", "start", "end", "status"):
                    if row.get(key) is not None:
                        pieces.append(f"{key}={row.get(key)}")
                during = row.get("outcome_during_window")
                if isinstance(during, dict):
                    prefix = f"{outcome_variable}_during" if outcome_variable else "outcome_during"
                    for key in ("start", "end", "min", "max", "mean"):
                        if during.get(key) is not None:
                            pieces.append(f"{prefix}_{key}={during.get(key)}")
                subsequent = row.get("subsequent_outcome")
                if isinstance(subsequent, dict):
                    prefix = f"{outcome_variable}_subsequent" if outcome_variable else "subsequent"
                    for key in ("periods", "end", "min", "max"):
                        if subsequent.get(key) is not None:
                            pieces.append(f"{prefix}_{key}={subsequent.get(key)}")
                if pieces:
                    lines.append("  - " + ", ".join(pieces))

    if lines:
        return "\n".join(lines)
    return None


def _compact_execution_summary_payload(parsed: dict) -> str:
    parts: list[str] = []
    compact_limit = 4000
    stats = parsed.get("statistical_summary")
    stats_payload = stats if isinstance(stats, dict) else {}

    acceptance_summary = _compact_feature_acceptance_payload(parsed)
    if acceptance_summary:
        parts.append(acceptance_summary)
        compact_limit = 8000

    regime_summary = _compact_regime_classifier_payload(parsed)
    if regime_summary:
        parts.append(regime_summary)

    validation_summary = _compact_validation_and_simulation_payload(parsed)
    if validation_summary:
        parts.append(validation_summary)
        compact_limit = max(compact_limit, 8000)

    macro_cycle_summary = _compact_macro_cycle_chart_pack_payload(parsed)
    if macro_cycle_summary:
        parts.append(macro_cycle_summary)
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

    scenario_rows = _scenario_table_from_execution_summary(parsed)
    if scenario_rows:
        lines = []
        for row in scenario_rows:
            lines.append(
                f"- {row.scenario}: assumptions={'; '.join(row.assumptions)}; "
                f"triggers={'; '.join(row.indicator_triggers)}; "
                f"confidence={row.confidence}; uncertainty={row.uncertainty_notes}"
            )
        parts.append(
            "Required scenario table from execution_summary.json. Render it as a markdown table "
            "with Scenario, Assumptions, Indicator Triggers, Confidence, and Uncertainty Notes columns:\n"
            + "\n".join(lines)
        )

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
    charts_json_path = _resolve_charts_json_path(runtime, charts_json_path)
    _save_plan_context(
        runtime,
        charts_json_path=charts_json_path,
        original_query=original_query,
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

    execution_summary_for_draft = _compact_execution_summary(runtime, execution_summary)
    if chart_facts_for_draft:
        execution_summary_for_draft = (
            chart_facts_for_draft
            if not execution_summary_for_draft
            else chart_facts_for_draft + "\n\n" + execution_summary_for_draft
        )
    if _requires_scenario_table(original_query):
        general_rules += (
            " Because the query asks for scenarios or stress testing, you MUST include a "
            "`## Scenario Table` section rendered as a markdown table with base, bull, and bear rows; "
            "use scenario_table from execution_summary_for_draft when present. "
            "Use exactly these parser-compatible headers and lowercase scenario row keys: "
            "`| Scenario | Assumptions | Indicator Triggers | Confidence | Uncertainty Notes |`, "
            "then rows beginning `| base |`, `| bull |`, and `| bear |`."
        )

    return json.dumps(
        {
            "general_rules": general_rules,
            "query_type": query_type,
            "chart_ids": chart_ids,
            "recommended_word_count": "1000+ words",
            "charts_json_path": charts_json_path,
            "chart_facts_for_draft": chart_facts_for_draft,
            "execution_summary_for_draft": execution_summary_for_draft,
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
            When it contains scenario_table, that structured table is embedded
            into report.json for QA/frontend consumers.

    Returns:
        JSON string with:
        - report_path: Absolute path where report.json was saved
        - chart_count: Number of <!-- CHART:id --> markers found in markdown
        - word_count: Approximate word count of markdown
        - validation_issues: List of non-blocking warnings (may be empty)
    """
    canonical_job_id = runtime.context.job_id
    plan_context = _load_plan_context(runtime)
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
    if not str(original_query).strip():
        original_query = _extract_research_query_from_markdown(markdown)
    if not str(original_query).strip():
        original_query = plan_context.get("original_query", "")
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

    scenario_table = _scenario_table_from_execution_summary(
        _execution_summary_payload(runtime, execution_summary)
    )
    if scenario_table is None and _requires_scenario_table(original_query):
        scenario_table = _scenario_table_from_markdown(markdown)

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
        scenario_table=scenario_table,
        data_sources=ds_objects,
        metadata=metadata,
    )

    # -------------------------------------------------------------------------
    # 6. Save to disk with pre-write validation
    # -------------------------------------------------------------------------
    out_dir = runtime.context.output_dir
    if not out_dir:
        out_dir = str(OUTPUT_BASE_DIR / canonical_job_id)
    report_path = str((Path(out_dir) / "report.json").resolve())
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
    or chart render/data semantics blockers.
    Check `warnings` for non-blocking hints (e.g. empty executive summary). Prose compliance
    is for quality-analyst review, not static regex.

    Args:
        report_json_path: Absolute path to `report.json`. If empty, uses
            `{output_dir}/report.json` from the current job context.
        auto_patch: If True, apply auto footer re-sync and chart-marker patches when applicable.

    Returns:
        JSON string with `passes_gate`, `format`, `charts`, `chart_render`,
        `chart_semantics`, `warnings`, `auto_patched`, `patches_applied`, and `blockers`.
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
    return run_report_static_gate(path, auto_patch=auto_patch)
