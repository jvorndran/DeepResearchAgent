"""Shared helpers for report.json, auto footer injection, and chart markers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Legacy delimiter in older saved reports; stripped on re-save but not written anymore
# (HTML comments render as literal text under ReactMarkdown without raw HTML).
AUTO_REPORT_FOOTER_MARKER = "<!-- AUTO_REPORT_DISCLAIMERS -->"

CHART_MARKER_RE = re.compile(r"<!--\s*CHART:(\S+?)\s*-->")


def auto_report_footer_markdown() -> str:
    """Canonical disclaimer block appended by the pipeline on save / validate."""
    return (
        "**DISCLAIMER**: This report does not constitute financial advice. "
        "All analysis is based on historical data.\n\n"
        "**NOTICE**: Past performance is not indicative of future results."
    )


def _strip_trailing_auto_footer(markdown: str) -> str:
    """Remove a prior auto footer: legacy marker block or trailing canonical disclaimer."""
    text = markdown.rstrip()
    idx = text.find(AUTO_REPORT_FOOTER_MARKER)
    if idx != -1:
        return text[:idx].rstrip()
    footer = auto_report_footer_markdown()
    if text.endswith(footer):
        return text[: -len(footer)].rstrip()
    return text


def inject_auto_report_footer(markdown: str) -> tuple[str, bool]:
    """
    Strip any prior auto footer, append a fresh canonical disclaimer (markdown only).

    Returns ``(new_markdown, changed)``. Idempotent when output already matches.
    """
    base = _strip_trailing_auto_footer(markdown)
    footer = auto_report_footer_markdown()
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
