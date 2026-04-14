"""
Quality Analyst Subagent (Deep Agents)

The Quality Analyst performs final quality checks on generated reports.
It validates formatting, and ensures compliance
with financial disclosure requirements.

Role: Quality Analyst / Compliance Officer
Model: Gemini 3.0 Flash (good at evaluation and pattern detection)

Responsibilities:
- Verify Markdown formatting is correct
- Ensure no predictive financial advice (compliance)
- Validate chart references are correct
- Check for proper disclaimers
- Approve or reject for final upload

Key Principle: Acts as the final gatekeeper. Nothing goes to the user
without Quality Analyst approval.
"""

from typing import List
from langchain_core.tools import tool
import json
import re
import os
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent


# =============================================================================
# QUALITY ANALYST TOOLS
# =============================================================================

@tool
def validate_report_format(report_json_path: str) -> str:
    """
    Validate the ResearchReport by loading report.json via Pydantic.

    Loads the report artifact and validates it against the ResearchReport
    schema. Checks mandatory elements in the markdown field.

    Args:
        report_json_path: File path to the report.json artifact

    Returns:
        JSON string with:
        - valid: Boolean indicating if the report passes all checks
        - schema_errors: Pydantic validation errors (if any)
        - missing_elements: List of mandatory elements absent from markdown
    """
    from core.report_schema import ResearchReport
    from pydantic import ValidationError

    schema_errors: list[str] = []
    missing_elements: list[str] = []

    # Load and parse report.json
    try:
        raw = Path(report_json_path).read_text(encoding="utf-8")
        data = json.loads(raw)
    except FileNotFoundError:
        return json.dumps({
            "valid": False,
            "schema_errors": [f"File not found: {report_json_path}"],
            "missing_elements": []
        })
    except json.JSONDecodeError as e:
        return json.dumps({
            "valid": False,
            "schema_errors": [f"Invalid JSON: {e}"],
            "missing_elements": []
        })

    # Pydantic validation
    try:
        report = ResearchReport(**data)
    except ValidationError as e:
        return json.dumps({
            "valid": False,
            "schema_errors": [str(err) for err in e.errors()],
            "missing_elements": []
        })

    # Mandatory markdown element checks
    markdown = report.markdown

    if "does not constitute financial advice" not in markdown:
        missing_elements.append("Financial disclaimer ('does not constitute financial advice')")

    if "Past performance" not in markdown:
        missing_elements.append("Past performance notice")

    if not report.executive_summary.strip():
        missing_elements.append("Executive summary (empty)")

    if report.query not in markdown and report.query[:40] not in markdown:
        missing_elements.append("Original query not found in markdown")

    valid = len(schema_errors) == 0 and len(missing_elements) == 0

    return json.dumps({
        "valid": valid,
        "schema_errors": schema_errors,
        "missing_elements": missing_elements
    })


@tool
def check_compliance(report_json_path: str) -> str:
    """
    Check for compliance with financial disclosure rules.

    Use this tool to ensure the report doesn't contain predictive
    language or investment advice.

    Args:
        report_json_path: File path to the report.json artifact

    Returns:
        JSON string with:
        - compliant: Boolean indicating if report is compliant
        - violations: List of compliance violations found
        - severity: "critical", "warning", or "none"
    """
    try:
        raw = Path(report_json_path).read_text(encoding="utf-8")
        data = json.loads(raw)
        report_text = data.get("markdown", "")
    except FileNotFoundError:
        return json.dumps({
            "compliant": False,
            "violations": [f"File not found: {report_json_path}"],
            "severity": "critical"
        })
    except json.JSONDecodeError as e:
        return json.dumps({
            "compliant": False,
            "violations": [f"Invalid JSON: {e}"],
            "severity": "critical"
        })

    violations = []

    # Patterns that indicate predictive advice (not allowed)
    prediction_patterns = [
        (r"(should|must|need to) (buy|sell|invest|trade|acquire|divest)", "Investment advice"),
        (r"(recommend|suggestion|advice):? (buy|sell|hold)", "Investment recommendations")
    ]

    for pattern, description in prediction_patterns:
        matches = re.findall(pattern, report_text, re.IGNORECASE)
        if matches:
            violations.append({
                "type": description,
                "match": matches[0] if isinstance(matches[0], str) else " ".join(matches[0]),
                "pattern": pattern
            })

    severity = "critical" if len(violations) > 0 else "none"

    return json.dumps({
        "compliant": len(violations) == 0,
        "violations": violations,
        "severity": severity
    })


@tool
def verify_chart_references(report_json_path: str) -> str:
    """
    Verify all <!-- CHART:id --> markers in report.markdown resolve to chart IDs.

    Loads report.json, extracts every <!-- CHART:id --> marker from the markdown
    field, and checks that each ID exists in report.charts.

    Args:
        report_json_path: File path to the report.json artifact

    Returns:
        JSON string with:
        - valid: Boolean — True only if all marker IDs exist in report.charts
        - broken_references: List of marker IDs missing from report.charts
        - chart_count: Number of <!-- CHART:id --> markers found in markdown
        - defined_charts: List of chart IDs defined in report.charts
    """
    from core.report_schema import ResearchReport
    from pydantic import ValidationError

    try:
        raw = Path(report_json_path).read_text(encoding="utf-8")
        data = json.loads(raw)
        report = ResearchReport(**data)
    except (FileNotFoundError, json.JSONDecodeError, ValidationError) as e:
        return json.dumps({
            "valid": False,
            "broken_references": [f"Could not load report: {e}"],
            "chart_count": 0,
            "defined_charts": []
        })

    marker_ids: list[str] = re.findall(r'<!--\s*CHART:(\S+?)\s*-->', report.markdown)
    defined = list(report.charts.keys())
    broken = [mid for mid in marker_ids if mid not in report.charts]

    return json.dumps({
        "valid": len(broken) == 0,
        "broken_references": broken,
        "chart_count": len(marker_ids),
        "defined_charts": defined
    })


@tool
def patch_report(report_json_path: str, patch_type: str) -> str:
    """
    Autonomously fix minor issues in the report without rejecting to Technical Writer.

    Supported patch_type values:
    - "add_disclaimer": Appends financial disclaimer text if missing
    - "add_past_performance": Appends past performance notice if missing
    - "remove_broken_chart_markers": Strips <!-- CHART:id --> markers whose ID
      is not in report.charts

    All patch types are idempotent — safe to call multiple times.

    Args:
        report_json_path: File path to the report.json artifact
        patch_type: One of the supported patch type strings listed above

    Returns:
        JSON string with:
        - patched: Boolean indicating if changes were made
        - changes_made: List of descriptions of changes applied
        - validation_issues: List of any re-validation issues after patching
    """
    from core.report_schema import ResearchReport
    from pydantic import ValidationError

    SUPPORTED = {"add_disclaimer", "add_past_performance", "remove_broken_chart_markers"}
    if patch_type not in SUPPORTED:
        return json.dumps({
            "patched": False,
            "changes_made": [],
            "validation_issues": [f"Unknown patch_type '{patch_type}'. Supported: {sorted(SUPPORTED)}"]
        })

    # Load and parse report.json
    try:
        path = Path(report_json_path)
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except FileNotFoundError:
        return json.dumps({
            "patched": False,
            "changes_made": [],
            "validation_issues": [f"File not found: {report_json_path}"]
        })
    except json.JSONDecodeError as e:
        return json.dumps({
            "patched": False,
            "changes_made": [],
            "validation_issues": [f"Invalid JSON: {e}"]
        })

    try:
        report = ResearchReport(**data)
    except ValidationError as e:
        return json.dumps({
            "patched": False,
            "changes_made": [],
            "validation_issues": [f"Schema validation failed before patching: {e}"]
        })

    markdown = report.markdown
    changes_made: list[str] = []

    if patch_type == "add_disclaimer":
        if "does not constitute financial advice" not in markdown:
            markdown += (
                "\n\n**DISCLAIMER**: This report does not constitute financial advice. "
                "All analysis is based on historical data."
            )
            changes_made.append("Appended financial disclaimer")

    elif patch_type == "add_past_performance":
        if "Past performance" not in markdown:
            markdown += "\n\n**NOTICE**: Past performance is not indicative of future results."
            changes_made.append("Appended past performance notice")

    elif patch_type == "remove_broken_chart_markers":
        defined_charts = set(report.charts.keys())
        def _remove_if_broken(m: re.Match) -> str:
            chart_id = m.group(1)
            if chart_id not in defined_charts:
                changes_made.append(f"Removed broken chart marker <!-- CHART:{chart_id} -->")
                return ""
            return m.group(0)
        markdown = re.sub(r'<!--\s*CHART:(\S+?)\s*-->', _remove_if_broken, markdown)

    if not changes_made:
        return json.dumps({
            "patched": False,
            "changes_made": [],
            "validation_issues": []
        })

    # Recalculate word_count and update data dict
    updated_data = data.copy()
    updated_data["markdown"] = markdown
    updated_data["metadata"] = dict(data.get("metadata", {}))
    updated_data["metadata"]["word_count"] = len(markdown.split())

    # Re-validate patched object via Pydantic before saving
    try:
        patched_report = ResearchReport(**updated_data)
    except ValidationError as e:
        return json.dumps({
            "patched": False,
            "changes_made": changes_made,
            "validation_issues": [f"Re-validation failed after patching — not saved: {e}"]
        })

    # Save patched report
    try:
        path.write_text(patched_report.model_dump_json(indent=2), encoding="utf-8")
    except Exception as e:
        return json.dumps({
            "patched": False,
            "changes_made": changes_made,
            "validation_issues": [f"Failed to write patched report: {e}"]
        })

    return json.dumps({
        "patched": True,
        "changes_made": changes_made,
        "validation_issues": []
    })


@tool
def approve_report(
    report_path: str,
    notes: str
) -> str:
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
    return json.dumps({
        "status": "approved",
        "report_path": report_path,
        "notes": notes,
        "ready_for_upload": True
    })


@tool
def reject_report(
    reason: str,
    required_fixes: str | list[str]
) -> str:
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

    return json.dumps({
        "status": "rejected",
        "reason": reason,
        "required_fixes": required_fixes,
        "ready_for_upload": False
    })


# =============================================================================
# SUBAGENT CONFIGURATION
# =============================================================================

QUALITY_ANALYST_SUBAGENT = {
    "name": "quality-analyst",

    "description": """Use this subagent to perform final quality review of the report.

    Delegate when you need to:
    - Validate Markdown formatting and structure
    - Ensure compliance (no predictive financial advice)
    - Verify chart references are correct
    - Check for proper disclaimers

    The quality analyst autonomously patches minor issues (missing disclaimers,
    broken chart markers) and either approves or rejects the report. Rejections include
    a required_fixes list for the technical writer. Nothing reaches the user without approval.""",

    "system_prompt": """# ROLE
You are the Quality Analyst. You are the final gatekeeper for research reports.

# TOOLS
- `validate_report_format`: Check structure and mandatory elements.
- `check_compliance`: Ensure no predictive advice or investment recommendations.
- `verify_chart_references`: Verify all `<!-- CHART:id -->` markers match `report.charts`.
- `patch_report`: Auto-fix minor issues (missing disclaimer, broken markers).
- `approve_report` / `reject_report`: Terminal actions.

# WORKFLOW
1. `validate_report_format` → `check_compliance` → `verify_chart_references`.
2. **If Critical Finding:** Call `reject_report` with required fixes. STOP.
3. **If Auto-Fixable:** Call `patch_report` and re-run `validate_report_format`.
4. **If Valid:** Call `approve_report`. STOP.

# CRITICAL RULES
- **Compliance:** Never approve predictive language like "will increase" or investment advice.
- **Terminality:** `approve_report` and `reject_report` are final. No further tool calls.
- **Paths:** Use absolute paths for the report tools.
- **No shell/filesystem tools:** They are blocked for this subagent.
- **Analytic Quality:** Ensure findings are supported by data and avoid narrative fallacy.
""",

    "tools": [
        validate_report_format,
        check_compliance,
        verify_chart_references,
        patch_report,
        approve_report,
        reject_report
    ],

    "model": "google_genai:gemini-3-flash-preview",

    "skills": [str(_BACKEND_DIR / "skills" / "quality-analyst")]
}
