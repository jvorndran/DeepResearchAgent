"""Typed evidence-bundle sidecar for quant artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .chart_provenance import normalize_chart_provenance
from .json_safety import to_json_safe
from .numeric_fact_contracts import normalize_numeric_facts
from .source_unit_fidelity import normalize_source_unit_metadata


_CHART_DATA_TABLE_PREFIX = "chart_data:"


class _EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceSource(_EvidenceModel):
    source_id: str
    provider: str | None = None
    series_id: str | None = None
    title: str | None = None
    units: str | None = None
    frequency: str | None = None
    source_file: str | None = None
    status: str | None = None
    coverage: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_id")
    @classmethod
    def _source_id_required(cls, value: str) -> str:
        return _require_text(value, "source_id")


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

    @field_validator("charts_json", "execution_summary_json", "evidence_bundle_json")
    @classmethod
    def _artifact_path_required(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)


class EvidenceBundle(_EvidenceModel):
    schema_version: Literal[1] = 1
    bundle_type: Literal["quant_evidence_bundle"] = "quant_evidence_bundle"
    sources: list[EvidenceSource] = Field(default_factory=list)
    raw_tables: list[EvidenceTableRef] = Field(default_factory=list)
    normalized_tables: list[EvidenceTableRef] = Field(default_factory=list)
    facts: list[EvidenceFact] = Field(default_factory=list)
    charts: list[EvidenceChart] = Field(default_factory=list)
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

    return EvidenceBundle(
        sources=_source_descriptors(
            summary,
            facts=facts,
            charts=chart_map,
            table_refs=[*raw_tables, *normalized_tables],
        ),
        raw_tables=raw_tables,
        normalized_tables=normalized_tables,
        facts=facts,
        charts=[
            _chart_from_payload(chart_id, chart, summary, table_ids=table_ids)
            for chart_id, chart in chart_map.items()
        ],
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

    data = payload.get("data")
    return EvidenceChart(
        chart_id=chart_id,
        chart_type=_clean_text(payload.get("type")),
        title=_clean_text(payload.get("title")),
        description=_clean_text(payload.get("description")),
        x_axis_key=_chart_axis_key(payload),
        series_keys=_chart_series_keys(payload),
        source_series=_source_series_from_provenance(provenance),
        source_table_ids=_source_table_ids_for_chart(
            chart_id,
            payload,
            provenance,
            table_ids=table_ids,
        ),
        transform_ids=_chart_transform_ids(payload, provenance, summary),
        data_row_count=len(data) if isinstance(data, list) else None,
        provenance=provenance,
    )


def _source_descriptors(
    summary: Mapping[str, Any],
    *,
    facts: list[EvidenceFact],
    charts: Mapping[str, Any] | None = None,
    table_refs: list[EvidenceTableRef] | None = None,
) -> list[EvidenceSource]:
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
                    provider=_clean_text(value.get("provider")) or provider,
                    status=_clean_text(value.get("status")),
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
            series_id=_clean_text(record.get("series_id")),
            title=_clean_text(record.get("title")),
            units=_clean_text(record.get("units")),
            frequency=_clean_text(record.get("frequency")),
            source_file=_clean_text(record.get("source_file")),
            provider=_clean_text(record.get("source")),
            metadata=record,
        )

    for source_id, source_file in {
        **_path_mapping(summary.get("source_files")),
        **_data_file_mapping(summary),
    }.items():
        merge(source_id, source_file=source_file)

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

    return [EvidenceSource(**payload) for payload in by_id.values()]


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
    for chart_id, chart in charts.items():
        payload = chart if isinstance(chart, Mapping) else {}
        provenance = _chart_provenance(chart_id, payload, summary)
        source_ids = _source_ids_from_chart_provenance(provenance)
        data = payload.get("data")
        if not source_ids or not isinstance(data, list) or not data:
            continue
        refs.append(
            EvidenceTableRef(
                table_id=_chart_data_table_id(chart_id),
                kind="normalized",
                source_id=source_ids[0] if len(source_ids) == 1 else None,
                role="chart_data",
                row_count=len(data),
                columns=_chart_data_columns(payload),
                metadata={
                    "chart_id": chart_id,
                    "source_ids": source_ids,
                },
            )
        )
    return refs


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
    candidate_ids.extend(_text_list(payload.get("source_table_id")))
    candidate_ids.extend(_text_list(payload.get("source_table_ids")))

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
    return f"{_CHART_DATA_TABLE_PREFIX}{chart_id}"


def _chart_transform_ids(
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
    return _unique_texts(transforms)


def _data_file_mapping(summary: Mapping[str, Any]) -> dict[str, str]:
    data_files = _path_mapping(summary.get("data_files"))
    manifest = summary.get("quant_input_manifest")
    if isinstance(manifest, Mapping):
        data_files.update(_path_mapping(manifest.get("data_files")))
    return data_files


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


def _source_key_resolves(source_key: str, source_ids: set[str]) -> bool:
    return any(
        source_key == source_id or source_key.startswith(f"{source_id}.")
        for source_id in source_ids
    )


__all__ = [
    "EvidenceArtifacts",
    "EvidenceBundle",
    "EvidenceChart",
    "EvidenceDiagnostic",
    "EvidenceFact",
    "EvidenceSource",
    "EvidenceTableRef",
    "EvidenceValidation",
    "build_evidence_bundle",
]
