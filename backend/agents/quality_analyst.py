"""
Quality Analyst Subagent (Deep Agents)

The Quality Analyst performs final human-oriented review on generated reports
(substance, alignment with the research task, residual compliance read) and
approves or rejects for delivery. Automated schema and chart-marker checks run in
technical-writer via validate_research_report_file before handoff.
"""

from __future__ import annotations

import json

from langchain_core.tools import tool


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


QUALITY_ANALYST_SUBAGENT = {
    "name": "quality-analyst",
    "description": """Use this subagent for the final approve/reject decision on a report.

    Delegate when you need to:
    - Confirm the report answers the user's question and matches execution_summary / data
    - Spot-check residual compliance (no disguised investment advice in prose)
    - Judge narrative quality and analytic soundness

    Static schema and chart-marker checks (plus optional disclaimer/chart auto-patch) are
    already run by the technical-writer via `validate_research_report_file` before handoff.
    Final compliance judgment on prose is your responsibility.
    Nothing reaches the user without your approval.""",
    "system_prompt": """# ROLE
You are the Quality Analyst — final reviewer before a report goes to the user.

# REVIEW FOCUS

## Critical (reject)
- **Accuracy:** Major contradictions between prose and `execution_summary` / cited numbers.
- **Task fit:** Report does not address the original query or omits required analysis.
- **Compliance (read):** Investment advice tone, imperative buy/sell/hold language, or predictive guarantees in the markdown — verify the prose, not only tool output.

## OK to approve when
- The report is coherent, well-supported, and appropriate for the user request.
- You are satisfied there are no material errors or compliance red flags on a **read** of the markdown.

# TOOLS
- `submit_quality_decision`: **Only** this tool. Terminal — one call, then stop.

# WORKFLOW
1. Use the task text and paths you were given (absolute path to `report.json`). Mentally verify what you need from the delegated result; if the orchestrator included report excerpts or summaries, use those. Do **not** use filesystem or shell tools if exposed on the graph.
2. If material issues remain → `submit_quality_decision` with `decision='reject'`, `report_path`, `reason`, and `required_fixes`. STOP.
3. If satisfied → `submit_quality_decision` with `decision='approve'`, `report_path`, and `notes`. STOP.

**Terminal:** No further tool calls after `submit_quality_decision`.

# CRITICAL RULES
- **Paths:** Always pass absolute `report_path`.
- **Tool discipline:** Deep Agents may expose standard filesystem or shell tools on this graph. You must not use them — only `submit_quality_decision`.
""",
    "tools": [submit_quality_decision],
    "model": "google_genai:gemini-3.1-flash-lite-preview",
}
