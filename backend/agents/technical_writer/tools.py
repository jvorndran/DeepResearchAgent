"""
LangChain tools for the Technical Writer subagent — plan outline, save report.json,
static validation gate.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from langchain.tools import ToolRuntime

from core.context import ResearchContext
from core.report_schema import DataSource, ReportMetadata, ResearchReport

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


def _is_macro_report(query_type: str, original_query: str) -> bool:
    """Infer macro report shape when the caller passes a generic query type."""
    macro_types = {"macro_indicator", "trend_analysis", "correlation_analysis"}
    if query_type in macro_types:
        return True

    lowered_query = original_query.lower()
    if any(keyword in lowered_query for keyword in _MACRO_QUERY_KEYWORDS):
        return True

    return False


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
        "linechart": "line",
        "barchart": "bar",
        "areachart": "area",
        "composedchart": "composed",
        "scatterchart": "scatter",
        "piechart": "pie",
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
        chart_copy.setdefault("description", _infer_chart_description(chart_copy, chart_id))

        if "type" not in chart_copy and isinstance(chart_copy.get("chart_type"), str):
            chart_copy["type"] = chart_copy["chart_type"]
        if "type" not in chart_copy and isinstance(chart_copy.get("chartType"), str):
            chart_copy["type"] = chart_copy["chartType"]
        if isinstance(chart_copy.get("type"), str):
            normalized_type = chart_copy["type"].replace(" ", "").lower()
            chart_copy["type"] = chart_type_aliases.get(normalized_type, normalized_type)
        chart_copy.setdefault("title", _infer_chart_title(chart_copy, chart_id))

        config = chart_copy.get("config") if isinstance(chart_copy.get("config"), dict) else {}
        recharts_children = _recharts_children(chart_copy)

        if chart_copy.get("type") == "radar":
            chart_copy = _coerce_radar_to_bar(chart_copy)

        if chart_copy.get("type") in {"line", "bar", "area", "composed"}:
            _flatten_panel_axis_data(chart_copy)

            if "xAxisKey" not in chart_copy:
                child_x_axis_key = _axis_key_from_recharts_children(recharts_children)
                if child_x_axis_key:
                    chart_copy["xAxisKey"] = child_x_axis_key
            if "xAxisKey" not in chart_copy and isinstance(config.get("xKey"), str):
                chart_copy["xAxisKey"] = config["xKey"]
            if "xAxisKey" not in chart_copy and isinstance(chart_copy.get("xKey"), str):
                chart_copy["xAxisKey"] = chart_copy["xKey"]
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
                elif "series" not in chart_copy and isinstance(config.get("yKeys"), list):
                    chart_copy["series"] = _series_from_y_keys(
                        config.get("yKeys", []),
                        config.get("colors", []),
                        config.get("names", []),
                    )
                elif "series" not in chart_copy and isinstance(chart_copy.get("yKeys"), list):
                    chart_copy["series"] = _series_from_y_keys(chart_copy.get("yKeys", []))
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

        if chart_copy.get("type") == "pie" and isinstance(chart_copy.get("data"), list):
            pie_data = []
            for point in chart_copy["data"]:
                if not isinstance(point, dict):
                    pie_data.append(point)
                    continue
                point_copy = dict(point)
                if "value" not in point_copy and "size" in point_copy:
                    point_copy["value"] = point_copy["size"]
                pie_data.append(point_copy)
            chart_copy["data"] = pie_data

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


def _resolve_charts_json_path(
    runtime: ToolRuntime[ResearchContext], charts_json_path: str
) -> str:
    """Pick the first existing charts.json — caller path, then canonical job output_dir."""
    candidates: list[Path] = []
    if charts_json_path.strip():
        p = Path(charts_json_path).expanduser()
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
    return charts_json_path.strip() or (str(Path(od) / "charts.json") if od else "")


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
            summary = parsed.get("statistical_summary")
            if isinstance(summary, str) and summary.strip():
                return summary.strip()[:4000]
        return json.dumps(parsed, ensure_ascii=False)[:4000]

    if "\n" in value or len(value) > 512:
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
        summary = parsed.get("statistical_summary")
        if isinstance(summary, str) and summary.strip():
            return summary.strip()[:4000]
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
        - execution_summary_for_draft: Writer-useful computed findings extracted from inline JSON or a job-local summary file
        - original_query: Echo of `original_query` (pass unchanged to `write_research_report`)
    """
    charts_json_path = _resolve_charts_json_path(runtime, charts_json_path)

    # Load chart IDs from disk — never from caller context
    chart_ids: list[str] = []
    try:
        raw = Path(charts_json_path).read_text(encoding="utf-8")
        charts_data = json.loads(raw)
        chart_ids = list(_chart_map_from_parsed_json(charts_data).keys())
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
            "Place each chart marker immediately after the paragraph that discusses its data."
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
            "Place each chart marker immediately after the paragraph that discusses its data."
        )

    execution_summary_for_draft = _compact_execution_summary(runtime, execution_summary)

    return json.dumps(
        {
            "general_rules": general_rules,
            "query_type": query_type,
            "chart_ids": chart_ids,
            "recommended_word_count": "1000+ words",
            "charts_json_path": charts_json_path,
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
        execution_summary: Optional. If the model mistakenly passes quant JSON here
            (same name as ``plan_report_structure``), it is ignored — use only
            ``executive_summary`` for the short report summary field.

    Returns:
        JSON string with:
        - report_path: Absolute path where report.json was saved
        - chart_count: Number of <!-- CHART:id --> markers found in markdown
        - word_count: Approximate word count of markdown
        - validation_issues: List of non-blocking warnings (may be empty)
    """
    _ = execution_summary  # optional mistaken echo from plan_report_structure; ignored

    canonical_job_id = runtime.context.job_id
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
    Run the static report gate: Pydantic schema, chart marker resolution, and optional
    safe auto-patches. Call after `write_research_report`.

    When `auto_patch` is True, may re-apply the canonical disclaimer footer (idempotent),
    remove broken `<!-- CHART:id -->` markers, then write `report.json` when patches apply.

    `passes_gate` is false only for load/schema errors or unresolved broken chart markers.
    Check `warnings` for non-blocking hints (e.g. empty executive summary). Prose compliance
    is for quality-analyst review, not static regex.

    Args:
        report_json_path: Absolute path to `report.json`. If empty, uses
            `{output_dir}/report.json` from the current job context.
        auto_patch: If True, apply auto footer re-sync and chart-marker patches when applicable.

    Returns:
        JSON string with `passes_gate`, `format`, `charts`, `warnings`, `auto_patched`,
        `patches_applied`, and `blockers`. Revise markdown and call
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
