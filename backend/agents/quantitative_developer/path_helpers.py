"""Path and job-id helpers for generated quant analysis scripts."""
from pathlib import Path

from langgraph.prebuilt.tool_node import ToolCallRequest

from .constants import (
    _ALLOWED_ANALYSIS_SCRIPT_RE,
    _JOB_ID_IN_PATH_RE,
    get_output_base_dir,
)
from .tool_utils import _state_messages


def _next_available_analysis_script_path(initial_path: Path) -> Path:
    """Return the first unused analysis.py/analysis_vN.py sibling."""
    path = initial_path.expanduser()
    code_dir = path.parent
    first_path = code_dir / "analysis.py"
    if not first_path.exists():
        return first_path

    version = 2
    while True:
        candidate = code_dir / f"analysis_v{version}.py"
        if not candidate.exists():
            return candidate
        version += 1


def _is_allowed_analysis_script_path(path_text: str) -> bool:
    normalized = path_text.replace("\\", "/")
    return bool(_ALLOWED_ANALYSIS_SCRIPT_RE.search(normalized))


def _job_id_from_text(text: str) -> str | None:
    match = _JOB_ID_IN_PATH_RE.search(text.replace("\\", "/"))
    if not match:
        return None
    job_id = match.group(1).strip()
    return job_id or None


def _job_id_from_request(request: ToolCallRequest, file_path: str) -> str | None:
    if job_id := _job_id_from_text(file_path):
        return job_id
    for message in reversed(_state_messages(getattr(request, "state", None))):
        content = str(getattr(message, "content", "") or "")
        if job_id := _job_id_from_text(content):
            return job_id
    return None


def _required_script_path_hint(job_id: str | None) -> str:
    if not job_id:
        return (
            "Use a non-empty absolute `file_path` ending in "
            "`/code/analysis.py`; after repeated edit failures use "
            "the first unused `/code/analysis_vN.py` fallback. Do not omit the "
            "`file_path` argument."
        )
    first_path = Path(get_output_base_dir()) / job_id / "code" / "analysis.py"
    required_path = _next_available_analysis_script_path(first_path)
    if required_path == first_path:
        fallback_path = first_path.with_name("analysis_v2.py")
        return (
            f"Use exactly `{first_path}` for the first script. "
            f"If that path already exists, use exactly `{fallback_path}` or the "
            "first unused `analysis_vN.py` sibling. Pass this as the named "
            "`file_path` argument; do not omit it or send an empty path."
        )
    return (
        f"`analysis.py` already exists for this job. Use exactly `{required_path}` "
        "for the replacement script. "
        "Pass this as the named `file_path` argument; do not omit it or send an "
        "empty path."
    )
