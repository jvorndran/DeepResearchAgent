"""
Technical Writer Subagent (Deep Agents)

The Technical Writer synthesizes research reports from analysis results.
It is the SOLE assembler of the ResearchReport artifact — it reads all
prior-stage outputs directly from the filesystem and produces report.json.

Role: Technical Writer / Research Analyst
Model: Gemini 3.0 Flash Preview (excellent at synthesis and clear writing)

Responsibilities:
- Read charts.json directly from disk (never receives chart data through context)
- Plan report structure dynamically based on query type and discovered charts
- Write markdown with inline <!-- CHART:id --> markers
- Assemble and validate the full ResearchReport object
- Save report.json as the single canonical output artifact

Key Principle: No other agent touches report.json. The quant developer produces
their own artifacts (charts.json, CSV files); the technical writer reads those
artifacts and assembles the complete report independently.
"""

from typing import Dict, List
from langchain_core.tools import tool
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from core.report_schema import ResearchReport, DataSource, ReportMetadata

# Absolute output base dir — avoids CWD ambiguity when running as a subagent
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_OUTPUT_BASE_DIR = Path(os.getenv("OUTPUT_DIR", str(_BACKEND_DIR / "outputs")))
_LAST_REPORT_CONTEXT: dict[str, str] = {
    "charts_json_path": "",
    "original_query": "",
    "job_id": "",
}


# =============================================================================
# TECHNICAL WRITER TOOLS
# =============================================================================


def _labelize_key(key: str) -> str:
    """Turn a data key like `gdp_growth_pct` into a readable label."""
    return key.replace("_", " ").strip().title()


def _infer_chart_description(chart_copy: dict, chart_id: str) -> str:
    title = chart_copy.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return f"Chart for {chart_id.replace('_', ' ')}."


def _normalize_chart_definitions(charts_on_disk: dict) -> dict:
    """Coerce legacy chart shapes into the ResearchReport schema."""
    normalized: dict = {}

    for chart_id, chart_def in charts_on_disk.items():
        if not isinstance(chart_def, dict):
            normalized[chart_id] = chart_def
            continue

        chart_copy = dict(chart_def)
        chart_copy.setdefault("id", chart_id)
        chart_copy.setdefault("description", _infer_chart_description(chart_copy, chart_id))

        config = chart_copy.get("config") if isinstance(chart_copy.get("config"), dict) else {}

        if chart_copy.get("type") in {"line", "bar", "area"}:
            if "xAxisKey" not in chart_copy and isinstance(config.get("xKey"), str):
                chart_copy["xAxisKey"] = config["xKey"]

            if "series" not in chart_copy:
                config_series = config.get("series")
                if isinstance(config_series, list) and config_series:
                    chart_copy["series"] = [
                        {
                            "dataKey": item.get("dataKey") or item.get("key", ""),
                            "label": item.get("label") or item.get("name") or _labelize_key(item.get("dataKey") or item.get("key", "")),
                            "color": item.get("color", "#3b82f6"),
                        }
                        for item in config_series
                        if isinstance(item, dict) and (item.get("dataKey") or item.get("key"))
                    ]
                elif isinstance(config.get("yKeys"), list):
                    y_keys = config.get("yKeys", [])
                    colors = config.get("colors", [])
                    names = config.get("names", [])
                    chart_copy["series"] = [
                        {
                            "dataKey": data_key,
                            "label": names[idx] if idx < len(names) else _labelize_key(data_key),
                            "color": colors[idx] if idx < len(colors) else "#3b82f6",
                        }
                        for idx, data_key in enumerate(y_keys)
                        if isinstance(data_key, str) and data_key
                    ]

        if chart_copy.get("type") == "scatter" and "xKey" not in chart_copy:
            config_series = config.get("series") if isinstance(config.get("series"), list) else []
            first_config_series = config_series[0] if config_series and isinstance(config_series[0], dict) else {}
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
            chart_copy["yLabel"] = chart_copy.get("yLabel") or first_config_series.get("name") or _labelize_key(y_key)
            chart_copy["color"] = chart_copy.get("color") or first_config_series.get("color") or "#3b82f6"

        normalized[chart_id] = chart_copy

    return normalized


def _extract_job_id_from_path(path: str) -> str:
    match = re.search(r"/(test-[^/]+)/", path)
    return match.group(1) if match else ""

@tool
def plan_report_structure(
    query_type: str,
    charts_json_path: str,
    execution_summary: str,
    original_query: str
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
                           developer (e.g. '{"correlation_coefficient": 0.82, ...}')
        original_query: The user's original research question

    Returns:
        JSON string with:
        - general_rules: High-level instructions on how to structure the report
        - query_type: Echoed back
        - chart_ids: List of chart IDs discovered from charts.json
        - recommended_word_count: Target word count for the report
    """
    _LAST_REPORT_CONTEXT["charts_json_path"] = charts_json_path
    _LAST_REPORT_CONTEXT["original_query"] = original_query
    _LAST_REPORT_CONTEXT["job_id"] = _extract_job_id_from_path(charts_json_path)

    # Load chart IDs from disk — never from caller context
    chart_ids: list[str] = []
    try:
        raw = Path(charts_json_path).read_text(encoding="utf-8")
        charts_data = json.loads(raw)
        if isinstance(charts_data, list):
            chart_ids = [item["name"] for item in charts_data if isinstance(item, dict) and "name" in item]
        else:
            chart_ids = list(charts_data.keys())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        chart_ids = []

    # Determine if query is Macro or Equity/Company focused
    macro_types = {"macro_indicator", "trend_analysis", "correlation_analysis"}
    is_macro = query_type in macro_types

    if is_macro:
        general_rules = (
            "You are writing a Macro Report. Structure the report as you see fit using your own headings and subheadings. "
            "However, you MUST start with an 'Executive Summary' (Macro View and Key Findings). "
            "Following that, weave your analysis covering the macro environment, policy context, indicator analysis, "
            "market implications, and structural risks. "
            "At the very bottom, include 'Research Query' (restating the original question) and a 'Disclaimer'. "
            "CRITICAL: You MUST include every chart from the `chart_ids` list in your markdown using the syntax `<!-- CHART:id -->`. "
            "Place each chart marker immediately after the paragraph that discusses its data."
        )
    else:
        general_rules = (
            "You are writing an Equity Report. Structure the report as you see fit using your own headings and subheadings. "
            "However, you MUST start with an 'Executive Summary' (The 'Call', Price Target Implications, and Key Findings). "
            "Following that, weave your analysis covering the investment thesis, catalysts, financial analysis, "
            "valuation, and investment risks. "
            "At the very bottom, include 'Research Query' (restating the original question) and a 'Disclaimer'. "
            "CRITICAL: You MUST include every chart from the `chart_ids` list in your markdown using the syntax `<!-- CHART:id -->`. "
            "Place each chart marker immediately after the paragraph that discusses its data."
        )

    return json.dumps({
        "general_rules": general_rules,
        "query_type": query_type,
        "chart_ids": chart_ids,
        "recommended_word_count": "1000+ words"
    })


@tool
def write_research_report(
    markdown: str,
    charts_json_path: str = "",
    data_sources: str = "[]",
    original_query: str = "",
    job_id: str = "",
    title: str = "",
    executive_summary: str = "",
    analysis_type: str = "custom"
) -> str:
    """
    Validate and save the LLM-written markdown narrative as report.json.

    YOU write the complete markdown narrative yourself before calling this tool.
    This tool only: reads charts.json from disk, embeds chart definitions into
    the report, validates mandatory elements, and saves report.json.

    Args:
        markdown: The COMPLETE markdown narrative you have written. Must include:
                  - ## Executive Summary (at the top, 2-3 sentences with specific numbers)
                  - Your own analysis sections with custom headings and subheadings
                  - <!-- CHART:id --> markers placed inline after the text that
                    references each chart (NOT clustered at the bottom)
                  - ## Research Query (verbatim original query, moved to the bottom)
                  - ## Disclaimer (MUST contain "does not constitute financial advice"
                    AND "Past performance is not indicative of future results")
        charts_json_path: Path to charts.json on disk (e.g. "outputs/abc123/charts.json")
        data_sources: JSON string containing DataSource dicts with small metadata only
                      (provider, description, tickers/series_ids, date_range, row_count)
        original_query: The user's original research question
        job_id: Unique job identifier
        title: Descriptive report title (derived from query + key finding)
        executive_summary: 2-3 sentence plain-text summary (same content as the
                           ## Executive Summary section in markdown)
        analysis_type: One of: "correlation_analysis", "trend_analysis",
                       "sector_comparison", "macro_indicator",
                       "earnings_analysis", "custom"

    Returns:
        JSON string with:
        - report_path: Absolute path where report.json was saved
        - chart_count: Number of <!-- CHART:id --> markers found in markdown
        - word_count: Approximate word count of markdown
        - validation_issues: List of non-blocking warnings (may be empty)
    """
    if not charts_json_path.strip():
        charts_json_path = _LAST_REPORT_CONTEXT["charts_json_path"]
    if not original_query.strip():
        original_query = _LAST_REPORT_CONTEXT["original_query"]
    if not job_id.strip():
        job_id = _extract_job_id_from_path(charts_json_path) or _LAST_REPORT_CONTEXT["job_id"]

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
        if isinstance(parsed, list):
            charts_on_disk = {item["name"]: item for item in parsed if isinstance(item, dict) and "name" in item}
        elif isinstance(parsed, dict):
            charts_on_disk = parsed
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        charts_on_disk = {}

    charts_on_disk = _normalize_chart_definitions(charts_on_disk)

    # -------------------------------------------------------------------------
    # 2. Append footer to the LLM-written markdown
    # -------------------------------------------------------------------------
    # (Footer has been removed per user request)

    # -------------------------------------------------------------------------
    # 3. Build DataSource objects
    # -------------------------------------------------------------------------
    ds_objects: list[DataSource] = []
    for ds in data_sources:
        try:
            ds_objects.append(DataSource(**ds))
        except Exception:
            ds_objects.append(DataSource(
                provider=ds.get("provider", "Unknown"),
                description=ds.get("description", "")
            ))

    # -------------------------------------------------------------------------
    # 4. Derive title and executive_summary from markdown if not supplied
    # -------------------------------------------------------------------------
    if not title.strip():
        title = original_query[:80].strip()

    if not executive_summary.strip():
        # Extract first non-empty line after "## Executive Summary"
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
    chart_ids_in_markdown = re.findall(r'<!--\s*CHART:(\S+?)\s*-->', markdown)
    metadata = ReportMetadata(
        analysis_type=analysis_type,
        chart_count=len(chart_ids_in_markdown),
        word_count=len(markdown.split())
    )

    report = ResearchReport(
        schema_version=1,
        job_id=job_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        query=original_query,
        title=title,
        executive_summary=executive_summary,
        markdown=markdown,
        charts=charts_on_disk,   # full definitions read from disk, not passed through context
        data_sources=ds_objects,
        metadata=metadata
    )

    # -------------------------------------------------------------------------
    # 6. Save to disk with pre-write validation
    # -------------------------------------------------------------------------
    report_path = str((_OUTPUT_BASE_DIR / job_id / "report.json").resolve())
    validation_issues = _save_report(report, report_path)

    return json.dumps({
        "report_path": report_path,
        "chart_count": metadata.chart_count,
        "word_count": metadata.word_count,
        "validation_issues": validation_issues
    })


def _save_report(report: ResearchReport, output_path: str) -> list[str]:
    """
    Validate mandatory elements and write report.json.

    Returns a list of non-blocking validation warnings (empty = all clear).
    The report is saved regardless of warnings — warnings are surfaced to the
    quality analyst for a final decision.
    """
    issues: list[str] = []

    if "does not constitute financial advice" not in report.markdown:
        issues.append("Missing required financial disclaimer in markdown")

    if "Past performance" not in report.markdown:
        issues.append("Missing past performance disclaimer")

    if not report.executive_summary.strip():
        issues.append("Executive summary is empty")

    # Every <!-- CHART:id --> marker must resolve to a key in report.charts
    marker_ids = re.findall(r'<!--\s*CHART:(\S+?)\s*-->', report.markdown)
    for mid in marker_ids:
        if mid not in report.charts:
            issues.append(f"Chart marker <!-- CHART:{mid} --> references unknown chart ID '{mid}'")

    try:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    except Exception as e:
        issues.append(f"Failed to write report.json: {e}")

    return issues


# =============================================================================
# SUBAGENT CONFIGURATION
# =============================================================================

TECHNICAL_WRITER_SUBAGENT = {
    "name": "technical-writer",

    "description": """Use this subagent to write and save the final ResearchReport artifact.

    Delegate when you need to:
    - Write the full markdown research narrative from execution_summary data
    - Embed chart references (<!-- CHART:id -->) inline in the narrative
    - Validate and save report.json

    Pass ONLY: the charts_json_path, execution_summary (full JSON from quant developer, including
    statistical_summary), data_sources metadata (populated with series_ids, date_range, row_count),
    original_query, and job_id.
    Do NOT pass chart data or raw arrays — the technical writer reads charts.json directly.

    The technical writer writes ALL prose itself. Do not expect the tool to generate content
    from execution_summary — the LLM writes every section with unique, cited analysis.""",

    "system_prompt": """# ROLE
You are the Technical Writer. You synthesize research reports by reading `charts.json` and `execution_summary`, then writing a complete markdown narrative.

# CORE TOOLS
1. `plan_report_structure`: Discover chart IDs from `charts.json`. Call this FIRST.
2. `write_research_report`: Save your finalized markdown to `report.json`.

# WORKFLOW
1. **Plan:** Call `plan_report_structure`. Note the available `chart_ids` and the `general_rules`.
2. **Draft:** Write the full markdown narrative in your response, following the general rules provided by `plan_report_structure`. The `execution_summary` contains a
   `statistical_summary` field: 1-2 paragraphs of dense computed numbers from the quant developer.
   READ this carefully and weave every specific number into the relevant analysis sections —
   exact slopes, r values, peak dates, deltas, p-values, etc. Do not paraphrase vaguely;
   cite the actual computed values in parentheticals (e.g., "slope of -0.05 pp/month", "r = -0.44, p < 0.001").
   - Disclaimer must include: "does not constitute financial advice" and "Past performance is not indicative of future results".
   - Make sure to place the "Research Query" and "Disclaimer" at the very bottom.
3. **Save:** Call `write_research_report` exactly once with this shape:
   - `markdown`
   - `charts_json_path`
   - `data_sources`
   - `original_query`
   - `job_id`
   - optional: `title`, `executive_summary`, `analysis_type`

# RULES
- **YOU write the prose.** The tool only saves it.
- **No data through context:** Read `charts.json` through the provided report tools only.
- **No shell/filesystem tools:** They are blocked for this subagent.
- **Inline Charts:** CRITICAL! Place `<!-- CHART:id -->` markers immediately after the referencing text. You MUST embed all provided `chart_ids`.
- **Word Count:** Aim for 1000+ words of dense, analytical content in investment bank style.
- **No fallback thrashing:** If `write_research_report` returns an argument error, call it again with the exact required fields above. Do not try `read_file` or `execute`.
""",

    "tools": [plan_report_structure, write_research_report],

    "model": "google_genai:gemini-3.1-flash-lite-preview",

    "skills": [str(_BACKEND_DIR / "skills" / "technical-writer")]
}
