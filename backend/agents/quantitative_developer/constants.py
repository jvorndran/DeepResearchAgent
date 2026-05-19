"""Constants and paths for the quantitative developer subagent."""

import os
import re
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_STORAGE_DIR = os.getenv("DATA_STORAGE_DIR", str(_BACKEND_DIR / "data"))

# Absolute path so analysis.py scripts use it regardless of sandbox CWD
OUTPUT_BASE_DIR = os.getenv("OUTPUT_DIR", str(_BACKEND_DIR / "outputs"))

# Prefer the venv Python (has pandas/numpy/scipy) over the bare system interpreter.
# The venv is always at backend/.venv/bin/python on Linux.
_VENV_PYTHON = _BACKEND_DIR / ".venv" / "bin" / "python"
PYTHON_EXECUTABLE = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable

_FIRST_WRITE_TOOL_NAMES = {"write_file"}
_AFTER_WRITE_TOOL_NAMES = {
    "write_file",
    "read_file",
    "edit_file",
    "execute",
}
_INSPECTION_TOOL_NAMES = {"ls", "glob", "grep"}
_MAX_ANALYSIS_SCRIPT_LINES = 360
_MAX_ANALYSIS_SCRIPT_CHARS = 28_000
# The prompt/tool feedback gives the model one final compact rewrite after
# three blocked drafts, so the hard failure trips on the fourth blocked write.
_MAX_PREWRITE_BLOCKS = 4
_DATA_FILE_SUFFIXES = {".csv", ".json", ".jsonl", ".parquet", ".xlsx", ".xls"}
_HANDOFF_FIELDS = (
    "charts_json",
    "execution_summary_json",
    "evidence_bundle_json",
    "chart_ids",
)
_HIGH_FREQUENCY_FRED_KEYS = {
    "T10Y2Y",
    "T10Y3M",
    "T10YFF",
    "DGS10",
    "DGS2",
    "DGS3MO",
    "DGS1",
    "DGS5",
    "DGS30",
    "T5YIE",
    "T10YIE",
    "T5YIFR",
    "ICSA",
    "IC4WSA",
}
_MONTHLY_OR_LOWER_FRED_KEYS = {
    "UNRATE",
    "PAYEMS",
    "INDPRO",
    "USREC",
    "CPIAUCSL",
    "CPILFESL",
    "PCEPI",
    "GDPC1",
    "GDP",
    "RSAFS",
    "UMCSENT",
    "JTSJOL",
    "JTSJOLR",
    "JTSHIL",
    "JTSHIR",
    "JTSQUL",
    "JTSQUR",
    "JTSLDL",
    "JTSLDR",
    "JTSSTL",
    "JTSSTR",
}
_DATA_FILES_MANIFEST_NAMES = {"DATA_FILES", "DATA", "DF", "D"}
_ALLOWED_ANALYSIS_SCRIPT_RE = re.compile(r"(?:^|/)code/analysis(?:_v\d+)?\.py$")
_JOB_ID_IN_PATH_RE = re.compile(r"(?:^|[\s'\"`/])outputs/([^/\s'\"`]+)/")
_AUTO_SAVED_DATA_STEM_RE = re.compile(
    r"^(?P<prefix>.+)_(?P<timestamp>\d{16,})_(?P<fingerprint>[0-9a-f]{6,})$"
)
_TRUNCATED_ARGUMENT_MARKERS = (
    "...(argument truncated)",
    "(argument truncated)",
    "...(truncated)",
)


def get_output_base_dir() -> str:
    """Return package-level OUTPUT_BASE_DIR so existing monkeypatches keep working."""
    package = sys.modules.get("agents.quantitative_developer")
    if package is None:
        package = sys.modules.get("backend.agents.quantitative_developer")
    return str(getattr(package, "OUTPUT_BASE_DIR", OUTPUT_BASE_DIR))
