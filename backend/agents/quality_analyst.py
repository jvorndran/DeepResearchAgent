"""
Quality Analyst Subagent (Deep Agents)

The Quality Analyst performs final quality checks on generated reports.
It validates formatting, ensures compliance with financial disclosure requirements,
and verifies chart references before approve/reject.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from langchain_core.tools import tool
from pydantic import ValidationError

from core.report_schema import ResearchReport

from .report_artifacts import DISCLAIMER_SUBSTRINGS, chart_marker_ids, load_report_json

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _format_validation_dict(report: ResearchReport) -> dict:
    schema_errors: list[str] = []
    missing_elements: list[str] = []
    markdown = report.markdown

    if DISCLAIMER_SUBSTRINGS["financial_advice"] not in markdown:
        missing_elements.append(
            "Financial disclaimer ('does not constitute financial advice')"
        )
    if DISCLAIMER_SUBSTRINGS["past_performance"] not in markdown:
        missing_elements.append("Past performance notice")

    if not report.executive_summary.strip():
        missing_elements.append("Executive summary (empty)")

    if report.query not in markdown and report.query[:40] not in markdown:
        missing_elements.append("Original query not found in markdown")

    valid = len(schema_errors) == 0 and len(missing_elements) == 0
    return {"valid": valid, "schema_errors": schema_errors, "missing_elements": missing_elements}


def _compliance_dict(markdown: str) -> dict:
    violations: list[dict] = []

    prediction_patterns = [
        (r"(should|must|need to) (buy|sell|invest|trade|acquire|divest)", "Investment advice"),
        (r"(recommend|suggestion|advice):? (buy|sell|hold)", "Investment recommendations"),
    ]

    for pattern, description in prediction_patterns:
        matches = re.findall(pattern, markdown, re.IGNORECASE)
        if matches:
            violations.append(
                {
                    "type": description,
                    "match": matches[0]
                    if isinstance(matches[0], str)
                    else " ".join(matches[0]),
                    "pattern": pattern,
                }
            )

    severity = "critical" if violations else "none"
    return {"compliant": len(violations) == 0, "violations": violations, "severity": severity}


def _charts_dict(report: ResearchReport) -> dict:
    marker_ids = chart_marker_ids(report.markdown)
    defined = list(report.charts.keys())
    broken = [mid for mid in marker_ids if mid not in report.charts]
    return {
        "valid": len(broken) == 0,
        "broken_references": broken,
        "chart_count": len(marker_ids),
        "defined_charts": defined,
    }


def _apply_safe_patches(data: dict, report: ResearchReport) -> tuple[dict, list[str]]:
    """Apply idempotent disclaimer / past-performance / broken-marker patches. Returns (updated_data, changes)."""
    markdown = report.markdown
    changes_made: list[str] = []

    if DISCLAIMER_SUBSTRINGS["financial_advice"] not in markdown:
        markdown += (
            "\n\n**DISCLAIMER**: This report does not constitute financial advice. "
            "All analysis is based on historical data."
        )
        changes_made.append("Appended financial disclaimer")

    if DISCLAIMER_SUBSTRINGS["past_performance"] not in markdown:
        markdown += "\n\n**NOTICE**: Past performance is not indicative of future results."
        changes_made.append("Appended past performance notice")

    defined_charts = set(report.charts.keys())

    def _remove_if_broken(m: re.Match) -> str:
        chart_id = m.group(1)
        if chart_id not in defined_charts:
            changes_made.append(f"Removed broken chart marker <!-- CHART:{chart_id} -->")
            return ""
        return m.group(0)

    new_md = re.sub(r"<!--\s*CHART:(\S+?)\s*-->", _remove_if_broken, markdown)
    if new_md != markdown:
        markdown = new_md

    if not changes_made:
        return data, []

    updated = dict(data)
    updated["markdown"] = markdown
    updated["metadata"] = dict(data.get("metadata", {}))
    updated["metadata"]["word_count"] = len(markdown.split())
    return updated, changes_made


@tool
def run_quality_gate(report_json_path: str, auto_patch: bool = True) -> str:
    """
    Run schema + mandatory markdown + compliance + chart-reference checks in one step.

    When auto_patch is True and compliance passes, applies the same safe auto-fixes
    as the legacy patch_report tool (disclaimers, broken chart markers), then
    re-validates before returning.

    Args:
        report_json_path: Absolute path to report.json
        auto_patch: If True, apply safe patches when compliance is clean

    Returns:
        JSON string with passes_gate, format, compliance, charts, auto_patched,
        patches_applied, and blockers (remaining reasons to reject).
    """
    path = Path(report_json_path)
    data, load_err = load_report_json(report_json_path)
    if load_err or data is None:
        return json.dumps(
            {
                "passes_gate": False,
                "load_error": load_err,
                "format": {},
                "compliance": {},
                "charts": {},
                "auto_patched": False,
                "patches_applied": [],
                "blockers": [load_err or "Unknown load error"],
            }
        )

    try:
        report = ResearchReport(**data)
    except ValidationError as e:
        return json.dumps(
            {
                "passes_gate": False,
                "format": {"valid": False, "schema_errors": [str(e)], "missing_elements": []},
                "compliance": {},
                "charts": {},
                "auto_patched": False,
                "patches_applied": [],
                "blockers": [f"Schema validation failed: {e}"],
            }
        )

    fmt = _format_validation_dict(report)
    comp = _compliance_dict(report.markdown)
    ch = _charts_dict(report)

    def _merge_blockers() -> list[str]:
        out: list[str] = []
        if not comp["compliant"]:
            out.append("compliance violations present")
        if not fmt["valid"]:
            out.extend(fmt["missing_elements"])
        if not ch["valid"]:
            out.append(f"broken chart references: {ch['broken_references']}")
        return out

    passes = bool(fmt["valid"] and comp["compliant"] and ch["valid"])
    if passes:
        return json.dumps(
            {
                "passes_gate": True,
                "format": fmt,
                "compliance": comp,
                "charts": ch,
                "auto_patched": False,
                "patches_applied": [],
                "blockers": [],
            }
        )

    if not auto_patch or not comp["compliant"]:
        return json.dumps(
            {
                "passes_gate": False,
                "format": fmt,
                "compliance": comp,
                "charts": ch,
                "auto_patched": False,
                "patches_applied": [],
                "blockers": _merge_blockers(),
            }
        )

    updated_data, patches = _apply_safe_patches(data, report)
    if not patches:
        return json.dumps(
            {
                "passes_gate": False,
                "format": fmt,
                "compliance": comp,
                "charts": ch,
                "auto_patched": False,
                "patches_applied": [],
                "blockers": _merge_blockers(),
            }
        )

    try:
        patched_report = ResearchReport(**updated_data)
    except ValidationError as e:
        return json.dumps(
            {
                "passes_gate": False,
                "format": fmt,
                "compliance": comp,
                "charts": ch,
                "auto_patched": False,
                "patches_applied": patches,
                "blockers": [f"Re-validation failed after patch — not saved: {e}"],
            }
        )

    try:
        path.write_text(patched_report.model_dump_json(indent=2), encoding="utf-8")
    except OSError as e:
        return json.dumps(
            {
                "passes_gate": False,
                "format": fmt,
                "compliance": comp,
                "charts": ch,
                "auto_patched": False,
                "patches_applied": patches,
                "blockers": [f"Failed to write patched report: {e}"],
            }
        )

    raw2 = path.read_text(encoding="utf-8")
    data2 = json.loads(raw2)
    report2 = ResearchReport(**data2)
    fmt2 = _format_validation_dict(report2)
    comp2 = _compliance_dict(report2.markdown)
    ch2 = _charts_dict(report2)
    passes2 = bool(fmt2["valid"] and comp2["compliant"] and ch2["valid"])

    return json.dumps(
        {
            "passes_gate": passes2,
            "format": fmt2,
            "compliance": comp2,
            "charts": ch2,
            "auto_patched": True,
            "patches_applied": patches,
            "blockers": [] if passes2 else _merge_blockers_from(fmt2, comp2, ch2),
        }
    )


def _merge_blockers_from(fmt: dict, comp: dict, ch: dict) -> list[str]:
    out: list[str] = []
    if not comp["compliant"]:
        out.append("compliance violations present")
    if not fmt["valid"]:
        out.extend(fmt["missing_elements"])
    if not ch["valid"]:
        out.append(f"broken chart references: {ch['broken_references']}")
    return out


@tool
def approve_report(report_path: str, notes: str) -> str:
    """
    Approve the report for final upload.

    Use this tool after all validation checks pass to approve
    the report for delivery to the user.

    Args:
        report_path: Path to the approved report
        notes: Any notes about the approval

    Returns:
        JSON string with approval confirmation
    """
    return json.dumps(
        {"status": "approved", "report_path": report_path, "notes": notes, "ready_for_upload": True}
    )


@tool
def reject_report(reason: str, required_fixes: str | list[str]) -> str:
    """
    Reject the report and request fixes.

    Use this tool when critical issues are found that require
    the technical writer to revise the report.

    Args:
        reason: Primary reason for rejection
        required_fixes: List of specific fixes required

    Returns:
        JSON string with rejection details
    """
    if isinstance(required_fixes, str):
        try:
            required_fixes = json.loads(required_fixes)
        except json.JSONDecodeError:
            required_fixes = [required_fixes]
    if not isinstance(required_fixes, list):
        required_fixes = [str(required_fixes)]

    return json.dumps(
        {
            "status": "rejected",
            "reason": reason,
            "required_fixes": required_fixes,
            "ready_for_upload": False,
        }
    )


QUALITY_ANALYST_SUBAGENT = {
    "name": "quality-analyst",
    "description": """Use this subagent to perform final quality review of the report.

    Delegate when you need to:
    - Validate Markdown formatting and structure
    - Ensure compliance (no predictive financial advice)
    - Verify chart references are correct
    - Check for proper disclaimers

    The quality analyst runs a single composite gate, may auto-patch minor disclaimer
    or chart-marker issues when safe, then approves or rejects. Nothing reaches the
    user without approval.""",
    "system_prompt": """# ROLE
You are the Quality Analyst. You are the final gatekeeper for research reports.

# TOOLS
- `run_quality_gate`: Single composite check (schema + mandatory markdown + compliance + charts).
  Use `auto_patch=True` (default) so minor disclaimer or broken chart-marker issues are fixed when safe.
- `approve_report` / `reject_report`: Terminal actions after the gate.

# WORKFLOW
1. Call `run_quality_gate` with the absolute path to `report.json`.
2. If `passes_gate` is false, call `reject_report` with `required_fixes` drawn from `blockers`. STOP.
3. If `passes_gate` is true, call `approve_report`. STOP.

# CRITICAL RULES
- **Compliance:** Never approve predictive language or investment advice. If `run_quality_gate` reports compliance violations, reject — do not rely on auto-patch.
- **Terminality:** `approve_report` and `reject_report` are final. No further tool calls after one of them.
- **Paths:** Use absolute paths for tools.
- **Tool discipline:** Deep Agents may expose standard filesystem or shell tools on this graph. You must not use them — only call the tools listed above.
- **Analytic Quality:** Ensure findings are supported by data and avoid narrative fallacy.
""",
    "tools": [run_quality_gate, approve_report, reject_report],
    "model": "google_genai:gemini-3.1-flash-lite-preview",
    "skills": [str(_BACKEND_DIR / "skills" / "quality-analyst")],
}
