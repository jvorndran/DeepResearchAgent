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

Key Principle: No other agent touches report.json. The quant developer and data
engineer produce their own artifacts (charts.json, CSV files); the technical writer
reads those artifacts and assembles the complete report independently.
"""

from typing import Dict, Any, List
from langchain_core.tools import tool
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from backend.core.report_schema import ResearchReport, DataSource, ReportMetadata


# =============================================================================
# TECHNICAL WRITER TOOLS
# =============================================================================

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
        - outline: List of section dicts (title, description, chart_id or null)
        - query_type: Echoed back
        - chart_ids: List of chart IDs discovered from charts.json
        - recommended_sections: Count
    """
    # Load chart IDs from disk — never from caller context
    chart_ids: list[str] = []
    try:
        raw = Path(charts_json_path).read_text(encoding="utf-8")
        charts_data = json.loads(raw)
        chart_ids = list(charts_data.keys())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        chart_ids = []

    # Base mandatory sections always present
    base_intro = [
        {"title": "Executive Summary", "description": "2-3 sentence overview of key findings", "chart_id": None},
        {"title": "Research Query", "description": "Original user question restated", "chart_id": None},
        {"title": "Data Sources", "description": "APIs, tickers, date ranges, row counts", "chart_id": None},
    ]

    base_footer = [
        {"title": "Methodology", "description": "Data collection and analysis approach", "chart_id": None},
        {"title": "Limitations", "description": "What the analysis does not cover", "chart_id": None},
        {"title": "Disclaimer", "description": "Financial disclaimer and past performance notice", "chart_id": None},
    ]

    # Query-type-specific middle sections
    type_sections: dict[str, list[dict]] = {
        "correlation_analysis": [
            {"title": "Correlation Findings", "description": "Pearson/Spearman coefficients and significance", "chart_id": None},
            {"title": "Time Series Trends", "description": "How each variable moved over time", "chart_id": None},
            {"title": "Scatter Analysis", "description": "Joint distribution and outliers", "chart_id": None},
        ],
        "trend_analysis": [
            {"title": "Trend Overview", "description": "Direction and magnitude of trends", "chart_id": None},
            {"title": "Key Inflection Points", "description": "Notable shifts in direction", "chart_id": None},
            {"title": "Comparative Performance", "description": "Benchmarking against peers or indices", "chart_id": None},
        ],
        "sector_comparison": [
            {"title": "Sector Overview", "description": "High-level sector landscape", "chart_id": None},
            {"title": "Metric Comparison", "description": "Side-by-side key metrics", "chart_id": None},
            {"title": "Relative Positioning", "description": "Leaders and laggards within sector", "chart_id": None},
        ],
        "macro_indicator": [
            {"title": "Macro Environment", "description": "Current macro context", "chart_id": None},
            {"title": "Indicator Analysis", "description": "Trends in selected macro indicators", "chart_id": None},
            {"title": "Asset Correlation", "description": "How macro indicators relate to asset prices", "chart_id": None},
        ],
        "earnings_analysis": [
            {"title": "Earnings Overview", "description": "Revenue, EPS, and margins summary", "chart_id": None},
            {"title": "Quarter-over-Quarter Trends", "description": "Sequential and YoY comparisons", "chart_id": None},
            {"title": "Guidance and Estimates", "description": "Beat/miss history and forward guidance", "chart_id": None},
        ],
        "custom": [
            {"title": "Key Findings", "description": "Primary insights from analysis", "chart_id": None},
            {"title": "Detailed Analysis", "description": "Supporting evidence and statistics", "chart_id": None},
        ],
    }

    middle = type_sections.get(query_type, type_sections["custom"])

    # Distribute discovered chart IDs across middle sections
    chart_queue = list(chart_ids)
    for section in middle:
        if chart_queue:
            section["chart_id"] = chart_queue.pop(0)

    outline = base_intro + middle + base_footer

    return json.dumps({
        "outline": outline,
        "query_type": query_type,
        "chart_ids": chart_ids,
        "recommended_sections": len(outline)
    })


@tool
def write_research_report(
    report_outline: str,
    charts_json_path: str,
    execution_summary: str,
    data_sources: List[Dict[str, Any]],
    original_query: str,
    job_id: str
) -> str:
    """
    Assemble the full ResearchReport from filesystem artifacts and save report.json.

    Call this AFTER plan_report_structure. Reads the full chart definitions
    from charts.json on disk (never from caller context), builds the markdown
    narrative with inline <!-- CHART:id --> markers, validates via Pydantic,
    and saves the complete ResearchReport to outputs/{job_id}/report.json.

    Args:
        report_outline: JSON string returned by plan_report_structure
        charts_json_path: Path to charts.json on disk — the technical writer
                          reads this directly to embed full chart definitions
                          into report.json (never passed through orchestrator context)
        execution_summary: Compact JSON string printed to stdout by the quant
                           developer (e.g. '{"correlation_coefficient": 0.82,
                           "key_finding": "Strong positive correlation", ...}')
        data_sources: List of DataSource dicts — small metadata only
                      (provider, description, tickers, date_range, row_count)
        original_query: The user's original research question
        job_id: Unique job identifier

    Returns:
        JSON string with:
        - report_path: Path where report.json was saved
        - chart_count: Number of <!-- CHART:id --> markers in markdown
        - word_count: Approximate word count of markdown
        - validation_issues: List of non-blocking warnings (may be empty)
    """
    # -------------------------------------------------------------------------
    # 1. Read full chart definitions from disk
    # -------------------------------------------------------------------------
    charts_on_disk: dict = {}
    try:
        raw_charts = Path(charts_json_path).read_text(encoding="utf-8")
        charts_on_disk = json.loads(raw_charts)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        charts_on_disk = {}

    # Build lightweight summaries for narrative use (no data arrays in LLM context)
    chart_summaries: dict[str, dict] = {
        cid: {
            "id": cid,
            "title": cdef.get("title", cid),
            "description": cdef.get("description", ""),
        }
        for cid, cdef in charts_on_disk.items()
    }

    # -------------------------------------------------------------------------
    # 2. Parse execution summary
    # -------------------------------------------------------------------------
    try:
        exec_data: dict = json.loads(execution_summary) if isinstance(execution_summary, str) else execution_summary
    except (json.JSONDecodeError, TypeError):
        exec_data = {"key_finding": str(execution_summary)}

    # -------------------------------------------------------------------------
    # 3. Parse outline
    # -------------------------------------------------------------------------
    try:
        outline_data = json.loads(report_outline) if isinstance(report_outline, str) else report_outline
    except (json.JSONDecodeError, TypeError):
        outline_data = {"outline": [], "query_type": "custom"}

    outline = outline_data.get("outline", [])
    query_type = outline_data.get("query_type", "custom")

    # -------------------------------------------------------------------------
    # 4. Build title and executive summary from execution data
    # -------------------------------------------------------------------------
    title = exec_data.get("title", original_query[:80].strip())
    executive_summary = exec_data.get(
        "executive_summary",
        exec_data.get("key_finding", f"Analysis of: {original_query}")
    )

    # -------------------------------------------------------------------------
    # 5. Build markdown body section by section
    # -------------------------------------------------------------------------
    md_sections: list[str] = []

    for section in outline:
        section_title = section.get("title", "")
        chart_id = section.get("chart_id")

        if section_title == "Executive Summary":
            md_sections.append(f"## Executive Summary\n\n{executive_summary}")

        elif section_title == "Research Query":
            md_sections.append(f"## Research Query\n\n{original_query}")

        elif section_title == "Data Sources":
            ds_lines = []
            for ds in data_sources:
                tickers = ", ".join(ds.get("tickers") or ds.get("series_ids") or [])
                ticker_str = f" — tickers: {tickers}" if tickers else ""
                date_range = ds.get("date_range") or {}
                date_str = (
                    f" ({date_range.get('start', '')} to {date_range.get('end', '')})"
                    if date_range else ""
                )
                row_count = ds.get("row_count")
                row_str = f", {row_count} rows" if row_count else ""
                ds_lines.append(
                    f"- **{ds.get('provider', 'Unknown')}**: "
                    f"{ds.get('description', '')}{ticker_str}{date_str}{row_str}"
                )
            sources_text = "\n".join(ds_lines) if ds_lines else "- See execution results for data source details."
            md_sections.append(f"## Data Sources\n\n{sources_text}")

        elif section_title == "Disclaimer":
            md_sections.append(
                "## Disclaimer\n\n"
                "**IMPORTANT DISCLAIMER**: This report is for informational purposes only and does not "
                "constitute financial advice. All analysis is based on historical data. "
                "Past performance is not indicative of future results."
            )

        elif section_title == "Limitations":
            md_sections.append(
                "## Limitations\n\n"
                "- Analysis based on historical data only\n"
                "- External factors not controlled for\n"
                "- Results reflect correlation, not causation\n"
                "- Data accuracy depends on source APIs"
            )

        elif section_title == "Methodology":
            md_sections.append(
                "## Methodology\n\n"
                "### Data Collection\n\n"
                "Data was fetched from financial APIs covering the specified time range "
                "and validated for completeness.\n\n"
                "### Analysis Approach\n\n"
                "Standard quantitative methods were applied including correlation analysis, "
                "time series decomposition, and summary statistics using pandas/numpy/scipy."
            )

        else:
            # Generic content section — pull relevant findings from exec_data
            key = section_title.lower().replace(" ", "_")
            findings = exec_data.get(key, exec_data.get("key_finding", "See charts and data sources for details."))

            content = f"## {section_title}\n\n{findings}"

            if chart_id and chart_id in chart_summaries:
                summary = chart_summaries[chart_id]
                chart_desc = summary.get("description", "")
                if chart_desc:
                    content += f"\n\n{chart_desc}"
                content += f"\n\n<!-- CHART:{chart_id} -->"

            md_sections.append(content)

    # -------------------------------------------------------------------------
    # 6. Append footer
    # -------------------------------------------------------------------------
    footer = (
        "\n\n---\n\n"
        f"*Generated by Deep Research Agent*  \n"
        f"*Job ID: {job_id}*  \n"
        f"*Generated at: {datetime.now(timezone.utc).isoformat()}*"
    )
    markdown = "\n\n".join(md_sections) + footer

    # -------------------------------------------------------------------------
    # 7. Build DataSource objects
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
    # 8. Assemble and validate ResearchReport (Pydantic validates chart shapes)
    # -------------------------------------------------------------------------
    chart_ids_in_markdown = re.findall(r'<!--\s*CHART:(\S+?)\s*-->', markdown)
    metadata = ReportMetadata(
        analysis_type=query_type,
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
    # 9. Save to disk with pre-write validation
    # -------------------------------------------------------------------------
    report_path = f"outputs/{job_id}/report.json"
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

    if "Generated by Deep Research Agent" not in report.markdown:
        issues.append("Missing footer in markdown")

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

    "description": """Use this subagent to assemble the final ResearchReport artifact.

    Delegate when you need to:
    - Plan report structure based on query type (technical writer reads chart IDs from disk)
    - Assemble report.json from charts.json and execution summary
    - Write markdown with inline <!-- CHART:id --> markers
    - Validate and save the complete ResearchReport

    Pass ONLY: the charts_json_path, execution_summary (compact stdout JSON),
    data_sources metadata, original_query, and job_id.
    Do NOT pass chart data or raw arrays — the technical writer reads charts.json directly.""",

    "system_prompt": """You are the Technical Writer for a financial research platform.

You are the SOLE assembler of the ResearchReport artifact. No other agent touches report.json.
The quant developer produces charts.json; the data engineer produces CSV files.
You read those artifacts directly from the filesystem and assemble the complete report.

## Output Artifact

You produce `outputs/{job_id}/report.json` — a `ResearchReport` schema v1 object containing:
- The full markdown narrative with inline `<!-- CHART:id -->` markers
- The complete chart definitions (read from charts.json, embedded verbatim)
- Data source metadata
- Report metadata (analysis_type, chart_count, word_count)

## What You Receive From the Orchestrator

- `charts_json_path`: Path to charts.json on disk (e.g. `outputs/abc123/charts.json`)
- `execution_summary`: The compact JSON string printed to stdout by the quant developer
- `data_sources`: Small metadata list (provider, tickers, date ranges, row counts)
- `original_query` and `job_id`c

You do NOT receive chart data arrays through context. You read them from disk yourself.

## Mandatory Report Elements

Every report MUST contain:
1. **Title** — descriptive, derived from the query
2. **Executive Summary** — 2-3 sentence overview of key findings
3. **Original Query** — restated verbatim
4. **Data Sources** — provider, tickers/series, date range, row counts
5. **Findings with cited numbers** — every statistic from execution_summary
6. **Methodology** — data collection and analysis approach
7. **Limitations** — what the analysis does not cover
8. **Financial Disclaimer** — "does not constitute financial advice"
9. **Past Performance Notice** — "Past performance is not indicative of future results"
10. **Footer** — job ID and generation timestamp

## Chart Placement

Place `<!-- CHART:id -->` on its own line immediately **after** the paragraph that
introduces the finding the chart illustrates. Never cluster all charts at the bottom.

```markdown
The correlation is strong (r=0.82, p < 0.001), with CapEx acting as a ~2 quarter
leading indicator for wafer volume growth.

<!-- CHART:correlation_scatter -->

This relationship weakened during 2023 when supply constraints normalized...
```

Use only the ID in the marker — never embed the type.

## Tools Available

- **plan_report_structure**: Call FIRST — reads chart IDs from charts_json_path on disk,
  returns a section outline with chart placement
- **write_research_report**: Call SECOND — reads full chart definitions from charts_json_path,
  assembles ResearchReport, validates via Pydantic, saves report.json

## Workflow

1. Call `plan_report_structure(query_type, charts_json_path, execution_summary, original_query)`
2. Call `write_research_report(report_outline, charts_json_path, execution_summary, data_sources, original_query, job_id)`
3. Report the saved `report_path`, `chart_count`, `word_count`, and any `validation_issues`

## Writing Style

- Lead with insights, not raw numbers (numbers belong in cited parentheticals)
- Explain correlations, trends, and patterns in plain English
- Avoid jargon; explain acronyms on first use
- Structure follows content — section order serves the narrative

## What NOT to Do

- Never invent statistics not present in execution_summary
- Never make predictive statements ("will increase", "should buy")
- Never omit the financial disclaimer or past performance notice
- Never request chart data arrays from the orchestrator — read charts_json_path directly
- Never put all charts at the bottom of the report

Remember: You are the final assembler. The report.json you produce is the single
canonical artifact for this research job.""",

    "tools": [plan_report_structure, write_research_report],

    "model": "google-genai:gemini-3-flash-preview"
}
