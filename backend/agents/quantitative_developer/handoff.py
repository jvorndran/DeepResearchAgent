"""Quant artifact handoff and pre-write retry state helpers."""
import json
from pathlib import Path
from typing import Any

from .constants import _HANDOFF_FIELDS, _MAX_PREWRITE_BLOCKS, get_output_base_dir
from .path_helpers import _is_allowed_analysis_script_path, _job_id_from_text
from .tool_utils import _message_tool_name

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


def _prewrite_failure_handoff(messages: list[Any]) -> str:
    job_id = _job_id_from_messages(messages) or "quant-developer-unknown-job"
    output_dir = Path(get_output_base_dir()) / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    charts_path = output_dir / "charts.json"
    summary_path = output_dir / "execution_summary.json"
    failure_path = output_dir / "quant_failure_summary.json"
    summary = {
        "status": "failed",
        "failure_stage": "quant_initial_script_write",
        "error": (
            "quant-developer exceeded the pre-write guardrail retry budget before "
            "creating code/analysis.py"
        ),
        "blocked_attempt_count": _prewrite_block_count(messages),
        "required_script_path": str(output_dir / "code" / "analysis.py"),
        "chart_ids": [],
        "methods_used": ["quant_prewrite_retry_budget_guard"],
        "limitations": [
            "No quantitative charts or computed regime/scenario artifacts were produced.",
            "Downstream report synthesis must explicitly caveat the missing local quant analysis.",
        ],
    }

    preserved_chart_ids: list[str] = []
    preserved_prior_artifacts = False
    try:
        existing_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if isinstance(existing_summary, dict) and existing_summary.get("status") != "failed":
            existing_ids = existing_summary.get("chart_ids")
            if isinstance(existing_ids, list):
                preserved_chart_ids = [str(value) for value in existing_ids if value]
            preserved_prior_artifacts = True
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        existing_summary = None

    try:
        existing_charts = json.loads(charts_path.read_text(encoding="utf-8"))
        if isinstance(existing_charts, dict) and existing_charts:
            preserved_chart_ids = list(existing_charts.keys())
            preserved_prior_artifacts = True
        elif isinstance(existing_charts, list) and existing_charts:
            preserved_chart_ids = [
                str(chart.get("id"))
                for chart in existing_charts
                if isinstance(chart, dict) and chart.get("id")
            ]
            preserved_prior_artifacts = True
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        existing_charts = None

    if preserved_prior_artifacts:
        summary["preserved_prior_artifacts"] = True
        summary["preserved_execution_summary_json"] = str(summary_path)
        summary["preserved_charts_json"] = str(charts_path)
        summary["chart_ids"] = preserved_chart_ids
        failure_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return json.dumps(
            {
                "status": "failed",
                "charts_json": str(charts_path),
                "execution_summary_json": str(summary_path),
                "failure_summary_json": str(failure_path),
                "chart_ids": preserved_chart_ids,
                "error": summary["error"],
                "methods_used": summary["methods_used"],
                "preserved_prior_artifacts": True,
            },
            sort_keys=True,
        )

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
            "error": summary["error"],
            "methods_used": summary["methods_used"],
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
        if all(field in content for field in _HANDOFF_FIELDS):
            handoff = content
    return handoff

