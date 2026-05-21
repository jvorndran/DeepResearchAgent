"""Reusable transform metadata helpers for quant execution summaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .evidence_bundle import TransformDescriptor
from .json_safety import to_json_safe


def transform_descriptor(
    transform_id: str,
    *,
    operation: str | None = None,
    transform_basis: str | None = None,
    source_ids: Sequence[Any] | None = None,
    source_groups: Sequence[Sequence[Any]] | None = None,
    source_table_ids: Sequence[Any] | None = None,
    chart_ids: Sequence[Any] | None = None,
    fact_ids: Sequence[Any] | None = None,
    input_unit_families: Sequence[Any] | None = None,
    input_unit_bases: Sequence[Any] | None = None,
    input_frequencies: Sequence[Any] | None = None,
    output_unit_family: str | None = None,
    output_unit_basis: str | None = None,
    output_frequency: str | None = None,
    period_key: str | None = None,
    resampling: str | None = None,
    conversion: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a JSON-safe validated evidence-bundle transform descriptor."""

    payload: dict[str, Any] = {"transform_id": transform_id}
    optional_values: dict[str, Any] = {
        "operation": operation,
        "transform_basis": transform_basis,
        "source_ids": _list_or_none(source_ids),
        "source_groups": _nested_list_or_none(source_groups),
        "source_table_ids": _list_or_none(source_table_ids),
        "chart_ids": _list_or_none(chart_ids),
        "fact_ids": _list_or_none(fact_ids),
        "input_unit_families": _list_or_none(input_unit_families),
        "input_unit_bases": _list_or_none(input_unit_bases),
        "input_frequencies": _list_or_none(input_frequencies),
        "output_unit_family": output_unit_family,
        "output_unit_basis": output_unit_basis,
        "output_frequency": output_frequency,
        "period_key": period_key,
        "resampling": resampling,
        "conversion": dict(conversion) if conversion is not None else None,
        "metadata": dict(metadata) if metadata is not None else None,
    }
    payload.update(
        {key: value for key, value in optional_values.items() if value is not None}
    )
    descriptor = TransformDescriptor(**payload)
    return to_json_safe(
        descriptor.model_dump(
            mode="json",
            exclude_defaults=True,
            exclude_none=True,
        )
    )


def _list_or_none(value: Sequence[Any] | None) -> list[Any] | None:
    if value is None:
        return None
    if isinstance(value, str | bytes):
        return [value]
    return list(value)


def _nested_list_or_none(
    value: Sequence[Sequence[Any]] | None,
) -> list[list[Any]] | None:
    if value is None:
        return None
    if isinstance(value, str | bytes):
        return [[value]]
    return [
        [group] if isinstance(group, str | bytes) else list(group)
        for group in value
    ]


__all__ = ["transform_descriptor"]
