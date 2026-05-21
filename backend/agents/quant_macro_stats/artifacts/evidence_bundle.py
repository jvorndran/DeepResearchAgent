"""Typed evidence-bundle sidecar for quant artifacts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agents.data_engineer.storage import SourceSnapshotDescriptor
from mcp_clients.market_data_provider import MARKET_VALUATION_SOURCE_ID
from mcp_clients.sec_edgar_contract import SEC_COMPANY_FACT_PROVENANCE_CONTRACT

from .chart_projection_contract import (
    ChartProjectionTransform,
    chart_projection_transforms_by_chart,
    chart_render_table_id,
    normalize_chart_projection_transforms,
)
from .artifact_fingerprints import ArtifactFingerprint
from .chart_provenance import normalize_chart_provenance
from .json_safety import to_json_safe
from .numeric_fact_contracts import normalize_numeric_facts
from .source_unit_fidelity import (
    normalize_source_unit_metadata,
    normalize_unit_comparisons,
)


_TRANSFORM_BASIS_KEYS = (
    "transform_basis",
    "correlation_basis",
    "correlation_transform",
    "value_transform",
    "calculation_basis",
)
TRANSFORM_BASIS_KEYS = _TRANSFORM_BASIS_KEYS
_SOURCE_DESCRIPTOR_KEYS = (
    "provider",
    "series_id",
    "concept_id",
    "title",
    "units",
    "unit_family",
    "unit_basis",
    "measure",
    "frequency",
    "currency",
    "fiscal_period",
    "taxonomy",
    "form",
    "filing_date",
    "accession_number",
    "transform_basis",
    "vintage",
    "as_of_date",
    "revision_policy",
    "source_url",
    "source_file",
    "status",
)


class _EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceDescriptor(_EvidenceModel):
    source_id: str
    provider: str | None = None
    series_id: str | None = None
    concept_id: str | None = None
    title: str | None = None
    units: str | None = None
    unit_family: str | None = None
    unit_basis: str | None = None
    measure: str | None = None
    frequency: str | None = None
    currency: str | None = None
    fiscal_period: str | None = None
    taxonomy: str | None = None
    form: str | None = None
    filing_date: str | None = None
    accession_number: str | None = None
    transform_basis: str | None = None
    vintage: str | None = None
    as_of_date: str | None = None
    revision_policy: str | None = None
    source_url: str | None = None
    source_file: str | None = None
    status: str | None = None
    coverage: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_id")
    @classmethod
    def _source_id_required(cls, value: str) -> str:
        return _require_text(value, "source_id")


class EvidenceSource(SourceDescriptor):
    """Backward-compatible name for source descriptors."""


class EvidenceTableRef(_EvidenceModel):
    table_id: str
    kind: Literal["raw", "normalized"]
    path: str | None = None
    source_id: str | None = None
    role: str | None = None
    row_count: int | None = None
    columns: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("table_id")
    @classmethod
    def _table_id_required(cls, value: str) -> str:
        return _require_text(value, "table_id")


class EvidenceFact(_EvidenceModel):
    fact_id: str
    label: str
    raw_value: float
    display_value: str
    unit: str
    precision: int
    tolerance: float
    source_key: str
    as_of_date: str | None = None
    subject: str | None = None
    metric: str | None = None
    semantic_role: str | None = None
    literal_required: bool | None = None
    state_description: str | None = None
    operation: str | None = None
    transform_basis: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("fact_id", "label", "display_value", "unit", "source_key")
    @classmethod
    def _text_fields_required(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)


class EvidenceChart(_EvidenceModel):
    chart_id: str
    chart_type: str | None = None
    title: str | None = None
    description: str | None = None
    x_axis_key: str | None = None
    series_keys: list[str] = Field(default_factory=list)
    source_series: list[str] = Field(default_factory=list)
    source_table_ids: list[str] = Field(min_length=1)
    transform_ids: list[str] = Field(min_length=1)
    data_row_count: int | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)

    @field_validator("chart_id")
    @classmethod
    def _chart_id_required(cls, value: str) -> str:
        return _require_text(value, "chart_id")

    @field_validator("source_table_ids", "transform_ids")
    @classmethod
    def _traceability_ids_required(cls, value: list[str], info: Any) -> list[str]:
        ids = _text_list(value)
        if not ids:
            raise ValueError(f"{info.field_name} must cite at least one ID")
        return ids

    @model_validator(mode="after")
    def _data_rows_require_source_lineage(self):
        if (self.data_row_count or 0) <= 0:
            return self
        if self.source_series or _source_ids_from_chart_provenance(self.provenance):
            return self
        raise ValueError(
            "charts with data rows must include chart provenance source_series "
            "or source_files; attach chart_provenance(source_series=[...]) or "
            "chart_provenance(source_files={...}) before saving"
        )


class ConversionDescriptor(_EvidenceModel):
    source_conversions: dict[str, str] = Field(default_factory=dict)
    from_unit: str | None = None
    to_unit: str | None = None
    input_unit: str | None = None
    output_unit: str | None = None
    factor: float | None = None
    formula: str | None = None
    basis: str | None = None

    @field_validator("source_conversions", mode="before")
    @classmethod
    def _source_conversions_are_text(cls, value: Any) -> dict[str, str]:
        if not _has_value(value):
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("source_conversions must be a mapping")
        out: dict[str, str] = {}
        for key, child in value.items():
            source_id = _clean_text(key)
            detail = _clean_text(child)
            if source_id is not None and detail is not None:
                out[source_id] = detail
        return out

    @field_validator(
        "from_unit",
        "to_unit",
        "input_unit",
        "output_unit",
        "formula",
        "basis",
        mode="before",
    )
    @classmethod
    def _optional_text(cls, value: Any) -> str | None:
        return _clean_text(value)

    @field_validator("factor", mode="before")
    @classmethod
    def _factor_is_numeric(cls, value: Any) -> float | None:
        if not _has_value(value):
            return None
        if isinstance(value, bool):
            raise ValueError("factor must be numeric")
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("factor must be numeric") from exc

    @model_validator(mode="after")
    def _requires_structured_detail(self):
        if self.source_conversions or _has_explicit_unit_conversion_details(self):
            return self
        raise ValueError(
            "conversion must include source-specific conversion details or "
            "from/to unit conversion details"
        )


class TransformDescriptor(_EvidenceModel):
    transform_id: str
    operation: str | None = None
    transform_basis: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    source_groups: list[list[str]] = Field(default_factory=list)
    source_table_ids: list[str] = Field(default_factory=list)
    chart_ids: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    input_unit_families: list[str] = Field(default_factory=list)
    input_unit_bases: list[str] = Field(default_factory=list)
    input_frequencies: list[str] = Field(default_factory=list)
    output_unit_family: str | None = None
    output_unit_basis: str | None = None
    output_frequency: str | None = None
    period_key: str | None = None
    resampling: str | None = None
    conversion: ConversionDescriptor | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("transform_id")
    @classmethod
    def _transform_id_required(cls, value: str) -> str:
        return _require_text(value, "transform_id")

    @field_validator(
        "source_ids",
        "source_table_ids",
        "chart_ids",
        "fact_ids",
        "input_unit_families",
        "input_unit_bases",
        "input_frequencies",
    )
    @classmethod
    def _text_list_fields(cls, value: list[str]) -> list[str]:
        return _text_list(value)

    @field_validator("source_groups", mode="before")
    @classmethod
    def _source_groups_are_text_ids(cls, value: Any) -> list[list[str]]:
        return _source_groups_from_payload(value)

    @field_validator("conversion", mode="before")
    @classmethod
    def _conversion_requires_mapping(
        cls,
        value: Any,
    ) -> ConversionDescriptor | dict[str, Any] | None:
        if not _has_value(value):
            return None
        if isinstance(value, ConversionDescriptor):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("conversion must be a non-empty mapping")
        return _conversion_descriptor_payload(value)

    @model_validator(mode="after")
    def _basis_required_for_derived_operations(self):
        if _transform_requires_basis(self) and not self.transform_basis:
            raise ValueError(
                "transform_basis is required for correlation, growth-rate, "
                f"spread, or normalized-index transform {self.transform_id!r}"
            )
        return self


class EvidenceDiagnostic(_EvidenceModel):
    level: Literal["info", "warning", "error"]
    code: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("code", "message")
    @classmethod
    def _diagnostic_text_required(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)


class EvidenceValidation(_EvidenceModel):
    valid: bool = True
    diagnostics: list[EvidenceDiagnostic] = Field(default_factory=list)
    artifact_fact_consistency: dict[str, Any] = Field(default_factory=dict)
    chart_normalization_issues: dict[str, Any] = Field(default_factory=dict)
    dropped_chart_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valid_has_no_errors(self):
        if self.valid:
            errors = [
                diagnostic.code
                for diagnostic in self.diagnostics
                if diagnostic.level == "error"
            ]
            if errors:
                raise ValueError(
                    "valid evidence bundles cannot include error diagnostics: "
                    + ", ".join(errors)
                )
        return self


class EvidenceArtifacts(_EvidenceModel):
    charts_json: str
    execution_summary_json: str
    evidence_bundle_json: str
    generated_by: dict[str, Any] = Field(default_factory=dict)
    source_files: dict[str, str] = Field(default_factory=dict)
    data_files: dict[str, str] = Field(default_factory=dict)
    source_snapshots: dict[str, SourceSnapshotDescriptor] = Field(default_factory=dict)
    fingerprints: list[ArtifactFingerprint] = Field(default_factory=list)

    @field_validator("charts_json", "execution_summary_json", "evidence_bundle_json")
    @classmethod
    def _artifact_path_required(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @model_validator(mode="after")
    def _fingerprint_ids_unique(self):
        _require_unique(
            "artifacts.fingerprints.artifact_id",
            (fingerprint.artifact_id for fingerprint in self.fingerprints),
        )
        return self


class EvidenceBundle(_EvidenceModel):
    schema_version: Literal[1] = 1
    bundle_type: Literal["quant_evidence_bundle"] = "quant_evidence_bundle"
    sources: list[SourceDescriptor] = Field(default_factory=list)
    raw_tables: list[EvidenceTableRef] = Field(default_factory=list)
    normalized_tables: list[EvidenceTableRef] = Field(default_factory=list)
    facts: list[EvidenceFact] = Field(default_factory=list)
    charts: list[EvidenceChart] = Field(default_factory=list)
    transforms: list[TransformDescriptor] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    validation: EvidenceValidation
    artifacts: EvidenceArtifacts

    @model_validator(mode="after")
    def _stable_ids_are_unique(self):
        _require_unique("facts.fact_id", (fact.fact_id for fact in self.facts))
        _require_unique("charts.chart_id", (chart.chart_id for chart in self.charts))
        _require_unique(
            "sources.source_id",
            (source.source_id for source in self.sources),
        )
        _require_unique(
            "raw_tables.table_id",
            (table.table_id for table in self.raw_tables),
        )
        _require_unique(
            "normalized_tables.table_id",
            (table.table_id for table in self.normalized_tables),
        )
        _require_unique(
            "transforms.transform_id",
            (transform.transform_id for transform in self.transforms),
        )
        _require_table_ids_unique_across_kinds(
            self.raw_tables,
            self.normalized_tables,
        )
        _require_fact_sources_resolve(self.facts, self.sources)
        _require_table_sources_resolve(
            [*self.raw_tables, *self.normalized_tables],
            self.sources,
        )
        _require_chart_traceability(
            self.charts,
            [*self.raw_tables, *self.normalized_tables],
        )
        _require_chart_transforms_resolve(self.charts, self.transforms)
        _require_transform_references_resolve(
            self.transforms,
            self.sources,
            [*self.raw_tables, *self.normalized_tables],
        )
        _require_transform_source_semantics(self.transforms, self.sources)
        _require_fact_transform_basis(self.facts)
        _require_sec_company_fact_provenance(self.facts)
        _require_market_valuation_unavailable_contract(self.sources)
        return self


def build_evidence_bundle(
    summary: Mapping[str, Any],
    charts: Mapping[str, Any],
    *,
    charts_json: str,
    execution_summary_json: str,
    evidence_bundle_json: str,
    artifact_fact_consistency: Mapping[str, Any] | None = None,
) -> EvidenceBundle:
    """Build the canonical typed evidence bundle from normalized artifacts."""

    chart_map = {str(chart_id): chart for chart_id, chart in charts.items()}
    chart_ids = list(chart_map)
    declared_chart_ids = _text_list(summary.get("chart_ids"))
    if declared_chart_ids and declared_chart_ids != chart_ids:
        raise ValueError(
            "evidence_bundle chart_ids must match charts.json keys: "
            f"execution_summary.chart_ids={declared_chart_ids} charts={chart_ids}"
        )

    facts = [
        _fact_from_numeric_fact(fact)
        for fact in normalize_numeric_facts(summary.get("numeric_facts"), strict=True)
    ]
    diagnostics = _validation_diagnostics(summary, artifact_fact_consistency)
    validation = EvidenceValidation(
        valid=not any(diagnostic.level == "error" for diagnostic in diagnostics),
        diagnostics=diagnostics,
        artifact_fact_consistency=_clean_mapping(artifact_fact_consistency) or {},
        chart_normalization_issues=_clean_mapping(
            summary.get("chart_normalization_issues")
        )
        or {},
        dropped_chart_ids=_text_list(summary.get("dropped_chart_ids")),
    )
    if not validation.valid:
        first_error = next(
            diagnostic.message
            for diagnostic in validation.diagnostics
            if diagnostic.level == "error"
        )
        raise ValueError(f"evidence_bundle validation failed: {first_error}")

    raw_tables = _table_refs(summary, kind="raw", charts=chart_map)
    normalized_tables = _table_refs(summary, kind="normalized", charts=chart_map)
    table_ids = {table.table_id for table in [*raw_tables, *normalized_tables]}
    sources = _source_descriptors(
        summary,
        facts=facts,
        charts=chart_map,
        table_refs=[*raw_tables, *normalized_tables],
    )
    bundle_charts = [
        _chart_from_payload(chart_id, chart, summary, table_ids=table_ids)
        for chart_id, chart in chart_map.items()
    ]

    return EvidenceBundle(
        sources=sources,
        raw_tables=raw_tables,
        normalized_tables=normalized_tables,
        facts=facts,
        charts=bundle_charts,
        transforms=_transform_descriptors(
            summary,
            charts=chart_map,
            chart_refs=bundle_charts,
            facts=facts,
            sources=sources,
        ),
        methods=_methods(summary.get("methods_used")),
        limitations=_limitations(summary.get("limitations")),
        validation=validation,
        artifacts=EvidenceArtifacts(
            charts_json=str(charts_json),
            execution_summary_json=str(execution_summary_json),
            evidence_bundle_json=str(evidence_bundle_json),
            generated_by=_clean_mapping(summary.get("generated_by")) or {},
            source_files=_path_mapping(summary.get("source_files")),
            data_files=_data_file_mapping(summary),
            source_snapshots=_source_snapshot_mapping(summary),
        ),
    )


def _fact_from_numeric_fact(fact: dict[str, Any]) -> EvidenceFact:
    known = {
        "id",
        "label",
        "raw_value",
        "display_value",
        "unit",
        "precision",
        "tolerance",
        "source_key",
        "as_of_date",
        "subject",
        "metric",
        "semantic_role",
        "literal_required",
        "state_description",
        "operation",
        "transform_basis",
        "correlation_basis",
        "correlation_transform",
        "value_transform",
        "calculation_basis",
    }
    transform_basis = _first_text(
        fact.get("transform_basis"),
        fact.get("correlation_basis"),
        fact.get("correlation_transform"),
        fact.get("value_transform"),
        fact.get("calculation_basis"),
    )
    return EvidenceFact(
        fact_id=str(fact["id"]),
        label=str(fact["label"]),
        raw_value=float(fact["raw_value"]),
        display_value=str(fact["display_value"]),
        unit=str(fact["unit"]),
        precision=int(fact["precision"]),
        tolerance=float(fact["tolerance"]),
        source_key=str(fact["source_key"]),
        as_of_date=_clean_text(fact.get("as_of_date")),
        subject=_clean_text(fact.get("subject")),
        metric=_clean_text(fact.get("metric")),
        semantic_role=_clean_text(fact.get("semantic_role")),
        literal_required=fact.get("literal_required")
        if isinstance(fact.get("literal_required"), bool)
        else None,
        state_description=_clean_text(fact.get("state_description")),
        operation=_clean_text(fact.get("operation")),
        transform_basis=transform_basis,
        attributes={
            str(key): to_json_safe(value)
            for key, value in fact.items()
            if key not in known and _has_value(value)
        },
    )


def _chart_from_payload(
    chart_id: str,
    chart: Any,
    summary: Mapping[str, Any],
    *,
    table_ids: set[str],
) -> EvidenceChart:
    payload = chart if isinstance(chart, Mapping) else {}
    provenance = _chart_provenance(chart_id, payload, summary)
    projection = _chart_projection_by_chart(summary).get(chart_id)
    source_table_ids = _source_table_ids_for_chart(
        chart_id,
        payload,
        provenance,
        table_ids=table_ids,
    )
    source_ids = _source_ids_from_chart_provenance(provenance)
    if projection is not None and source_ids:
        source_table_ids = _unique_texts(
            [
                projection.source_table_id,
                projection.render_table_id,
                *source_table_ids,
            ]
        )

    data = payload.get("data")
    return EvidenceChart(
        chart_id=chart_id,
        chart_type=_clean_text(payload.get("type")),
        title=_clean_text(payload.get("title")),
        description=_clean_text(payload.get("description")),
        x_axis_key=_chart_axis_key(payload),
        series_keys=_chart_series_keys(payload),
        source_series=_source_series_from_provenance(provenance),
        source_table_ids=source_table_ids,
        transform_ids=_chart_transform_ids(chart_id, payload, provenance, summary),
        data_row_count=len(data) if isinstance(data, list) else None,
        provenance=provenance,
    )


def _source_descriptors(
    summary: Mapping[str, Any],
    *,
    facts: list[EvidenceFact],
    charts: Mapping[str, Any] | None = None,
    table_refs: list[EvidenceTableRef] | None = None,
) -> list[SourceDescriptor]:
    by_id: dict[str, dict[str, Any]] = {}

    def merge(source_id: str | None, **values: Any) -> None:
        cleaned_id = _clean_text(source_id)
        if cleaned_id is None:
            return
        current = by_id.setdefault(cleaned_id, {"source_id": cleaned_id})
        metadata = values.pop("metadata", None)
        coverage = values.pop("coverage", None)
        for key, value in values.items():
            if _has_value(value) and not _has_value(current.get(key)):
                current[key] = to_json_safe(value)
        if isinstance(metadata, Mapping):
            current.setdefault("metadata", {}).update(_clean_mapping(metadata) or {})
        if isinstance(coverage, Mapping):
            current.setdefault("coverage", {}).update(_clean_mapping(coverage) or {})

    coverage = summary.get("source_coverage")
    if isinstance(coverage, Mapping):
        for source_id, value in coverage.items():
            provider = str(source_id)
            if isinstance(value, Mapping):
                merge(
                    str(source_id),
                    **_source_descriptor_values(
                        value,
                        provider_fallback=provider,
                    ),
                    coverage=value,
                    metadata=value,
                )
            else:
                merge(
                    str(source_id),
                    provider=provider,
                    status="covered" if _has_value(value) else None,
                    coverage={"value": to_json_safe(value)} if _has_value(value) else {},
                )

    for record in normalize_source_unit_metadata(summary.get("source_unit_metadata")):
        source_id = _first_text(
            record.get("source_key"),
            record.get("series_id"),
            record.get("source_file"),
            record.get("title"),
        )
        merge(
            source_id,
            **_source_descriptor_values(record),
            metadata=record,
        )

    for source_id, source_file in {
        **_path_mapping(summary.get("source_files")),
        **_data_file_mapping(summary),
    }.items():
        merge(source_id, source_file=source_file)

    for source_id, snapshot in _source_snapshot_mapping(summary).items():
        snapshot_payload = _source_snapshot_payload(snapshot)
        if not snapshot_payload:
            continue
        merge(
            source_id,
            provider=snapshot_payload.get("provider"),
            source_url=snapshot_payload.get("endpoint"),
            source_file=snapshot_payload.get("path"),
            revision_policy=snapshot_payload.get("freshness_policy"),
            metadata={"source_snapshot": snapshot_payload},
        )

    for chart_id, provenance in _chart_provenance_items(charts or {}, summary):
        for source_id in _source_ids_from_chart_provenance(provenance):
            merge(
                source_id,
                provider=source_id,
                metadata={
                    "inferred_from_chart_provenance": True,
                    "chart_id": chart_id,
                },
            )

    for table in table_refs or []:
        if table.source_id:
            merge(
                table.source_id,
                source_file=table.path,
                metadata={
                    "table_id": table.table_id,
                    "table_kind": table.kind,
                    "table_role": table.role,
                },
            )

    for source_id in _source_ids_from_fact_keys(facts):
        merge(
            source_id,
            provider=source_id,
            metadata={"inferred_from_fact_source_key": True},
        )

    return [SourceDescriptor(**payload) for payload in by_id.values()]


def _source_descriptor_values(
    record: Mapping[str, Any],
    *,
    provider_fallback: str | None = None,
) -> dict[str, Any]:
    values = {
        key: _clean_text(record.get(key))
        for key in _SOURCE_DESCRIPTOR_KEYS
        if _has_value(record.get(key))
    }
    provider = _first_text(
        record.get("provider"),
        record.get("source"),
        provider_fallback,
    )
    if provider:
        values["provider"] = provider
    transform_basis = _first_text(
        record.get("transform_basis"),
        record.get("transformation")
        if isinstance(record.get("transformation"), str)
        else None,
    )
    if transform_basis:
        values["transform_basis"] = transform_basis
    return values


def _table_refs(
    summary: Mapping[str, Any],
    *,
    kind: Literal["raw", "normalized"],
    charts: Mapping[str, Any],
) -> list[EvidenceTableRef]:
    refs: list[EvidenceTableRef] = []
    if kind == "raw":
        for table_id, path in {
            **_path_mapping(summary.get("source_files")),
            **_data_file_mapping(summary),
        }.items():
            refs.append(
                EvidenceTableRef(
                    table_id=table_id,
                    kind="raw",
                    path=path,
                    source_id=table_id,
                    role="source_file",
                )
            )
        refs.extend(_raw_table_refs_from_chart_provenance(charts, summary))

    summary_key = "raw_tables" if kind == "raw" else "normalized_tables"
    for ref in _table_refs_from_summary(summary.get(summary_key), kind=kind):
        refs.append(ref)
    if kind == "normalized":
        refs.extend(_chart_data_table_refs(charts, summary))
    return _dedupe_table_refs(refs)


def _raw_table_refs_from_chart_provenance(
    charts: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> list[EvidenceTableRef]:
    refs: list[EvidenceTableRef] = []
    for chart_id, provenance in _chart_provenance_items(charts, summary):
        for table_id, path in _source_file_items(provenance.get("source_files")):
            refs.append(
                EvidenceTableRef(
                    table_id=table_id,
                    kind="raw",
                    path=path,
                    source_id=table_id,
                    role="chart_provenance_source_file",
                    metadata={"chart_id": chart_id},
                )
            )
    return refs


def _chart_data_table_refs(
    charts: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> list[EvidenceTableRef]:
    refs: list[EvidenceTableRef] = []
    projection_by_chart = _chart_projection_by_chart(summary)
    for chart_id, chart in charts.items():
        payload = chart if isinstance(chart, Mapping) else {}
        provenance = _chart_provenance(chart_id, payload, summary)
        source_ids = _source_ids_from_chart_provenance(provenance)
        projection = projection_by_chart.get(str(chart_id))
        if projection is not None:
            if not source_ids:
                continue
            refs.extend(
                _projected_chart_table_refs(
                    str(chart_id),
                    projection,
                    source_ids=source_ids,
                    summary=summary,
                )
            )
            continue

        data = payload.get("data")
        if not source_ids or not isinstance(data, list) or not data:
            continue
        metadata = {
            "chart_id": chart_id,
            "source_ids": source_ids,
        }
        chart_source_validation = _chart_source_validation_metadata(summary, chart_id)
        if chart_source_validation:
            metadata["chart_source_table_validation"] = chart_source_validation
        refs.append(
            EvidenceTableRef(
                table_id=_chart_data_table_id(chart_id),
                kind="normalized",
                source_id=source_ids[0] if len(source_ids) == 1 else None,
                role="chart_data",
                row_count=len(data),
                columns=_chart_data_columns(payload),
                metadata=metadata,
            )
        )
    return refs


def _projected_chart_table_refs(
    chart_id: str,
    projection: ChartProjectionTransform,
    *,
    source_ids: list[str],
    summary: Mapping[str, Any],
) -> list[EvidenceTableRef]:
    source_metadata = {
        "chart_id": chart_id,
        "source_ids": source_ids,
        "chart_projection_transform_id": projection.transform_id,
        "chart_projection_role": "source",
    }
    source_validation = _chart_source_validation_metadata(summary, chart_id)
    if source_validation:
        source_metadata["chart_source_table_validation"] = source_validation

    render_metadata = {
        "chart_id": chart_id,
        "source_ids": source_ids,
        "chart_projection_transform_id": projection.transform_id,
        "chart_projection_role": "render",
    }
    render_validation = _chart_render_validation_metadata(summary, chart_id)
    if render_validation:
        render_metadata["chart_render_table_validation"] = render_validation

    return [
        EvidenceTableRef(
            table_id=projection.source_table_id,
            kind="normalized",
            source_id=source_ids[0] if len(source_ids) == 1 else None,
            role="chart_source_data",
            row_count=projection.source_row_count,
            columns=projection.source_columns,
            metadata=source_metadata,
        ),
        EvidenceTableRef(
            table_id=projection.render_table_id,
            kind="normalized",
            source_id=source_ids[0] if len(source_ids) == 1 else None,
            role="chart_data",
            row_count=projection.render_row_count,
            columns=projection.render_columns,
            metadata=render_metadata,
        ),
    ]


def _chart_source_validation_metadata(
    summary: Mapping[str, Any],
    chart_id: str,
) -> dict[str, Any]:
    return _chart_validation_metadata(summary, chart_id, "chart_source_table_validation")


def _chart_render_validation_metadata(
    summary: Mapping[str, Any],
    chart_id: str,
) -> dict[str, Any]:
    return _chart_validation_metadata(summary, chart_id, "chart_render_table_validation")


def _chart_validation_metadata(
    summary: Mapping[str, Any],
    chart_id: str,
    key: str,
) -> dict[str, Any]:
    validation = summary.get(key)
    if not isinstance(validation, Mapping):
        return {}
    metadata = validation.get(chart_id)
    if not isinstance(metadata, Mapping):
        return {}
    return _clean_mapping(metadata) or {}


def _table_refs_from_summary(
    value: Any,
    *,
    kind: Literal["raw", "normalized"],
) -> list[EvidenceTableRef]:
    if isinstance(value, Mapping):
        candidates = value.items()
    elif isinstance(value, list):
        candidates = enumerate(value)
    else:
        return []

    refs: list[EvidenceTableRef] = []
    for fallback_id, candidate in candidates:
        fallback_text = str(fallback_id)
        if isinstance(candidate, Mapping):
            table_id = _first_text(
                candidate.get("table_id"),
                candidate.get("id"),
                candidate.get("name"),
                candidate.get("source_key"),
                fallback_text,
            )
            if table_id is None:
                continue
            columns = candidate.get("columns")
            refs.append(
                EvidenceTableRef(
                    table_id=table_id,
                    kind=kind,
                    path=_clean_text(candidate.get("path") or candidate.get("file_path")),
                    source_id=_clean_text(candidate.get("source_id")),
                    role=_clean_text(candidate.get("role")),
                    row_count=_int_or_none(candidate.get("row_count")),
                    columns=[str(column) for column in columns]
                    if isinstance(columns, list)
                    else [],
                    metadata=_clean_mapping(candidate) or {},
                )
            )
        elif _has_value(candidate):
            refs.append(
                EvidenceTableRef(
                    table_id=fallback_text,
                    kind=kind,
                    path=str(candidate),
                )
            )
    return refs


def _validation_diagnostics(
    summary: Mapping[str, Any],
    artifact_fact_consistency: Mapping[str, Any] | None,
) -> list[EvidenceDiagnostic]:
    diagnostics: list[EvidenceDiagnostic] = []
    chart_issues = summary.get("chart_normalization_issues")
    if isinstance(chart_issues, Mapping):
        for chart_id, issues in chart_issues.items():
            diagnostics.append(
                EvidenceDiagnostic(
                    level="warning",
                    code="chart_normalization_issues",
                    message=f"Chart {chart_id} had normalization issues.",
                    metadata={"chart_id": str(chart_id), "issues": to_json_safe(issues)},
                )
            )
    for chart_id in _text_list(summary.get("dropped_chart_ids")):
        diagnostics.append(
            EvidenceDiagnostic(
                level="info",
                code="dropped_empty_chart",
                message=f"Chart {chart_id} was dropped before handoff.",
                metadata={"chart_id": chart_id},
            )
        )
    source_errors = summary.get("source_unit_errors")
    if isinstance(source_errors, list):
        for error in source_errors:
            diagnostics.append(
                EvidenceDiagnostic(
                    level="error",
                    code="source_unit_error",
                    message=str(error),
                )
            )
    elif _has_value(source_errors):
        diagnostics.append(
            EvidenceDiagnostic(
                level="error",
                code="source_unit_error",
                message=str(source_errors),
            )
        )
    if artifact_fact_consistency and not artifact_fact_consistency.get("valid", True):
        diagnostics.append(
            EvidenceDiagnostic(
                level="error",
                code="artifact_fact_mismatch",
                message="Quant artifacts contain conflicting repeated facts.",
                metadata=_clean_mapping(artifact_fact_consistency) or {},
            )
        )
    return diagnostics


def _methods(value: Any) -> list[str]:
    return _text_list(value)


def _limitations(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        out: list[str] = []
        for key, item in value.items():
            for child in _text_list(item):
                out.append(f"{key}: {child}")
        return _unique_texts(out)
    return _text_list(value)


def _chart_axis_key(payload: Mapping[str, Any]) -> str | None:
    direct = _first_text(
        payload.get("xAxisKey"),
        payload.get("xKey"),
        payload.get("angleKey"),
        payload.get("nameKey"),
    )
    if direct:
        return direct
    x_axis = payload.get("xAxis")
    if isinstance(x_axis, Mapping):
        return _clean_text(x_axis.get("dataKey"))
    return None


def _chart_series_keys(payload: Mapping[str, Any]) -> list[str]:
    keys: list[str] = []
    series = payload.get("series")
    if isinstance(series, list):
        for item in series:
            if isinstance(item, Mapping):
                keys.extend(_text_list(_first_text(item.get("dataKey"), item.get("key"))))
    for key in ("dataKey", "yKey", "sizeKey", "colorKey", "valueKey"):
        value = _clean_text(payload.get(key))
        if value:
            keys.append(value)
    return _unique_texts(keys)


def _chart_data_columns(payload: Mapping[str, Any]) -> list[str]:
    columns: list[str] = []
    data = payload.get("data")
    if isinstance(data, list):
        for row in data:
            if isinstance(row, Mapping):
                columns.extend(str(key) for key in row)
    if axis_key := _chart_axis_key(payload):
        columns.append(axis_key)
    columns.extend(_chart_series_keys(payload))
    return _unique_texts(columns)


def _chart_provenance(
    chart_id: str,
    payload: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    provenance = normalize_chart_provenance(payload.get("provenance"))
    if provenance:
        return provenance

    summary_provenance = summary.get("chart_provenance")
    if isinstance(summary_provenance, Mapping):
        return normalize_chart_provenance(summary_provenance.get(chart_id))
    return {}


def _chart_provenance_items(
    charts: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    items: list[tuple[str, dict[str, Any]]] = []
    for chart_id, chart in charts.items():
        payload = chart if isinstance(chart, Mapping) else {}
        provenance = _chart_provenance(str(chart_id), payload, summary)
        if provenance:
            items.append((str(chart_id), provenance))
    return items


def _chart_projection_by_chart(
    summary: Mapping[str, Any],
) -> dict[str, ChartProjectionTransform]:
    return chart_projection_transforms_by_chart(
        summary.get("chart_projection_transforms")
    )


def _source_series_from_provenance(provenance: Mapping[str, Any]) -> list[str]:
    value = provenance.get("source_series")
    if isinstance(value, Mapping):
        values = [_clean_text(child) for child in value.values()]
        if any(values):
            return _unique_texts(child for child in values if child)
        return _unique_texts(str(key) for key in value)
    return _text_list(value)


def _source_table_ids_for_chart(
    chart_id: str,
    payload: Mapping[str, Any],
    provenance: Mapping[str, Any],
    *,
    table_ids: set[str],
) -> list[str]:
    candidate_ids: list[str] = []
    source_files = provenance.get("source_files")
    candidate_ids.extend(table_id for table_id, _ in _source_file_items(source_files))
    candidate_ids.extend(
        source_id
        for source_id in _source_series_from_provenance(provenance)
        if source_id in table_ids
    )

    chart_data_table_id = _chart_data_table_id(chart_id)
    if not candidate_ids and chart_data_table_id in table_ids:
        candidate_ids.append(chart_data_table_id)
    if not candidate_ids:
        candidate_ids.extend(_text_list(payload.get("source_table_id")))
        candidate_ids.extend(_text_list(payload.get("source_table_ids")))

    return _unique_texts(candidate_ids)


def _source_ids_from_chart_provenance(provenance: Mapping[str, Any]) -> list[str]:
    source_ids = _source_series_from_provenance(provenance)
    source_ids.extend(
        table_id
        for table_id, _ in _source_file_items(provenance.get("source_files"))
    )
    return _unique_texts(source_ids)


def _source_file_items(value: Any) -> list[tuple[str, str]]:
    if isinstance(value, Mapping):
        return [
            (str(source_id), str(path))
            for source_id, path in value.items()
            if _has_value(source_id) and _has_value(path)
        ]
    if isinstance(value, list):
        return [
            (Path(str(path)).stem, str(path))
            for path in value
            if _has_value(path)
        ]
    return []


def _chart_data_table_id(chart_id: str) -> str:
    return chart_render_table_id(chart_id)


def _chart_transform_ids(
    chart_id: str,
    payload: Mapping[str, Any],
    provenance: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> list[str]:
    transforms: list[str] = []
    for key in (
        "transform_id",
        "transform_ids",
        "methods_used",
        "transform_basis",
        "correlation_basis",
        "correlation_transform",
        "value_transform",
        "calculation_basis",
    ):
        transforms.extend(_text_list(payload.get(key)))
    if _has_value(provenance.get("resampling")):
        transforms.append("resampling")
    normalization = provenance.get("normalization")
    if isinstance(normalization, Mapping):
        transforms.extend(f"normalization.{key}" for key in normalization)
    elif _has_value(normalization):
        transforms.append("normalization")
    if not transforms:
        transforms.extend(_methods(summary.get("methods_used")))
    projection = _chart_projection_by_chart(summary).get(chart_id)
    if projection is not None:
        transforms.append(projection.transform_id)
    return _unique_texts(transforms)


def _transform_descriptors(
    summary: Mapping[str, Any],
    *,
    charts: Mapping[str, Any],
    chart_refs: list[EvidenceChart],
    facts: list[EvidenceFact],
    sources: list[SourceDescriptor],
) -> list[TransformDescriptor]:
    by_id: dict[str, dict[str, Any]] = {}
    source_ids = {source.source_id for source in sources}

    def merge(transform_id: str | None, **values: Any) -> None:
        cleaned_id = _clean_text(transform_id)
        if cleaned_id is None:
            return
        current = by_id.setdefault(cleaned_id, {"transform_id": cleaned_id})
        metadata = values.pop("metadata", None)
        for key in (
            "source_ids",
            "source_table_ids",
            "chart_ids",
            "fact_ids",
            "input_unit_families",
            "input_unit_bases",
            "input_frequencies",
        ):
            current[key] = _unique_texts(
                [*current.get(key, []), *_text_list(values.pop(key, None))]
            )
        source_groups = values.pop("source_groups", None)
        if isinstance(source_groups, list):
            groups = current.setdefault("source_groups", [])
            for group in source_groups:
                ids = _text_list(group)
                if ids and ids not in groups:
                    groups.append(ids)
        for key, value in values.items():
            if _has_value(value) and not _has_value(current.get(key)):
                current[key] = to_json_safe(value)
        if isinstance(metadata, Mapping):
            current.setdefault("metadata", {}).update(_clean_mapping(metadata) or {})

    for payload in _declared_transform_payloads(summary):
        merge(
            _first_text(payload.get("transform_id"), payload.get("id")),
            operation=_clean_text(payload.get("operation")),
            transform_basis=_transform_basis_from_mapping(payload),
            source_ids=_text_list(payload.get("source_ids")),
            source_groups=_source_groups_from_payload(payload.get("source_groups")),
            source_table_ids=_text_list(payload.get("source_table_ids")),
            chart_ids=_text_list(payload.get("chart_ids")),
            fact_ids=_text_list(payload.get("fact_ids")),
            input_unit_families=_text_list(payload.get("input_unit_families")),
            input_unit_bases=_text_list(payload.get("input_unit_bases")),
            input_frequencies=_text_list(payload.get("input_frequencies")),
            output_unit_family=_clean_text(payload.get("output_unit_family")),
            output_unit_basis=_clean_text(payload.get("output_unit_basis")),
            output_frequency=_clean_text(payload.get("output_frequency")),
            period_key=_clean_text(payload.get("period_key")),
            resampling=_clean_text(payload.get("resampling")),
            conversion=payload.get("conversion"),
            metadata=payload.get("metadata")
            if isinstance(payload.get("metadata"), Mapping)
            else payload,
        )

    for projection in normalize_chart_projection_transforms(
        summary.get("chart_projection_transforms")
    ):
        merge(
            projection.transform_id,
            operation=projection.operation,
            source_table_ids=[
                projection.source_table_id,
                projection.render_table_id,
            ],
            chart_ids=[projection.chart_id],
            period_key=projection.axis_key,
            metadata={"chart_projection": projection.model_dump(mode="json")},
        )

    chart_by_id = {chart.chart_id: chart for chart in chart_refs}
    for chart_id, chart in charts.items():
        payload = chart if isinstance(chart, Mapping) else {}
        chart_ref = chart_by_id.get(str(chart_id))
        if chart_ref is None:
            continue
        provenance = _chart_provenance(str(chart_id), payload, summary)
        chart_source_ids = _source_ids_from_chart_provenance(provenance)
        chart_source_ids = [
            source_id
            for source_id in chart_source_ids
            if _source_key_resolves(source_id, source_ids)
        ] or chart_source_ids
        source_group = [chart_source_ids] if chart_source_ids else []
        transform_basis = _first_text(
            _transform_basis_from_mapping(payload),
            _normalization_basis(provenance.get("normalization")),
        )
        resampling = _clean_text(provenance.get("resampling"))
        period_key = _first_text(payload.get("period_key"), provenance.get("period_key"))
        for transform_id in chart_ref.transform_ids:
            merge(
                transform_id,
                operation=_operation_from_chart_transform_id(transform_id, provenance),
                transform_basis=transform_basis,
                source_ids=chart_source_ids,
                source_groups=source_group,
                source_table_ids=chart_ref.source_table_ids,
                chart_ids=[chart_ref.chart_id],
                period_key=period_key,
                resampling=resampling,
                metadata={
                    "chart_id": chart_ref.chart_id,
                    "provenance": provenance,
                },
            )

    for comparison in normalize_unit_comparisons(summary.get("unit_comparisons")):
        comparison_source_ids = [
            source_id
            for source_id in (
                _source_id_from_source_unit_record(source)
                for source in comparison.get("sources", [])
                if isinstance(source, Mapping)
            )
            if source_id is not None
        ]
        merge(
            _first_text(comparison.get("id"), comparison.get("comparison_id")),
            operation=_clean_text(comparison.get("operation")),
            transform_basis=_transform_basis_from_mapping(comparison),
            source_ids=comparison_source_ids,
            source_groups=[comparison_source_ids] if comparison_source_ids else [],
            input_unit_families=_text_list(comparison.get("unit_families")),
            input_unit_bases=_text_list(comparison.get("unit_bases")),
            conversion=comparison.get("conversion"),
            metadata={"unit_comparison": comparison},
        )

    for fact in facts:
        operation = _operation_from_fact(fact)
        if not operation and not fact.transform_basis:
            continue
        merge(
            f"fact:{fact.fact_id}",
            operation=operation,
            transform_basis=fact.transform_basis,
            source_ids=[_source_id_from_fact_source_key(fact.source_key)],
            fact_ids=[fact.fact_id],
            metadata={
                "source_key": fact.source_key,
                "metric": fact.metric,
                "unit": fact.unit,
            },
        )

    return [TransformDescriptor(**payload) for payload in by_id.values()]


def _declared_transform_payloads(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = summary.get("transforms", summary.get("transform_descriptors"))
    if isinstance(value, Mapping):
        if _looks_like_transform_descriptor(value):
            return [dict(value)]
        payloads: list[dict[str, Any]] = []
        for fallback_id, item in value.items():
            if isinstance(item, Mapping):
                payload = dict(item)
                payload.setdefault("transform_id", str(fallback_id))
                payloads.append(payload)
            elif _has_value(item):
                payloads.append(
                    {"transform_id": str(fallback_id), "operation": str(item)}
                )
        return payloads
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _looks_like_transform_descriptor(value: Mapping[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "transform_id",
            "id",
            "operation",
            "source_ids",
            "source_groups",
            "transform_basis",
        )
    )


def _source_groups_from_payload(value: Any) -> list[list[str]]:
    if not _has_value(value):
        return []
    if not isinstance(value, list):
        raise ValueError("source_groups must be a list of source ID lists")
    groups: list[list[str]] = []
    for group in value:
        if isinstance(group, str | bytes) or isinstance(group, Mapping):
            raise ValueError("source_groups must be a list of source ID lists")
        if not isinstance(group, list | tuple | set):
            raise ValueError("source_groups must be a list of source ID lists")
        ids = _text_list(group)
        if ids:
            groups.append(ids)
    return groups


def _conversion_descriptor_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = _clean_mapping(value)
    if cleaned is None:
        raise ValueError("conversion must be a non-empty mapping")

    payload: dict[str, Any] = {}
    source_conversions: dict[str, str] = {}
    descriptor_keys = {
        "source_conversions",
        "from_unit",
        "to_unit",
        "input_unit",
        "output_unit",
        "factor",
        "formula",
        "basis",
    }
    for key, child in cleaned.items():
        if key == "source_conversions":
            if not isinstance(child, Mapping):
                raise ValueError("source_conversions must be a mapping")
            source_conversions.update(
                {
                    str(source_id): str(detail)
                    for source_id, detail in child.items()
                    if _has_value(source_id) and _has_value(detail)
                }
            )
        elif key in descriptor_keys:
            payload[key] = child
        else:
            detail = _clean_text(child)
            if detail is not None:
                source_conversions[key] = detail
    if source_conversions:
        payload["source_conversions"] = source_conversions
    return payload


def _source_id_from_source_unit_record(record: Mapping[str, Any]) -> str | None:
    return _first_text(
        record.get("source_key"),
        record.get("series_id"),
        record.get("source_file"),
        record.get("title"),
    )


def _source_id_from_fact_source_key(source_key: str) -> str:
    return source_key.split(".", 1)[0] if "." in source_key else source_key


def _transform_basis_from_mapping(value: Mapping[str, Any]) -> str | None:
    return _first_text(*(value.get(key) for key in _TRANSFORM_BASIS_KEYS))


def _normalization_basis(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    parts = [
        f"{key}={child}"
        for key, child in value.items()
        if _has_value(key) and _has_value(child)
    ]
    return "; ".join(parts) or None


def _operation_from_fact(fact: EvidenceFact) -> str | None:
    if fact.operation:
        return fact.operation
    return _operation_from_text(
        fact.transform_basis,
        fact.unit,
        fact.metric,
        fact.fact_id,
        fact.label,
        fact.source_key,
    )


def _operation_from_transform_id(value: Any) -> str | None:
    return _operation_from_text(value)


def _operation_from_chart_transform_id(
    value: Any,
    provenance: Mapping[str, Any],
) -> str | None:
    if _has_value(provenance.get("normalization")) and _is_normalization_transform_id(
        value
    ):
        return "normalized_index"
    return _operation_from_transform_id(value)


def _is_normalization_transform_id(value: Any) -> bool:
    return "normalization" in set(_semantic_tokens(_semantic_text(value)))


def _operation_from_text(*values: Any) -> str | None:
    text = _semantic_text(*values)
    tokens = set(_semantic_tokens(text))
    if {"correlation", "corr"} & tokens:
        return "correlation"
    if (
        {"growth", "yoy", "qoq", "mom", "cagr"} & tokens
        or {"percent", "change"} <= tokens
        or {"percentage", "change"} <= tokens
        or ("annualized" in tokens and {"return", "rate", "change"} & tokens)
    ):
        return "growth_rate"
    if {"spread", "delta"} & tokens:
        return "spread"
    if "resampling" in tokens or "resample" in tokens:
        return "resampling"
    if "period" in tokens and {"align", "alignment", "key"} & tokens:
        return "period_alignment"
    if "conversion" in tokens or "convert" in tokens:
        return "conversion"
    if _is_normalized_index_text(text, tokens):
        return "normalized_index"
    if "projection" in tokens or "forecast" in tokens:
        return "projection"
    return None


def _transform_requires_basis(transform: TransformDescriptor) -> bool:
    if transform.operation == "long_to_wide_grouped_axis":
        return False
    return _operation_requires_basis(
        transform.operation,
        transform.transform_id,
    )


def _fact_requires_transform_basis(fact: EvidenceFact) -> bool:
    return _operation_requires_basis(fact.operation) or _operation_requires_basis(
        fact.unit,
        fact.metric,
        fact.fact_id,
        fact.label,
        fact.source_key,
    )


def _operation_requires_basis(*values: Any) -> bool:
    return _operation_from_text(*values) in {
        "correlation",
        "growth_rate",
        "normalized_index",
        "spread",
    }


def transform_operation_from_text(*values: Any) -> str | None:
    """Return the canonical operation inferred by the evidence bundle."""

    return _operation_from_text(*values)


def transform_operation_requires_basis(*values: Any) -> bool:
    """Return whether inferred transform metadata needs an explicit basis."""

    return _operation_requires_basis(*values)


def _is_normalized_index_text(text: str, tokens: set[str]) -> bool:
    return (
        ("normalized" in tokens and "index" in tokens)
        or "normalized_index" in text
        or "index_normalized" in text
        or "indexed_to" in text
        or ({"z", "score", "normalization"} <= tokens)
        or ({"zscore", "normalization"} <= tokens)
    )


def _semantic_text(*values: Any) -> str:
    return " ".join(str(value).lower() for value in values if _has_value(value))


def _semantic_tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", value.lower()) if token]


def _data_file_mapping(summary: Mapping[str, Any]) -> dict[str, str]:
    data_files = _path_mapping(summary.get("data_files"))
    manifest = summary.get("quant_input_manifest")
    if isinstance(manifest, Mapping):
        data_files.update(_path_mapping(manifest.get("data_files")))
    return data_files


def _source_snapshot_mapping(summary: Mapping[str, Any]) -> dict[str, Any]:
    source_snapshots = _snapshot_descriptor_mapping(summary.get("source_snapshots"))
    manifest = summary.get("quant_input_manifest")
    if isinstance(manifest, Mapping):
        source_snapshots.update(
            _snapshot_descriptor_mapping(manifest.get("source_snapshots"))
        )
    return source_snapshots


def _snapshot_descriptor_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key, descriptor in value.items():
        if not _has_value(key) or not isinstance(descriptor, Mapping):
            continue
        out[str(key)] = dict(descriptor)
    return out


def _source_snapshot_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, SourceSnapshotDescriptor):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, Mapping):
        return {str(key): to_json_safe(child) for key, child in value.items()}
    return {}


def _path_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, str] = {}
    for key, path in value.items():
        if _has_value(key) and _has_value(path):
            out[str(key)] = str(path)
    return out


def _clean_mapping(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    cleaned = {
        str(key): to_json_safe(child)
        for key, child in value.items()
        if _has_value(child)
    }
    return cleaned or None


def _dedupe_table_refs(refs: list[EvidenceTableRef]) -> list[EvidenceTableRef]:
    out: list[EvidenceTableRef] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        key = (ref.kind, ref.table_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def _source_ids_from_fact_keys(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    ids: list[str] = []
    for fact in value:
        if isinstance(fact, Mapping):
            source_key = _clean_text(fact.get("source_key"))
        else:
            source_key = _clean_text(getattr(fact, "source_key", None))
        if source_key is None:
            continue
        ids.append(source_key.split(".", 1)[0] if "." in source_key else source_key)
    return _unique_texts(ids)


def _text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, Mapping):
        items = [str(key) for key in value]
    elif isinstance(value, (list, tuple, set)):
        items = [str(item) for item in value if _has_value(item)]
    else:
        items = [str(value)]
    return _unique_texts(item.strip() for item in items if item.strip())


def _unique_texts(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _clean_text(value)
        if text is not None:
            return text
    return None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _require_text(value: str, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} must be a non-empty string")
    return text


def _require_unique(label: str, values: Any) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        text = str(value)
        if text in seen and text not in duplicates:
            duplicates.append(text)
        seen.add(text)
    if duplicates:
        raise ValueError(f"{label} values must be unique: {duplicates}")


def _require_table_ids_unique_across_kinds(
    raw_tables: list[EvidenceTableRef],
    normalized_tables: list[EvidenceTableRef],
) -> None:
    raw_ids = {table.table_id for table in raw_tables}
    duplicates = _unique_texts(
        table.table_id for table in normalized_tables if table.table_id in raw_ids
    )
    if duplicates:
        raise ValueError(
            "table_id values must be unique across raw_tables and "
            "normalized_tables so chart source_table_ids are unambiguous: "
            f"{duplicates}"
        )


def _require_fact_sources_resolve(
    facts: list[EvidenceFact],
    sources: list[EvidenceSource],
) -> None:
    if not facts:
        return
    source_ids = {source.source_id for source in sources}
    unresolved = [
        fact.source_key
        for fact in facts
        if not _source_key_resolves(fact.source_key, source_ids)
    ]
    if unresolved:
        raise ValueError(
            "facts.source_key values must resolve to sources.source_id: "
            f"{_unique_texts(unresolved)}"
        )


def _require_sec_company_fact_provenance(facts: list[EvidenceFact]) -> None:
    errors: list[str] = []
    for fact in facts:
        if not fact.source_key.startswith(SEC_COMPANY_FACT_PROVENANCE_CONTRACT.source_prefix):
            continue
        schema_name = _clean_text(fact.attributes.get("source_provenance_schema"))
        schema_version = _int_or_none(fact.attributes.get("sec_provenance_schema_version"))
        label = fact.fact_id
        if schema_name != SEC_COMPANY_FACT_PROVENANCE_CONTRACT.schema_name:
            errors.append(
                f"{label}: source_provenance_schema must be "
                f"{SEC_COMPANY_FACT_PROVENANCE_CONTRACT.schema_name!r}"
            )
        if schema_version != SEC_COMPANY_FACT_PROVENANCE_CONTRACT.schema_version:
            errors.append(
                f"{label}: sec_provenance_schema_version must be "
                f"{SEC_COMPANY_FACT_PROVENANCE_CONTRACT.schema_version}"
            )

        metric = _sec_company_fact_metric(fact)
        expected_components = SEC_COMPANY_FACT_PROVENANCE_CONTRACT.components_for_metric(metric)
        if not expected_components:
            errors.append(f"{label}: SEC fact metric is required for provenance validation")
            continue

        components = fact.attributes.get("sec_metric_components")
        provenance = fact.attributes.get("sec_fact_provenance")
        if not isinstance(components, list) or not components:
            errors.append(f"{label}: sec_metric_components must be a non-empty list")
            component_keys: list[str] = []
        else:
            component_keys = [
                str(component).strip()
                for component in components
                if _has_value(component) and str(component).strip()
            ]
            if sorted(component_keys) != sorted(expected_components):
                errors.append(
                    f"{label}: sec_metric_components must be "
                    f"{list(expected_components)!r}"
                )
        if not isinstance(provenance, Mapping) or not provenance:
            errors.append(f"{label}: sec_fact_provenance must be a non-empty mapping")
            continue

        for component_key in expected_components:
            item = provenance.get(component_key)
            if not isinstance(item, Mapping):
                errors.append(f"{label}: missing SEC provenance for {component_key}")
                continue
            missing = [
                field
                for field in SEC_COMPANY_FACT_PROVENANCE_CONTRACT.required_fields
                if not _has_value(item.get(field))
            ]
            if missing:
                errors.append(
                    f"{label}: SEC provenance for {component_key} is missing "
                    + ", ".join(missing)
                )

    if errors:
        raise ValueError("SEC helper facts with provenance schemas are invalid: " + "; ".join(errors))


def _require_market_valuation_unavailable_contract(
    sources: list[EvidenceSource],
) -> None:
    errors: list[str] = []
    for source in sources:
        if source.source_id != MARKET_VALUATION_SOURCE_ID:
            continue
        status = str(source.status or source.coverage.get("status") or "").strip().lower()
        if status not in {"not_available", "disabled"}:
            continue
        reason = _first_text(
            source.coverage.get("limitation"),
            source.coverage.get("reason"),
            source.metadata.get("limitation"),
            source.metadata.get("reason"),
        )
        capabilities = source.coverage.get("capabilities") or source.coverage.get(
            "capability_list"
        )
        if not reason:
            errors.append(
                "valuation_market_data status=not_available requires limitation or reason"
            )
        if not isinstance(capabilities, list) or not capabilities:
            errors.append(
                "valuation_market_data status=not_available requires a non-empty capability list"
            )
    if errors:
        raise ValueError(
            "market valuation source coverage is invalid: "
            + "; ".join(_unique_texts(errors))
        )


def _sec_company_fact_metric(fact: EvidenceFact) -> str | None:
    metric = _clean_text(fact.metric)
    if metric:
        return metric
    prefix = SEC_COMPANY_FACT_PROVENANCE_CONTRACT.source_prefix
    if fact.source_key.startswith(prefix):
        suffix = fact.source_key[len(prefix) :]
        if "." in suffix:
            return _clean_text(suffix.rsplit(".", 1)[-1])
    return _clean_text(fact.fact_id.rsplit(".", 1)[-1])


def _require_table_sources_resolve(
    tables: list[EvidenceTableRef],
    sources: list[EvidenceSource],
) -> None:
    source_ids = {source.source_id for source in sources}
    unresolved = [
        f"{table.kind}.{table.table_id}:{table.source_id}"
        for table in tables
        if table.source_id and not _source_key_resolves(table.source_id, source_ids)
    ]
    if unresolved:
        raise ValueError(
            "tables.source_id values must resolve to sources.source_id: "
            f"{_unique_texts(unresolved)}"
        )


def _require_chart_traceability(
    charts: list[EvidenceChart],
    tables: list[EvidenceTableRef],
) -> None:
    missing: list[str] = []
    unresolved: dict[str, list[str]] = {}
    table_ids = {table.table_id for table in tables}
    for chart in charts:
        if not chart.source_table_ids:
            missing.append(f"{chart.chart_id}.source_table_ids")
        if not chart.transform_ids:
            missing.append(f"{chart.chart_id}.transform_ids")
        unresolved_ids = [
            source_table_id
            for source_table_id in chart.source_table_ids
            if source_table_id not in table_ids
        ]
        if unresolved_ids:
            unresolved[chart.chart_id] = unresolved_ids
    if missing:
        raise ValueError(
            "charts must cite source_table_ids and transform_ids: "
            f"{_unique_texts(missing)}"
        )
    if unresolved:
        raise ValueError(
            "charts.source_table_ids must resolve to raw_tables.table_id or "
            f"normalized_tables.table_id: {unresolved}"
        )


def _require_chart_transforms_resolve(
    charts: list[EvidenceChart],
    transforms: list[TransformDescriptor],
) -> None:
    transform_ids = {transform.transform_id for transform in transforms}
    unresolved: dict[str, list[str]] = {}
    for chart in charts:
        missing = [
            transform_id
            for transform_id in chart.transform_ids
            if transform_id not in transform_ids
        ]
        if missing:
            unresolved[chart.chart_id] = missing
    if unresolved:
        raise ValueError(
            "charts.transform_ids must resolve to transforms.transform_id: "
            f"{unresolved}"
        )


def _require_transform_references_resolve(
    transforms: list[TransformDescriptor],
    sources: list[SourceDescriptor],
    tables: list[EvidenceTableRef],
) -> None:
    source_ids = {source.source_id for source in sources}
    table_ids = {table.table_id for table in tables}
    unresolved_sources: list[str] = []
    unresolved_tables: list[str] = []
    for transform in transforms:
        for source_id in [
            *transform.source_ids,
            *[source_id for group in transform.source_groups for source_id in group],
        ]:
            if source_id and not _source_key_resolves(source_id, source_ids):
                unresolved_sources.append(f"{transform.transform_id}:{source_id}")
        for table_id in transform.source_table_ids:
            if table_id not in table_ids:
                unresolved_tables.append(f"{transform.transform_id}:{table_id}")
    if unresolved_sources:
        raise ValueError(
            "transforms.source_ids must resolve to sources.source_id: "
            f"{_unique_texts(unresolved_sources)}"
        )
    if unresolved_tables:
        raise ValueError(
            "transforms.source_table_ids must resolve to raw_tables.table_id or "
            "normalized_tables.table_id: "
            f"{_unique_texts(unresolved_tables)}"
        )


def _require_transform_source_semantics(
    transforms: list[TransformDescriptor],
    sources: list[SourceDescriptor],
) -> None:
    source_by_id = {source.source_id: source for source in sources}
    for transform in transforms:
        groups = _semantic_source_groups(transform)
        for group in groups:
            group_sources = [
                source
                for source_id in group
                if (source := _resolve_source_descriptor(source_id, source_by_id))
                is not None
            ]
            families = _descriptor_tokens(
                [
                    *(source.unit_family for source in group_sources),
                    *transform.input_unit_families,
                ]
            )
            bases = _descriptor_tokens(
                [
                    *(source.unit_basis for source in group_sources),
                    *transform.input_unit_bases,
                ]
            )
            frequencies = _descriptor_tokens(
                [
                    *(source.frequency for source in group_sources),
                    *transform.input_frequencies,
                ]
            )
            transform_bases = _descriptor_tokens(
                source.transform_basis for source in group_sources
            )
            if len(families) > 1 and not _has_unit_alignment(transform):
                raise ValueError(
                    "transforms.source_ids have incompatible unit families "
                    f"without conversion: {transform.transform_id}={families}"
                )
            if len(bases) > 1 and not _has_unit_alignment(transform):
                raise ValueError(
                    "transforms.source_ids have incompatible unit bases without "
                    f"conversion: {transform.transform_id}={bases}"
                )
            if len(frequencies) > 1 and not _has_frequency_alignment(transform):
                raise ValueError(
                    "transforms.source_ids have incompatible frequencies without "
                    f"resampling or period_key: {transform.transform_id}={frequencies}"
                )
            if len(transform_bases) > 1 and not _has_transform_basis_alignment(
                transform,
                transform_bases,
            ):
                raise ValueError(
                    "transforms.source_ids have incompatible transform bases "
                    "without an explicit mixed-basis label: "
                    f"{transform.transform_id}={transform_bases}"
                )


def _semantic_source_groups(transform: TransformDescriptor) -> list[list[str]]:
    groups = [group for group in transform.source_groups if group]
    if groups:
        return groups
    if len(transform.source_ids) > 1:
        return [transform.source_ids]
    if transform.input_unit_families or transform.input_unit_bases or transform.input_frequencies:
        return groups or [[]]
    return groups


def _require_fact_transform_basis(facts: list[EvidenceFact]) -> None:
    missing = [
        fact.fact_id
        for fact in facts
        if _fact_requires_transform_basis(fact) and not fact.transform_basis
    ]
    if missing:
        raise ValueError(
            "facts.transform_basis is required for correlation, growth-rate, "
            "spread, or normalized-index facts: "
            f"{_unique_texts(missing)}"
        )


def _resolve_source_descriptor(
    source_id: str,
    sources: Mapping[str, SourceDescriptor],
) -> SourceDescriptor | None:
    if source_id in sources:
        return sources[source_id]
    for candidate_id, source in sources.items():
        if source_id.startswith(f"{candidate_id}."):
            return source
    return None


def _descriptor_tokens(values: Any) -> list[str]:
    return _unique_texts(
        _semantic_text(value).replace(" ", "_")
        for value in values
        if _has_value(value)
    )


def _has_transform_basis_alignment(
    transform: TransformDescriptor,
    source_bases: list[str],
) -> bool:
    transform_tokens = set(_semantic_tokens(_semantic_text(transform.transform_basis)))
    if not transform_tokens:
        return False
    return all(
        set(_semantic_tokens(source_basis)) <= transform_tokens
        for source_basis in source_bases
    )


def _transform_source_keys(transform: TransformDescriptor) -> set[str]:
    return {
        source_id
        for source_id in [
            *transform.source_ids,
            *[source_id for group in transform.source_groups for source_id in group],
        ]
        if source_id
    }


def _has_conversion_details(transform: TransformDescriptor) -> bool:
    conversion = transform.conversion
    if not conversion:
        return False
    source_keys = _transform_source_keys(transform)
    if source_keys and any(
        _source_key_resolves(conversion_source_id, source_keys)
        for conversion_source_id in conversion.source_conversions
    ):
        return True
    return _has_explicit_unit_conversion_details(conversion)


def _has_explicit_unit_conversion_details(conversion: ConversionDescriptor) -> bool:
    from_unit = _first_text(conversion.from_unit, conversion.input_unit)
    to_unit = _first_text(conversion.to_unit, conversion.output_unit)
    has_rule = (
        conversion.factor is not None
        or _has_value(conversion.formula)
        or _has_value(conversion.basis)
    )
    return bool(from_unit and to_unit and has_rule)


def _has_unit_alignment(transform: TransformDescriptor) -> bool:
    if _has_conversion_details(transform):
        return True
    return transform.operation == "normalized_index" and bool(transform.transform_basis)


def _has_frequency_alignment(transform: TransformDescriptor) -> bool:
    return bool(transform.resampling or transform.period_key)


def _source_key_resolves(source_key: str, source_ids: set[str]) -> bool:
    return any(
        source_key == source_id or source_key.startswith(f"{source_id}.")
        for source_id in source_ids
    )


__all__ = [
    "ArtifactFingerprint",
    "ConversionDescriptor",
    "EvidenceArtifacts",
    "EvidenceBundle",
    "EvidenceChart",
    "EvidenceDiagnostic",
    "EvidenceFact",
    "EvidenceSource",
    "EvidenceTableRef",
    "EvidenceValidation",
    "SourceDescriptor",
    "TransformDescriptor",
    "build_evidence_bundle",
]
