"""Shared helpers for report.json loading, disclaimers, and chart markers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Substrings used to verify mandatory disclaimers in markdown
DISCLAIMER_SUBSTRINGS = {
    "financial_advice": "does not constitute financial advice",
    "past_performance": "Past performance",
}

CHART_MARKER_RE = re.compile(r"<!--\s*CHART:(\S+?)\s*-->")


def load_report_json(report_json_path: str) -> tuple[dict[str, Any] | None, str | None]:
    """
    Load and parse report.json. Returns (data, None) on success, or (None, error_message).
    """
    try:
        raw = Path(report_json_path).read_text(encoding="utf-8")
        data = json.loads(raw)
    except FileNotFoundError:
        return None, f"File not found: {report_json_path}"
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}"
    if not isinstance(data, dict):
        return None, "report.json root must be a JSON object"
    return data, None


def chart_marker_ids(markdown: str) -> list[str]:
    return CHART_MARKER_RE.findall(markdown)
