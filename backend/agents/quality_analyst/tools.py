"""Quality analyst tools and terminal decision normalization."""
import json
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool

from ..report_artifacts import chart_marker_ids, load_report_json
from .fidelity import (
    _approval_failure_metadata,
    _approval_blockers,
    _load_sibling_execution_summary,
)
from .utils import _parse_required_fixes, _truncate

def _compact_decision_payload(raw: str) -> str | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("status") not in {"approved", "rejected", "error"}:
        return None
    if not isinstance(payload.get("report_path"), str):
        return None

    keys = (
        "status",
        "report_path",
        "reason",
        "required_fixes",
        "failure_category",
        "required_upstream",
        "notes",
        "ready_for_upload",
    )
    compact = {key: payload[key] for key in keys if key in payload}
    return json.dumps(compact, separators=(",", ":"))


def _normalize_terminal_quality_decision(result: dict) -> dict:
    """Make submit_quality_decision's tool result the subagent's final answer.

    The QA model is instructed to mirror the terminal tool result, but the model
    can still emit a conflicting final JSON object after the tool has enforced an
    approval blocker. The orchestrator can only see the task return text, so keep
    the tool result authoritative at the runnable boundary.
    """

    messages = list(result.get("messages") or [])
    if not messages:
        return result

    latest_index: int | None = None
    latest_decision: str | None = None
    for index, message in enumerate(messages):
        if not isinstance(message, ToolMessage):
            continue
        if getattr(message, "name", None) != "submit_quality_decision":
            continue
        content = str(getattr(message, "content", "") or "")
        decision = _compact_decision_payload(content)
        if decision is None:
            continue
        latest_index = index
        latest_decision = decision

    if latest_index is None or latest_decision is None:
        return result

    normalized = dict(result)
    normalized["messages"] = messages[: latest_index + 1] + [
        AIMessage(content=latest_decision, name="quality-analyst")
    ]
    return normalized


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

    markdown = str(data.get("markdown", ""))
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
            # Keep normal-length reports intact for QA. A 4k-word institutional
            # report is still small enough for review, and excerpt markers have
            # caused false rejections as if the artifact itself were truncated.
            "markdown": _truncate(markdown, 50000),
            "markdown_full_length": len(markdown),
            "markdown_truncated_for_context": len(markdown) > 50000,
            "chart_markers": chart_marker_ids(markdown),
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
    failure_category: str = "",
    required_upstream: str = "",
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
        failure_category: Optional structured rejection category, e.g. numeric_fact_mismatch
        required_upstream: Optional specialist owner for the next repair task

    Returns:
        JSON string: approved payload with ready_for_upload true, or rejected payload with
        required_fixes and ready_for_upload false.
    """
    d = decision.strip().lower()
    if d in ("approve", "approved"):
        blockers = _approval_blockers(report_path)
        if blockers:
            metadata = _approval_failure_metadata(report_path)
            return json.dumps(
                {
                    "status": "rejected",
                    "report_path": report_path,
                    "reason": blockers[0],
                    "required_fixes": blockers,
                    **metadata,
                    "ready_for_upload": False,
                }
            )
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
        metadata = {
            key: value.strip()
            for key, value in {
                "failure_category": failure_category,
                "required_upstream": required_upstream,
            }.items()
            if isinstance(value, str) and value.strip()
        }
        if not metadata:
            metadata = _approval_failure_metadata(report_path)
        return json.dumps(
            {
                "status": "rejected",
                "report_path": report_path,
                "reason": reason,
                "required_fixes": fixes,
                **metadata,
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
