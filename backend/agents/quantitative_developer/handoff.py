"""Quant artifact handoff and pre-write retry state helpers."""
import json
from pathlib import Path
from typing import Any

from .constants import (
    _HANDOFF_FIELDS,
    _MAX_PREWRITE_BLOCKS,
    get_output_base_dir,
)
from .path_helpers import _is_allowed_analysis_script_path, _job_id_from_text
from .tool_utils import _message_tool_name

_NON_HANDOFF_TOOL_NAMES = {
    "edit_file",
    "glob",
    "grep",
    "loadSkill",
    "load_skill",
    "ls",
    "read_file",
    "write_file",
}
_HANDOFF_TOOL_NAMES = {"execute"}

def _has_written_analysis_script(messages: list[Any]) -> bool:
    for message in messages:
        if type(message).__name__ == "ToolMessage":
            content = str(getattr(message, "content", "") or "")
            if (
                _is_allowed_analysis_script_path(content)
                and (
                    "Updated file" in content
                    or "Created file" in content
                    or "Wrote file" in content
                )
            ):
                return True
    return False


def _has_successful_quant_handoff(messages: list[Any]) -> bool:
    return _latest_successful_quant_handoff_content(messages) is not None


def _prewrite_block_count(messages: list[Any]) -> int:
    count = 0
    for message in messages:
        if type(message).__name__ != "ToolMessage":
            continue
        if _message_tool_name(message) != "write_file":
            continue
        content = str(getattr(message, "content", "") or "")
        status = getattr(message, "status", None)
        if status == "error" and content.startswith("Blocked "):
            count += 1
    return count


def _job_id_from_messages(messages: list[Any]) -> str | None:
    for message in reversed(messages):
        content = str(getattr(message, "content", "") or "")
        if job_id := _job_id_from_text(content):
            return job_id
    return None


def _job_id_from_runtime(runtime: Any) -> str | None:
    context = getattr(runtime, "context", None)
    if isinstance(context, dict):
        value = context.get("job_id")
    else:
        value = getattr(context, "job_id", None)
    if not isinstance(value, str):
        return None
    job_id = value.strip()
    if not job_id or "/" in job_id or "\\" in job_id:
        return None
    return job_id


def _prewrite_failure_handoff(
    messages: list[Any],
    *,
    job_id: str | None = None,
    failure_stage: str = "quant_initial_script_write",
    error: str | None = None,
    methods_used: list[str] | None = None,
) -> str:
    job_id = job_id or _job_id_from_messages(messages) or "quant-developer-unknown-job"
    output_dir = Path(get_output_base_dir()) / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    charts_path = output_dir / "charts.json"
    summary_path = output_dir / "execution_summary.json"
    methods = methods_used or ["quant_prewrite_retry_budget_guard"]
    summary = {
        "status": "failed",
        "failure_stage": failure_stage,
        "error": (
            error
            or "quant-developer exceeded the pre-write guardrail retry budget before "
            "creating code/analysis.py"
        ),
        "blocked_attempt_count": _prewrite_block_count(messages),
        "required_script_path": str(output_dir / "code" / "analysis.py"),
        "chart_ids": [],
        "methods_used": methods,
        "limitations": [
            "No quantitative charts or computed regime/scenario artifacts were produced.",
            "Downstream report synthesis must explicitly caveat the missing local quant analysis.",
        ],
    }

    charts_path.write_text("[]\n", encoding="utf-8")
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return json.dumps(
        {
            "status": "failed",
            "charts_json": str(charts_path),
            "execution_summary_json": str(summary_path),
            "chart_ids": [],
            "failure_stage": failure_stage,
            "error": summary["error"],
            "methods_used": methods,
        },
        sort_keys=True,
    )


def _should_stop_prewrite_loop(messages: list[Any]) -> bool:
    return (
        not _has_written_analysis_script(messages)
        and _prewrite_block_count(messages) >= _MAX_PREWRITE_BLOCKS
    )


def _is_final_prewrite_opportunity(messages: list[Any]) -> bool:
    return (
        not _has_written_analysis_script(messages)
        and _prewrite_block_count(messages) == _MAX_PREWRITE_BLOCKS - 1
    )


def _latest_successful_quant_handoff_content(messages: list[Any]) -> str | None:
    handoff: str | None = None
    for message in messages:
        if type(message).__name__ != "ToolMessage":
            continue
        content = str(getattr(message, "content", "") or "")
        status = getattr(message, "status", None)
        if status == "error" or "Command failed" in content:
            continue
        tool_name = _message_tool_name(message)
        if tool_name in _NON_HANDOFF_TOOL_NAMES:
            continue
        if tool_name not in _HANDOFF_TOOL_NAMES and not content.lstrip().startswith("{"):
            continue
        if all(field in content for field in _HANDOFF_FIELDS):
            handoff = content
    return handoff
