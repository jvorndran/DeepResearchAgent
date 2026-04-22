"""Shared helpers for report.json, auto footer injection, and chart markers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Replaced on every save / validate patch so the LLM does not maintain this prose.
AUTO_REPORT_FOOTER_MARKER = "<!-- AUTO_REPORT_DISCLAIMERS -->"

CHART_MARKER_RE = re.compile(r"<!--\s*CHART:(\S+?)\s*-->")


def auto_report_footer_markdown() -> str:
    """Canonical disclaimer block (after ``AUTO_REPORT_FOOTER_MARKER``)."""
    return (
        "**DISCLAIMER**: This report does not constitute financial advice. "
        "All analysis is based on historical data.\n\n"
        "**NOTICE**: Past performance is not indicative of future results."
    )


def inject_auto_report_footer(markdown: str) -> tuple[str, bool]:
    """
    Strip any prior auto footer (from marker through EOF), append a fresh canonical footer.

    Returns ``(new_markdown, changed)``. Idempotent when output already matches.
    """
    idx = markdown.find(AUTO_REPORT_FOOTER_MARKER)
    base = markdown[:idx].rstrip() if idx != -1 else markdown.rstrip()
    footer = f"{AUTO_REPORT_FOOTER_MARKER}\n\n{auto_report_footer_markdown()}"
    new_md = f"{base}\n\n{footer}" if base else footer
    return new_md, new_md != markdown


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
