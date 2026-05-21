"""Artifact serialization for generated quant scripts."""

import sys
from pathlib import Path
from typing import Any

from ...artifact_fact_consistency import (
    artifact_fact_consistency_blocker,
    artifact_fact_consistency_dict,
)
from .chart_latest_facts import attach_chart_latest_numeric_facts
from .chart_provenance import normalize_chart_provenance
from .chart_source_validation import validate_chart_source_tables
from .evidence_bundle import build_evidence_bundle
from ..share_count_diagnostics import (
    append_share_count_limitation,
    source_series_uses_raw_shares,
    split_affected_share_count_diagnostics,
)
from .artifact_fingerprints import (
    build_artifact_fingerprints,
    finalize_evidence_bundle_fingerprint_bytes,
    json_artifact_bytes,
)
from .recharts_schema_normalization import (
    _chart_map_from_payload,
    _drop_empty_chart_definitions,
    _normalize_declared_since_lists,
)
from .source_unit_fidelity import (
    attach_source_unit_metadata,
    failed_unit_comparison_messages,
)
from .execution_summary_normalization import (
    build_quant_output_handoff,
    normalize_quant_execution_summary,
)


def save_quant_outputs(
    output_dir: str | Path,
    charts: dict[str, Any] | list[dict[str, Any]],
    execution_summary: dict[str, Any],
    *,
    statistical_summary_excerpt: str | None = None,
) -> dict[str, Any]:
    """Save canonical quant artifacts and return the compact handoff JSON.

    Generated ``analysis.py`` scripts use this to avoid custom serializers and
    stale ``chart_ids`` lists. The helper writes strict JSON with ``NaN`` values
    converted to ``None``.
    """

    if not isinstance(execution_summary, dict):
        raise ValueError("execution_summary must be a JSON object")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    charts_path = output_path / "charts.json"
    summary_path = output_path / "execution_summary.json"
    evidence_bundle_path = output_path / "evidence_bundle.json"

    input_chart_map = _chart_map_from_payload(charts)
    chart_source_validation = validate_chart_source_tables(input_chart_map)
    (
        chart_map,
        dropped_chart_ids,
        chart_normalization_issues,
        chart_projection_transforms,
    ) = _drop_empty_chart_definitions(input_chart_map)
    chart_ids = list(chart_map.keys())
    chart_render_validation = validate_chart_source_tables(chart_map)

    summary_seed = dict(execution_summary)
    _preserve_chart_provenance(chart_map, summary_seed, chart_ids)
    attach_chart_latest_numeric_facts(summary_seed, chart_map)
    summary = normalize_quant_execution_summary(summary_seed)
    _normalize_declared_since_lists(summary)
    _preserve_source_unit_contract(summary)
    _attach_generated_by(summary, output_path)
    _preserve_chart_provenance(chart_map, summary, chart_ids)
    _attach_raw_share_chart_limitations(chart_map, summary, chart_ids)
    attach_chart_latest_numeric_facts(summary, chart_map)

    summary["charts_json"] = str(charts_path)
    summary["execution_summary_json"] = str(summary_path)
    summary["evidence_bundle_json"] = str(evidence_bundle_path)
    summary["chart_ids"] = chart_ids
    chart_source_metadata = chart_source_validation.metadata_for_chart_ids(chart_ids)
    chart_render_metadata = chart_render_validation.metadata_for_chart_ids(chart_ids)
    if chart_source_metadata:
        summary["chart_source_table_validation"] = chart_source_metadata
    if chart_render_metadata:
        summary["chart_render_table_validation"] = chart_render_metadata
    if chart_projection_transforms:
        summary["chart_projection_transforms"] = _merge_chart_projection_transforms(
            summary.get("chart_projection_transforms"),
            chart_projection_transforms,
        )
    if dropped_chart_ids:
        summary["dropped_chart_ids"] = dropped_chart_ids
    if chart_normalization_issues:
        existing_issues = summary.get("chart_normalization_issues")
        merged_issues: dict[str, Any] = {}
        if not isinstance(existing_issues, dict):
            existing_issues = {}
        for chart_id, issues in existing_issues.items():
            if isinstance(issues, list):
                merged_issues[str(chart_id)] = list(issues)
            else:
                merged_issues[str(chart_id)] = [issues]
        for chart_id, issues in chart_normalization_issues.items():
            merged_issues.setdefault(chart_id, []).extend(issues)
        summary["chart_normalization_issues"] = merged_issues

    fact_consistency = artifact_fact_consistency_dict(
        execution_summary=summary,
        charts=chart_map,
    )
    fact_blocker = artifact_fact_consistency_blocker(fact_consistency)
    if fact_blocker:
        raise ValueError(fact_blocker)

    evidence_bundle = build_evidence_bundle(
        summary,
        chart_map,
        charts_json=str(charts_path),
        execution_summary_json=str(summary_path),
        evidence_bundle_json=str(evidence_bundle_path),
        artifact_fact_consistency=fact_consistency,
    )
    charts_bytes = json_artifact_bytes(chart_map)
    summary_bytes = json_artifact_bytes(summary)
    evidence_bundle.artifacts.fingerprints = build_artifact_fingerprints(
        charts_path=charts_path,
        execution_summary_path=summary_path,
        evidence_bundle_path=evidence_bundle_path,
        charts_bytes=charts_bytes,
        execution_summary_bytes=summary_bytes,
        source_files=evidence_bundle.artifacts.source_files,
        data_files=evidence_bundle.artifacts.data_files,
        base_dir=output_path,
        source_snapshots=evidence_bundle.artifacts.source_snapshots,
    )
    evidence_bundle_bytes = finalize_evidence_bundle_fingerprint_bytes(
        evidence_bundle
    )

    charts_path.write_bytes(charts_bytes)
    evidence_bundle_path.write_bytes(evidence_bundle_bytes)
    summary_path.write_bytes(summary_bytes)

    return build_quant_output_handoff(
        summary,
        charts_json=str(charts_path),
        execution_summary_json=str(summary_path),
        evidence_bundle_json=str(evidence_bundle_path),
        chart_ids=chart_ids,
        dropped_chart_ids=dropped_chart_ids,
        statistical_summary_excerpt=statistical_summary_excerpt,
    )


def _preserve_chart_provenance(
    chart_map: dict[str, Any],
    summary: dict[str, Any],
    chart_ids: list[str],
) -> None:
    """Mirror per-chart provenance between saved charts and execution summary."""

    summary_provenance = summary.get("chart_provenance")
    if not isinstance(summary_provenance, dict):
        summary_provenance = {}

    preserved: dict[str, Any] = {}
    for chart_id in chart_ids:
        chart = chart_map.get(chart_id)
        if not isinstance(chart, dict):
            continue

        provenance = normalize_chart_provenance(chart.get("provenance"))
        if not provenance:
            provenance = normalize_chart_provenance(summary_provenance.get(chart_id))
        if not provenance:
            continue

        chart["provenance"] = provenance
        preserved[chart_id] = provenance

    if preserved:
        summary["chart_provenance"] = preserved
    else:
        summary.pop("chart_provenance", None)


def _attach_raw_share_chart_limitations(
    chart_map: dict[str, Any],
    summary: dict[str, Any],
    chart_ids: list[str],
) -> None:
    """Mark raw share-count charts when helper diagnostics flag split effects."""

    if not split_affected_share_count_diagnostics(summary.get("share_count_diagnostics")):
        return

    summary_provenance = summary.get("chart_provenance")
    if not isinstance(summary_provenance, dict):
        summary_provenance = {}

    updated: dict[str, Any] = dict(summary_provenance)
    for chart_id in chart_ids:
        chart = chart_map.get(chart_id)
        if not isinstance(chart, dict):
            continue
        provenance = chart.get("provenance")
        if not isinstance(provenance, dict):
            provenance = normalize_chart_provenance(summary_provenance.get(chart_id))
        if not source_series_uses_raw_shares(provenance.get("source_series")):
            continue

        provenance = dict(provenance)
        provenance["limitations"] = append_share_count_limitation(
            provenance.get("limitations")
        )
        chart["provenance"] = provenance
        updated[str(chart_id)] = provenance

    if updated:
        summary["chart_provenance"] = updated


def _merge_chart_projection_transforms(
    existing_value: Any,
    generated: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if isinstance(existing_value, dict):
        for chart_id, value in existing_value.items():
            merged[str(chart_id)] = value
    elif isinstance(existing_value, list):
        for item in existing_value:
            if isinstance(item, dict) and isinstance(item.get("chart_id"), str):
                merged[item["chart_id"]] = item
    merged.update(generated)
    return merged


def _preserve_source_unit_contract(summary: dict[str, Any]) -> None:
    """Keep source units in the saved contract and fail invalid comparisons."""

    attach_source_unit_metadata(summary)
    errors = failed_unit_comparison_messages(summary)
    if errors:
        raise ValueError(errors[0])


def _attach_generated_by(summary: dict[str, Any], output_path: Path) -> None:
    script_path = _current_job_script_path(output_path)
    if script_path is None:
        return

    generated_by = summary.get("generated_by")
    if not isinstance(generated_by, dict):
        generated_by = {}
    generated_by["script_path"] = script_path
    summary["generated_by"] = generated_by


def _current_job_script_path(output_path: Path) -> str | None:
    argv0 = sys.argv[0] if sys.argv else ""
    if not argv0 or argv0 in {"-c", "-m"}:
        return None

    try:
        script_path = Path(argv0).expanduser().resolve()
        code_dir = (output_path / "code").resolve()
        script_path.relative_to(code_dir)
    except (OSError, ValueError):
        return None
    return str(script_path)
