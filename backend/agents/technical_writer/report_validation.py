"""Static validation and safe auto-patches for report.json (technical writer gate engine).

Blocking gate (``passes_gate``):
    - Valid JSON and ``ResearchReport`` schema (Pydantic).
    - Chart markers ``<!-- CHART:id -->`` resolve to keys in ``report.charts``.
      For chart-requested reports, unknown markers are blockers rather than
      being stripped by auto-patch.
    - Axis charts satisfy deterministic render and data semantics checks.
    - Generic chart and numeric-fact fidelity checks guard against invented
      quantitative evidence.

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
from .chart_audit import chart_render_dict, chart_semantics_dict, query_requests_charts

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
    unreferenced = [chart_id for chart_id in defined if chart_id not in marker_ids]
    seen: set[str] = set()
    duplicate_markers = []
    for marker_id in marker_ids:
        if marker_id in seen and marker_id not in duplicate_markers:
            duplicate_markers.append(marker_id)
        seen.add(marker_id)
    metadata_chart_count = report.metadata.chart_count
    return {
        "valid": len(broken) == 0 and len(unreferenced) == 0 and len(duplicate_markers) == 0,
        "broken_references": broken,
        "unreferenced_charts": unreferenced,
        "duplicate_markers": duplicate_markers,
        "chart_count": len(marker_ids),
        "metadata_chart_count": metadata_chart_count,
        "chart_count_mismatch": metadata_chart_count != len(marker_ids),
        "defined_charts": defined,
    }


def scenario_dict(report: ResearchReport) -> dict:
    return {
        "required": False,
        "valid": True,
        "row_count": 0,
        "scenarios": [],
        "missing_required_rows": [],
    }


def format_dict_schema_ok() -> dict:
    """Legacy ``format`` key when schema succeeded (prose checks moved to ``warnings``)."""
    return {"valid": True, "schema_errors": [], "missing_elements": []}


def structural_blockers(
    charts: dict,
    scenarios: dict | None = None,
    chart_render: dict | None = None,
    chart_semantics: dict | None = None,
    chart_required: bool = False,
) -> list[str]:
    blockers: list[str] = []
    if chart_required and not charts.get("defined_charts"):
        blockers.append(
            "query requested charts but report.json contains zero chart definitions"
        )
    if not charts["valid"]:
        if charts["broken_references"]:
            blockers.append(f"broken chart references: {charts['broken_references']}")
        if charts.get("unreferenced_charts"):
            blockers.append(
                "charts defined in charts.json but not referenced in markdown: "
                f"{charts['unreferenced_charts']}"
            )
        if charts.get("duplicate_markers"):
            blockers.append(f"duplicate chart markers: {charts['duplicate_markers']}")
    if charts.get("chart_count_mismatch"):
        blockers.append(
            "metadata chart_count does not match markdown chart markers: "
            f"metadata={charts.get('metadata_chart_count')} markers={charts.get('chart_count')}"
        )
    if chart_render is not None and not chart_render["valid"]:
        blockers.append(
            "charts fail frontend Recharts render contract: "
            f"{chart_render['issues']}"
        )
    if chart_semantics is not None and not chart_semantics["valid"]:
        blockers.append(
            "charts fail chart data semantics audit: "
            f"{chart_semantics['blockers']}"
        )
    return blockers


def apply_safe_patches(
    data: dict,
    report: ResearchReport,
    *,
    remove_broken_chart_markers: bool = True,
) -> tuple[dict, list[str]]:
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
        if remove_broken_chart_markers and chart_id not in defined_charts:
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
    updated["metadata"]["chart_count"] = len(chart_marker_ids(markdown))
    return updated, changes_made


def _gate_payload(
    *,
    passes_gate: bool,
    fmt: dict,
    charts: dict,
    scenarios: dict | None,
    chart_render: dict | None,
    chart_semantics: dict | None,
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
        "scenarios": scenarios or {},
        "chart_render": chart_render or {},
        "chart_semantics": chart_semantics or {},
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
        JSON string with passes_gate, format, charts, scenarios, chart_render,
        chart_semantics, warnings, auto_patched, patches_applied, and blockers.
    """
    path = Path(report_json_path)
    data, load_err = load_report_json(report_json_path)
    if load_err or data is None:
        return _gate_payload(
            passes_gate=False,
            fmt={},
            charts={},
            scenarios={},
            chart_render={},
            chart_semantics={},
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
            scenarios={},
            chart_render={},
            chart_semantics={},
            warnings=[],
            auto_patched=False,
            patches_applied=[],
            blockers=[f"Schema validation failed: {e}"],
        )

    fmt_ok = format_dict_schema_ok()
    charts = charts_dict(report)
    chart_render = chart_render_dict(report)
    chart_semantics = chart_semantics_dict(report)
    scenarios = scenario_dict(report)
    warnings = content_warnings(report)

    if auto_patch:
        updated_data, patches = apply_safe_patches(
            data,
            report,
            remove_broken_chart_markers=not query_requests_charts(report.query),
        )
        if patches:
            try:
                patched_report = ResearchReport(**updated_data)
            except ValidationError as e:
                return _gate_payload(
                    passes_gate=False,
                    fmt=fmt_ok,
                    charts=charts,
                    scenarios=scenarios,
                    chart_render=chart_render,
                    chart_semantics=chart_semantics,
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
                    scenarios=scenarios,
                    chart_render=chart_render,
                    chart_semantics=chart_semantics,
                    warnings=warnings,
                    auto_patched=False,
                    patches_applied=patches,
                    blockers=[f"Failed to write patched report: {e}"],
                )

            raw2 = path.read_text(encoding="utf-8")
            data = json.loads(raw2)
            report = ResearchReport(**data)
            charts = charts_dict(report)
            chart_render = chart_render_dict(report)
            chart_semantics = chart_semantics_dict(report)
            warnings = content_warnings(report)
            scenarios = scenario_dict(report)
            blockers = structural_blockers(
                charts,
                scenarios,
                chart_render,
                chart_semantics,
                chart_required=query_requests_charts(report.query),
            )
            passes = len(blockers) == 0
            return _gate_payload(
                passes_gate=passes,
                fmt=fmt_ok,
                charts=charts,
                scenarios=scenarios,
                chart_render=chart_render,
                chart_semantics=chart_semantics,
                warnings=warnings,
                auto_patched=True,
                patches_applied=patches,
                blockers=blockers,
            )

    blockers = structural_blockers(
        charts,
        scenarios,
        chart_render,
        chart_semantics,
        chart_required=query_requests_charts(report.query),
    )
    passes = len(blockers) == 0
    return _gate_payload(
        passes_gate=passes,
        fmt=fmt_ok,
        charts=charts,
        scenarios=scenarios,
        chart_render=chart_render,
        chart_semantics=chart_semantics,
        warnings=warnings,
        auto_patched=False,
        patches_applied=[],
        blockers=blockers,
    )
