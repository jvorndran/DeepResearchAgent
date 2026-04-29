"""
Quality Analyst Subagent (Deep Agents)

The Quality Analyst performs final human-oriented review on generated reports
(substance, alignment with the research task, residual compliance read) and
approves or rejects for delivery. Automated schema and chart-marker checks run in
technical-writer via validate_research_report_file before handoff.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool

from .report_artifacts import chart_marker_ids, load_report_json


def _truncate(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[truncated for review]"


def _parse_required_fixes(raw: str | list[str]) -> list[str]:
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except json.JSONDecodeError:
            return [raw] if raw.strip() else []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return [str(raw)]


def _load_sibling_execution_summary(report_path: Path) -> dict[str, object]:
    """Return a compact quant summary from execution_summary.json when available."""
    summary_path = report_path.with_name("execution_summary.json")
    if not summary_path.is_file():
        return {
            "status": "missing",
            "path": str(summary_path),
            "note": "No sibling execution_summary.json was found.",
        }

    try:
        parsed = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "error",
            "path": str(summary_path),
            "error": str(exc),
        }

    if not isinstance(parsed, dict):
        return {
            "status": "error",
            "path": str(summary_path),
            "error": "Expected execution_summary.json to contain a JSON object.",
        }

    compact: dict[str, object] = {
        "status": "success",
        "path": str(summary_path),
    }
    for key in (
        "statistical_summary",
        "statistical_text",
        "brief_analysis_summary",
        "chart_ids",
    ):
        value = parsed.get(key)
        if value is not None:
            if key == "chart_ids" and isinstance(value, list):
                compact[key] = [str(chart_id) for chart_id in value]
            elif isinstance(value, (dict, list)):
                compact[key] = _truncate(json.dumps(value, ensure_ascii=False), 4000)
            else:
                compact[key] = _truncate(str(value), 4000)
    return compact


@tool
def load_report_for_review(report_path: str) -> str:
    """
    Load the final report artifact into compact review text.

    Args:
        report_path: Absolute path to report.json.

    Returns:
        JSON string with title, query, executive_summary, markdown excerpt,
        chart markers, chart ids, data source metadata, and a compact sibling
        execution_summary.json review packet when present.
    """
    path = Path(report_path)
    if path.name != "report.json":
        return json.dumps(
            {
                "status": "error",
                "report_path": report_path,
                "error": "Expected the final report.json artifact. Do not review charts.json, execution_summary.json, or output directories with this tool.",
            }
        )
    if path.exists() and not path.is_file():
        return json.dumps(
            {
                "status": "error",
                "report_path": report_path,
                "error": "Expected report_path to be a file, but received a directory.",
            }
        )

    data, error = load_report_json(report_path)
    if error:
        return json.dumps(
            {
                "status": "error",
                "report_path": report_path,
                "error": error,
            }
        )

    markdown = data.get("markdown", "")
    charts = data.get("charts", [])
    chart_ids: list[str] = []
    if isinstance(charts, list):
        for chart in charts:
            if isinstance(chart, dict) and isinstance(chart.get("id"), str):
                chart_ids.append(chart["id"])
    elif isinstance(charts, dict):
        chart_ids = [str(chart_id) for chart_id in charts.keys()]

    return json.dumps(
        {
            "status": "success",
            "report_path": report_path,
            "query": data.get("query", ""),
            "title": data.get("title", ""),
            "executive_summary": data.get("executive_summary", ""),
            "markdown": _truncate(str(markdown)),
            "chart_markers": chart_marker_ids(str(markdown)),
            "chart_ids": chart_ids,
            "data_sources": data.get("data_sources", []),
            "metadata": data.get("metadata", {}),
            "execution_summary": _load_sibling_execution_summary(path),
        }
    )


@tool
def submit_quality_decision(
    decision: str,
    report_path: str,
    notes: str = "",
    reason: str = "",
    required_fixes: str | list[str] = "",
) -> str:
    """
    Terminal quality decision: approve or reject the report for delivery.

    Call exactly once after substantive review. Use decision 'approve' with
    notes when satisfied; use 'reject' with reason and required_fixes when the
    report must be revised upstream.

    Args:
        decision: 'approve' or 'reject' (also accepts 'approved' / 'rejected').
        report_path: Absolute path to report.json (always pass)
        notes: Short approval notes (for approve)
        reason: Primary rejection reason (for reject)
        required_fixes: Concrete fixes required — JSON array string or list of strings (for reject)

    Returns:
        JSON string: approved payload with ready_for_upload true, or rejected payload with
        required_fixes and ready_for_upload false.
    """
    d = decision.strip().lower()
    if d in ("approve", "approved"):
        return json.dumps(
            {
                "status": "approved",
                "report_path": report_path,
                "notes": notes,
                "ready_for_upload": True,
            }
        )
    if d in ("reject", "rejected"):
        fixes = _parse_required_fixes(required_fixes)
        return json.dumps(
            {
                "status": "rejected",
                "report_path": report_path,
                "reason": reason,
                "required_fixes": fixes,
                "ready_for_upload": False,
            }
        )
    return json.dumps(
        {
            "status": "error",
            "message": "decision must be 'approve' or 'reject'",
            "report_path": report_path,
        }
    )


QUALITY_ANALYST_DESCRIPTION = """Use this subagent for the final approve/reject decision on a report.

    Delegate when you need to:
    - Confirm the report answers the user's question and matches execution_summary / data
    - Spot-check residual compliance (no disguised investment advice in prose)
    - Judge narrative quality and analytic soundness

    Static schema and chart-marker checks (plus optional disclaimer/chart auto-patch) are
    already run by the technical-writer via `validate_research_report_file` before handoff.
    Final compliance judgment on prose is your responsibility.
    Nothing reaches the user without your approval."""

QUALITY_ANALYST_SYSTEM_PROMPT = """# ROLE
You are the Quality Analyst — final reviewer before a report goes to the user.

# REVIEW FOCUS

## Critical (reject)
- **Accuracy:** Major contradictions between prose and `execution_summary` / cited numbers.
- **Consistency claims:** If the user asked whether something was "consistent", "always", or "guaranteed", reject reports that answer "yes" or "consistent" while also citing material counterexamples such as near-zero or negative period/regime outcomes.
- **Date/range fidelity:** Reject reports whose title, executive summary, or body shifts a user-requested time range or conflicts with data source `date_range` metadata (for example "since 2000" becoming "2001-...") unless the report explicitly explains that the narrower range applies only to a derived metric such as YoY growth after lookback loss.
- **Task fit:** Report does not address the original query or omits required analysis.
- **Compliance (read):** Investment advice tone, imperative buy/sell/hold language, or predictive guarantees in the markdown — verify the prose, not only tool output.

## OK to approve when
- The report is coherent, well-supported, and appropriate for the user request.
- You are satisfied there are no material errors or compliance red flags on a **read** of the markdown.

# TOOLS
- `load_report_for_review`: Read only the final `report.json` artifact into compact review text.
- `submit_quality_decision`: Terminal decision. Call exactly once after review, then stop.

# WORKFLOW
1. Call `load_report_for_review(report_path)` exactly once using the absolute path you were given.
2. If the returned status is `"error"` → `submit_quality_decision` with `decision='reject'`, the same `report_path`, the tool error as `reason`, and concrete `required_fixes`. STOP.
3. Review the returned title, executive summary, markdown, chart markers, data source metadata, and `execution_summary` packet against the task.
4. If material issues remain → `submit_quality_decision` with `decision='reject'`, `report_path`, `reason`, and `required_fixes`. STOP.
5. If satisfied → `submit_quality_decision` with `decision='approve'`, `report_path`, and `notes`. STOP.

**Terminal:** No further tool calls after `submit_quality_decision`.

# CRITICAL RULES
- **Silent review:** Do not narrate your review, checklist, tables, number-by-number audit, or final approval/rejection explanation in assistant text. Keep reasoning private and put only compact `notes`, `reason`, and `required_fixes` inside `submit_quality_decision`.
- **Terminal brevity:** After `submit_quality_decision` returns, emit at most one terse sentence such as `Approved.` or `Rejected.` and stop. Never include markdown tables, verification summaries, chart lists, or copied report paths after the terminal tool result.
- **Paths:** Always pass absolute `report_path`.
- **Single artifact:** Never call `load_report_for_review` on `charts.json`, `execution_summary.json`, or an output directory. The `load_report_for_review(report.json)` result already includes the sibling execution summary review packet when available.
- **Tool discipline:** Deep Agents may expose standard filesystem or shell tools on this graph. You must not use them — only `load_report_for_review` and `submit_quality_decision`.
"""


@lru_cache(maxsize=1)
def _quality_analyst_agent():
    return create_agent(
        "deepseek:deepseek-chat",
        system_prompt=QUALITY_ANALYST_SYSTEM_PROMPT,
        tools=[load_report_for_review, submit_quality_decision],
        name="quality-analyst",
    )


def _invoke_quality_analyst(state: dict) -> dict:
    return _quality_analyst_agent().invoke(state)


async def _ainvoke_quality_analyst(state: dict) -> dict:
    return await _quality_analyst_agent().ainvoke(state)


QUALITY_ANALYST_SUBAGENT = {
    "name": "quality-analyst",
    "description": QUALITY_ANALYST_DESCRIPTION,
    # Use a compiled agent instead of a declarative Deep Agents subagent. Declarative
    # subagents receive the default filesystem/shell middleware, which lets QA drift
    # into open-ended `execute` probes after it has enough evidence to decide.
    "runnable": RunnableLambda(
        _invoke_quality_analyst,
        afunc=_ainvoke_quality_analyst,
        name="quality-analyst",
    ),
}
