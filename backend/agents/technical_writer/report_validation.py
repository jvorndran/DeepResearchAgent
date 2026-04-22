"""Static validation and safe auto-patches for report.json (technical writer gate engine).

Blocking gate (``passes_gate``):
    - Valid JSON and ``ResearchReport`` schema (Pydantic).
    - Chart markers ``<!-- CHART:id -->`` resolve to keys in ``report.charts`` after optional
      auto-patch (strip unknown markers).

Canonical disclaimer text is injected by ``inject_auto_report_footer`` on every
``write_research_report`` save (and reapplied here when ``auto_patch`` runs) — the LLM
should not author that block.

Non-blocking (never flips ``passes_gate``):
    - ``warnings``: e.g. empty executive summary.

Auto-patch runs whenever ``auto_patch`` is true and ``apply_safe_patches`` would change the file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import ValidationError

from core.report_schema import ResearchReport

from ..report_artifacts import chart_marker_ids, inject_auto_report_footer, load_report_json


def content_warnings(report: ResearchReport) -> list[str]:
    """Non-blocking hints for the writer / QA (never used for ``passes_gate``)."""
    out: list[str] = []
    if not report.executive_summary.strip():
        out.append("Executive summary is empty (consider filling before handoff)")
    return out


def charts_dict(report: ResearchReport) -> dict:
    marker_ids = chart_marker_ids(report.markdown)
    defined = list(report.charts.keys())
    broken = [mid for mid in marker_ids if mid not in report.charts]
    return {
        "valid": len(broken) == 0,
        "broken_references": broken,
        "chart_count": len(marker_ids),
        "defined_charts": defined,
    }


def format_dict_schema_ok() -> dict:
    """Legacy ``format`` key when schema succeeded (prose checks moved to ``warnings``)."""
    return {"valid": True, "schema_errors": [], "missing_elements": []}


def structural_blockers(charts: dict) -> list[str]:
    if charts["valid"]:
        return []
    return [f"broken chart references: {charts['broken_references']}"]


def apply_safe_patches(data: dict, report: ResearchReport) -> tuple[dict, list[str]]:
    """Apply idempotent auto footer + broken-chart-marker removal. Returns (updated_data, changes)."""
    markdown = report.markdown
    changes_made: list[str] = []

    new_md, footer_changed = inject_auto_report_footer(markdown)
    if footer_changed:
        markdown = new_md
        changes_made.append("Applied auto-injected report disclaimer footer")

    defined_charts = set(report.charts.keys())

    def _remove_if_broken(m: re.Match) -> str:
        chart_id = m.group(1)
        if chart_id not in defined_charts:
            changes_made.append(f"Removed broken chart marker <!-- CHART:{chart_id} -->")
            return ""
        return m.group(0)

    new_md = re.sub(r"<!--\s*CHART:(\S+?)\s*-->", _remove_if_broken, markdown)
    if new_md != markdown:
        markdown = new_md

    if not changes_made:
        return data, []

    updated = dict(data)
    updated["markdown"] = markdown
    updated["metadata"] = dict(data.get("metadata", {}))
    updated["metadata"]["word_count"] = len(markdown.split())
    return updated, changes_made


def _gate_payload(
    *,
    passes_gate: bool,
    fmt: dict,
    charts: dict,
    warnings: list[str],
    auto_patched: bool,
    patches_applied: list[str],
    blockers: list[str],
    load_error: str | None = None,
) -> str:
    body: dict = {
        "passes_gate": passes_gate,
        "format": fmt,
        "charts": charts,
        "warnings": warnings,
        "auto_patched": auto_patched,
        "patches_applied": patches_applied,
        "blockers": blockers,
    }
    if load_error is not None:
        body["load_error"] = load_error
    return json.dumps(body)


def run_report_static_gate(report_json_path: str, auto_patch: bool = True) -> str:
    """
    Run schema validation, optional safe auto-fixes, and chart-marker integrity.

    ``passes_gate`` is true when JSON loads, ``ResearchReport`` validates, and every
    ``<!-- CHART:id -->`` references a defined chart after patching.

    Args:
        report_json_path: Absolute path to report.json
        auto_patch: If True, re-apply canonical footer (idempotent) / strip broken chart markers

    Returns:
        JSON string with passes_gate, format, charts, warnings, auto_patched,
        patches_applied, and blockers (structural chart issues only).
    """
    path = Path(report_json_path)
    data, load_err = load_report_json(report_json_path)
    if load_err or data is None:
        return _gate_payload(
            passes_gate=False,
            fmt={},
            charts={},
            warnings=[],
            auto_patched=False,
            patches_applied=[],
            blockers=[load_err or "Unknown load error"],
            load_error=load_err,
        )

    try:
        report = ResearchReport(**data)
    except ValidationError as e:
        return _gate_payload(
            passes_gate=False,
            fmt={"valid": False, "schema_errors": [str(e)], "missing_elements": []},
            charts={},
            warnings=[],
            auto_patched=False,
            patches_applied=[],
            blockers=[f"Schema validation failed: {e}"],
        )

    fmt_ok = format_dict_schema_ok()
    charts = charts_dict(report)
    warnings = content_warnings(report)

    if auto_patch:
        updated_data, patches = apply_safe_patches(data, report)
        if patches:
            try:
                patched_report = ResearchReport(**updated_data)
            except ValidationError as e:
                return _gate_payload(
                    passes_gate=False,
                    fmt=fmt_ok,
                    charts=charts,
                    warnings=warnings,
                    auto_patched=False,
                    patches_applied=patches,
                    blockers=[f"Re-validation failed after patch — not saved: {e}"],
                )

            try:
                path.write_text(patched_report.model_dump_json(indent=2), encoding="utf-8")
            except OSError as e:
                return _gate_payload(
                    passes_gate=False,
                    fmt=fmt_ok,
                    charts=charts,
                    warnings=warnings,
                    auto_patched=False,
                    patches_applied=patches,
                    blockers=[f"Failed to write patched report: {e}"],
                )

            raw2 = path.read_text(encoding="utf-8")
            data = json.loads(raw2)
            report = ResearchReport(**data)
            charts = charts_dict(report)
            warnings = content_warnings(report)
            blockers = structural_blockers(charts)
            passes = len(blockers) == 0
            return _gate_payload(
                passes_gate=passes,
                fmt=fmt_ok,
                charts=charts,
                warnings=warnings,
                auto_patched=True,
                patches_applied=patches,
                blockers=blockers,
            )

    blockers = structural_blockers(charts)
    passes = len(blockers) == 0
    return _gate_payload(
        passes_gate=passes,
        fmt=fmt_ok,
        charts=charts,
        warnings=warnings,
        auto_patched=False,
        patches_applied=[],
        blockers=blockers,
    )
