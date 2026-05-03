"""Static validation and safe auto-patches for report.json (technical writer gate engine).

Blocking gate (``passes_gate``):
    - Valid JSON and ``ResearchReport`` schema (Pydantic).
    - Chart markers ``<!-- CHART:id -->`` resolve to keys in ``report.charts`` after optional
      auto-patch (strip unknown markers).
    - Scenario/stress prompts include a valid base/bull/bear ``scenario_table``.

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

_SCENARIO_QUERY_KEYWORDS = (
    "scenario",
    "scenarios",
    "stress test",
    "stress testing",
    "base case",
    "bull case",
    "bear case",
)


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
    return {
        "valid": len(broken) == 0 and len(unreferenced) == 0,
        "broken_references": broken,
        "unreferenced_charts": unreferenced,
        "chart_count": len(marker_ids),
        "defined_charts": defined,
    }


def _is_finite_number(value: object) -> bool:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return numeric == numeric and numeric not in {float("inf"), float("-inf")}


def chart_render_dict(report: ResearchReport) -> dict:
    """Validate the deterministic subset of the frontend Recharts render contract."""

    issues: dict[str, list[str]] = {}
    for chart_id, chart_model in report.charts.items():
        chart = chart_model.model_dump()
        chart_issues: list[str] = []
        if chart.get("id") != chart_id:
            chart_issues.append(f"chart id mismatch: expected {chart_id}, got {chart.get('id')}")
        if not str(chart.get("title") or "").strip():
            chart_issues.append("chart title is required")
        data = chart.get("data")
        if not isinstance(data, list) or not data:
            chart_issues.append("chart data must include at least one row")
            issues[chart_id] = chart_issues
            continue

        chart_type = chart.get("type")
        if chart_type in {"line", "bar", "area", "composed"}:
            x_axis_key = chart.get("xAxisKey")
            series = chart.get("series")
            if not isinstance(x_axis_key, str) or not x_axis_key.strip():
                chart_issues.append("axis chart xAxisKey is required")
            elif any(
                not isinstance(row, dict) or row.get(x_axis_key) in {None, ""}
                for row in data
            ):
                chart_issues.append(f"one or more rows are missing xAxisKey {x_axis_key}")
            if not isinstance(series, list) or not series:
                chart_issues.append("axis chart series must include at least one item")
            else:
                for item in series:
                    data_key = item.get("dataKey") if isinstance(item, dict) else None
                    if not isinstance(data_key, str) or not data_key.strip():
                        chart_issues.append("series dataKey is required")
                        continue
                    if not any(
                        isinstance(row, dict) and _is_finite_number(row.get(data_key))
                        for row in data
                    ):
                        chart_issues.append(f"series {data_key} has no finite numeric values")
            if chart_issues:
                issues[chart_id] = chart_issues
            continue

        if chart_type == "scatter":
            for key_name in ("xKey", "yKey"):
                key = chart.get(key_name)
                if not isinstance(key, str) or not key.strip():
                    chart_issues.append(f"scatter chart {key_name} is required")
                    continue
                if not any(
                    isinstance(row, dict) and _is_finite_number(row.get(key))
                    for row in data
                ):
                    chart_issues.append(f"scatter key {key} has no finite numeric values")

        if chart_type == "pie":
            for index, row in enumerate(data):
                if not isinstance(row, dict):
                    chart_issues.append(f"pie slice {index} must be an object")
                    continue
                if not str(row.get("name") or "").strip():
                    chart_issues.append(f"pie slice {index} name is required")
                if not _is_finite_number(row.get("value")):
                    chart_issues.append(f"pie slice {index} value must be finite")

        if chart_issues:
            issues[chart_id] = chart_issues

    return {
        "valid": not issues,
        "issues": issues,
        "checked_charts": list(report.charts.keys()),
    }


def requires_scenario_table(report: ResearchReport) -> bool:
    query = report.query.lower()
    return any(keyword in query for keyword in _SCENARIO_QUERY_KEYWORDS)


def scenario_dict(report: ResearchReport) -> dict:
    rows = report.scenario_table or []
    row_names = [row.scenario for row in rows]
    missing = [name for name in ("base", "bull", "bear") if name not in row_names]
    required = requires_scenario_table(report)
    return {
        "required": required,
        "valid": (not required) or not missing,
        "row_count": len(rows),
        "scenarios": row_names,
        "missing_required_rows": missing if required else [],
    }


def format_dict_schema_ok() -> dict:
    """Legacy ``format`` key when schema succeeded (prose checks moved to ``warnings``)."""
    return {"valid": True, "schema_errors": [], "missing_elements": []}


def structural_blockers(
    charts: dict,
    scenarios: dict | None = None,
    chart_render: dict | None = None,
) -> list[str]:
    blockers: list[str] = []
    if not charts["valid"]:
        if charts["broken_references"]:
            blockers.append(f"broken chart references: {charts['broken_references']}")
        if charts.get("unreferenced_charts"):
            blockers.append(
                "charts defined in charts.json but not referenced in markdown: "
                f"{charts['unreferenced_charts']}"
            )
    if scenarios is not None and not scenarios["valid"]:
        blockers.append(
            "missing required scenario_table rows for scenario/stress query: "
            f"{scenarios['missing_required_rows']}"
        )
    if chart_render is not None and not chart_render["valid"]:
        blockers.append(
            "charts fail frontend Recharts render contract: "
            f"{chart_render['issues']}"
        )
    return blockers


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
    scenarios: dict | None,
    chart_render: dict | None,
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
        JSON string with passes_gate, format, charts, scenarios, warnings,
        auto_patched, patches_applied, and blockers.
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
            warnings=[],
            auto_patched=False,
            patches_applied=[],
            blockers=[f"Schema validation failed: {e}"],
        )

    fmt_ok = format_dict_schema_ok()
    charts = charts_dict(report)
    chart_render = chart_render_dict(report)
    scenarios = scenario_dict(report)
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
                    scenarios=scenarios,
                    chart_render=chart_render,
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
            warnings = content_warnings(report)
            scenarios = scenario_dict(report)
            blockers = structural_blockers(charts, scenarios, chart_render)
            passes = len(blockers) == 0
            return _gate_payload(
                passes_gate=passes,
                fmt=fmt_ok,
                charts=charts,
                scenarios=scenarios,
                chart_render=chart_render,
                warnings=warnings,
                auto_patched=True,
                patches_applied=patches,
                blockers=blockers,
            )

    blockers = structural_blockers(charts, scenarios, chart_render)
    passes = len(blockers) == 0
    return _gate_payload(
        passes_gate=passes,
        fmt=fmt_ok,
        charts=charts,
        scenarios=scenarios,
        chart_render=chart_render,
        warnings=warnings,
        auto_patched=False,
        patches_applied=[],
        blockers=blockers,
    )
