"""Shared helpers for report.json, auto footer injection, and chart markers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .quant_macro_stats.artifacts.evidence_bundle import EvidenceBundle

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


def load_sibling_execution_summary_json(
    report_json_path: str | Path,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Load execution_summary.json next to report.json.

    A missing sibling is not an error for static report validation because legacy
    reports and prose-only runs may not have quantitative artifacts.
    """
    path = Path(report_json_path).with_name("execution_summary.json")
    if not path.is_file():
        return None, None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, str(exc)
    except json.JSONDecodeError as exc:
        return None, f"Invalid execution_summary.json: {exc}"
    if not isinstance(parsed, dict):
        return None, "execution_summary.json root must be a JSON object"
    return parsed, None


def load_sibling_evidence_bundle_json(
    report_json_path: str | Path,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Load evidence_bundle.json next to report.json.

    A missing sibling is not an error for static report validation because
    legacy reports and prose-only runs may not have quantitative bundle
    artifacts.
    """
    path = Path(report_json_path).with_name("evidence_bundle.json")
    if not path.is_file():
        return None, None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, str(exc)
    except json.JSONDecodeError as exc:
        return None, f"Invalid evidence_bundle.json: {exc}"
    if not isinstance(parsed, dict):
        return None, "evidence_bundle.json root must be a JSON object"
    try:
        bundle = EvidenceBundle.model_validate(parsed)
    except ValidationError as exc:
        return None, f"Invalid evidence_bundle.json: {exc}"
    return bundle.model_dump(mode="json", exclude_none=True), None


def _unique_string_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip() if item is not None else ""
        if not text or text in seen:
            continue
        seen.add(text)
        ids.append(text)
    return ids


def _report_chart_ids(report_data: dict[str, Any]) -> list[str]:
    charts = report_data.get("charts")
    if isinstance(charts, dict):
        return _unique_string_ids(list(charts.keys()))
    if not isinstance(charts, list):
        return []

    ids: list[str] = []
    seen: set[str] = set()
    for item in charts:
        if not isinstance(item, dict):
            continue
        for key in ("id", "chart_id", "name"):
            chart_id = item.get(key)
            text = str(chart_id).strip() if chart_id is not None else ""
            if text:
                break
        else:
            text = ""
        if not text or text in seen:
            continue
        seen.add(text)
        ids.append(text)
    return ids


def chart_handoff_dict(
    report_data: dict[str, Any],
    execution_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Compare final report chart coverage with the quantitative chart handoff.

    Expected charts are the non-dropped IDs from execution_summary.json. Missing
    final chart definitions are blocking; markdown marker coverage is returned
    as a diagnostic because canonical marker integrity is enforced separately.
    """
    summary = execution_summary if isinstance(execution_summary, dict) else {}
    upstream_chart_ids = _unique_string_ids(summary.get("chart_ids"))
    dropped_chart_ids = _unique_string_ids(summary.get("dropped_chart_ids"))
    dropped = set(dropped_chart_ids)
    expected_chart_ids = [
        chart_id for chart_id in upstream_chart_ids if chart_id not in dropped
    ]
    report_chart_ids = _report_chart_ids(report_data)
    markdown_chart_ids = chart_marker_ids(str(report_data.get("markdown", "")))
    report_chart_set = set(report_chart_ids)
    markdown_chart_set = set(markdown_chart_ids)
    missing_report_chart_ids = [
        chart_id for chart_id in expected_chart_ids if chart_id not in report_chart_set
    ]
    missing_markdown_chart_ids = [
        chart_id for chart_id in expected_chart_ids if chart_id not in markdown_chart_set
    ]
    return {
        "required": bool(upstream_chart_ids),
        "valid": not missing_report_chart_ids,
        "expected_chart_ids": expected_chart_ids,
        "upstream_chart_ids": upstream_chart_ids,
        "dropped_chart_ids": dropped_chart_ids,
        "report_chart_ids": report_chart_ids,
        "markdown_chart_ids": markdown_chart_ids,
        "missing_report_chart_ids": missing_report_chart_ids,
        "missing_markdown_chart_ids": missing_markdown_chart_ids,
    }


def chart_handoff_blocker(chart_handoff: dict[str, Any]) -> str | None:
    if not chart_handoff or chart_handoff.get("valid", True):
        return None
    missing_report = chart_handoff.get("missing_report_chart_ids") or []
    parts: list[str] = []
    if missing_report:
        parts.append(f"missing_report_chart_ids={missing_report}")
    if not parts:
        return None
    parts.append(f"expected_chart_ids={chart_handoff.get('expected_chart_ids') or []}")
    parts.append(f"dropped_chart_ids={chart_handoff.get('dropped_chart_ids') or []}")
    return (
        "chart_handoff_mismatch: final report did not preserve non-dropped "
        "execution_summary.chart_ids (" + "; ".join(parts) + ")"
    )
