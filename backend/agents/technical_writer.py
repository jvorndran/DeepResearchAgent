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
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from core.report_schema import ResearchReport, DataSource, ReportMetadata

# Absolute output base dir — avoids CWD ambiguity when running as a subagent
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_OUTPUT_BASE_DIR = Path(os.getenv("OUTPUT_DIR", str(_BACKEND_DIR / "outputs")))


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
        if isinstance(charts_data, list):
            chart_ids = [item["name"] for item in charts_data if isinstance(item, dict) and "name" in item]
        else:
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
    markdown: str,
    charts_json_path: str,
    data_sources: List[Dict[str, Any]],
    original_query: str,
    job_id: str,
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
                  - ## Executive Summary (2-3 sentences with specific numbers)
                  - ## Research Query (verbatim original query)
                  - ## Data Sources (provider, series IDs, date ranges, row counts)
                  - Content sections (each unique, citing specific statistics)
                  - <!-- CHART:id --> markers placed inline after the text that
                    references each chart (NOT clustered at the bottom)
                  - ## Methodology
                  - ## Limitations
                  - ## Disclaimer (MUST contain "does not constitute financial advice"
                    AND "Past performance is not indicative of future results")
        charts_json_path: Path to charts.json on disk (e.g. "outputs/abc123/charts.json")
        data_sources: List of DataSource dicts — small metadata only
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
        - report_path: Path where report.json was saved
        - chart_count: Number of <!-- CHART:id --> markers found in markdown
        - word_count: Approximate word count of markdown
        - validation_issues: List of non-blocking warnings (may be empty)
    """
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

    # -------------------------------------------------------------------------
    # 2. Append footer to the LLM-written markdown
    # -------------------------------------------------------------------------
    footer = (
        "\n\n---\n\n"
        f"*Generated by Deep Research Agent*  \n"
        f"*Job ID: {job_id}*  \n"
        f"*Generated at: {datetime.now(timezone.utc).isoformat()}*"
    )
    if "Generated by Deep Research Agent" not in markdown:
        markdown = markdown.rstrip() + footer

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
    report_path = str(_OUTPUT_BASE_DIR / job_id / "report.json")
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

    "description": """Use this subagent to write and save the final ResearchReport artifact.

    Delegate when you need to:
    - Write the full markdown research narrative from execution_summary data
    - Embed chart references (<!-- CHART:id -->) inline in the narrative
    - Validate and save report.json

    Pass ONLY: the charts_json_path, execution_summary (compact stdout JSON from quant developer),
    data_sources metadata, original_query, and job_id.
    Do NOT pass chart data or raw arrays — the technical writer reads charts.json directly.

    The technical writer writes ALL prose itself. Do not expect the tool to generate content
    from execution_summary — the LLM writes every section with unique, cited analysis.""",

    "system_prompt": """You are the Technical Writer for a financial research platform.

You are the SOLE assembler of the ResearchReport artifact. No other agent touches report.json.
The quant developer produces charts.json and an execution_summary; the data engineer produces CSV files.
You read those artifacts, then **YOU WRITE the complete markdown narrative yourself**, and call
`write_research_report` to validate and save it.

## The Golden Rule

**You write every word of the report.** The `write_research_report` tool does NOT generate content —
it only validates structure and saves. If you pass a thin `execution_summary` to the tool and expect
it to fill in sections, the report will be empty and repetitive. Every section must contain unique
prose you composed based on the execution_summary data.

## What You Receive From the Orchestrator

- `charts_json_path`: Path to charts.json on disk (e.g. `outputs/abc123/charts.json`)
- `execution_summary`: Compact JSON from the quant developer — contains all statistics you need
- `data_sources`: Small metadata list (provider, series IDs, date ranges, row counts)
- `original_query` and `job_id`

## Step 1: Inspect chart IDs

Call `plan_report_structure(query_type, charts_json_path, execution_summary, original_query)` to
discover the chart IDs available in charts.json. Note the IDs — you will need them for inline markers.

## Step 2: Write the complete markdown narrative

Write the full markdown **in your response text before calling any tool**. Every section must be
unique — never copy the same sentence into two sections. Cite the specific numbers from
execution_summary inline in parentheticals.

### Required sections (in this order)

```markdown
## Executive Summary

[2-3 sentences. State the single most important finding with the exact statistic.
Example: "US real GDP growth and unemployment have a strong inverse relationship
(Pearson r = -0.89, p < 0.001) over 2004–2024. When GDP contracts by 1 percentage point,
unemployment rises by approximately 0.77 percentage points (Okun coefficient). The relationship
is tightest during recessions (2008–2009, 2020) when both series moved sharply."]

## Research Query

[Verbatim original query — no paraphrasing]

## Data Sources

[Bullet list: provider, series IDs, date range, row counts]
- **FRED (Federal Reserve Economic Data)**: Real GDP Growth Rate (GDPC1) and Unemployment Rate
  (UNRATE), Q1 2004 – Q4 2024 (80 quarterly observations)

## [Analysis section title — unique to this query type]

[2-4 paragraphs analyzing the data. Each paragraph covers a distinct aspect.
Cite specific numbers. Do NOT copy text from another section.]

<!-- CHART:chart_id_1 -->

[Continue analysis — next aspect. Different topic from the paragraph above.]

## [Second analysis section]

[Different content. Address a different dimension of the findings.]

<!-- CHART:chart_id_2 -->

## Methodology

[How the data was collected and analyzed. Mention the specific series, time period,
and analytical methods (e.g. Pearson correlation, OLS regression, Okun's Law model).]

## Limitations

[Specific limitations of THIS analysis — not generic boilerplate.
Example: "This analysis uses quarterly data; higher-frequency monthly data would
reveal faster labor market responses to GDP contractions."]

## Disclaimer

**IMPORTANT DISCLAIMER**: This report is for informational purposes only and does not
constitute financial advice. All analysis is based on historical data.
Past performance is not indicative of future results.
```

### Chart placement rules

- Place `<!-- CHART:id -->` on its own line immediately **after** the paragraph that references it
- Never cluster all charts at the bottom
- Use exactly the IDs returned by `plan_report_structure` — no invented IDs

### Anti-patterns (these will make the report fail quality review)

❌ Copying the same sentence from execution_summary into every section
❌ Sections with only 1 sentence
❌ Generic boilerplate that could apply to any report
❌ Inventing statistics not present in execution_summary
❌ Predictive statements ("will increase", "should buy")
❌ All `<!-- CHART:id -->` markers at the bottom

## Step 3: Call write_research_report

Once your markdown is complete, call:

```
write_research_report(
    markdown=<your complete markdown>,
    charts_json_path=<path>,
    data_sources=<list>,
    original_query=<query>,
    job_id=<id>,
    title=<descriptive title>,
    executive_summary=<plain text version of executive summary>,
    analysis_type=<query_type from step 1>
)
```

## Step 4: Report results

After the tool returns, report the `report_path`, `chart_count`, `word_count`, and any
`validation_issues` to the orchestrator.

## Quality bar

A good report has:
- Word count > 400
- chart_count ≥ 1 (every available chart referenced in context)
- No validation_issues
- Every section contains unique prose specific to THIS query's data
- Executive summary names the exact statistic (r-value, coefficient, percentage)""",

    "tools": [plan_report_structure, write_research_report],

    "model": "google_genai:gemini-3-flash-preview"
}