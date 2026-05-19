"""Typed chart projection metadata for quant chart artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


CHART_PROJECTION_VERSION = 1
CHART_SOURCE_TABLE_PREFIX = "chart_source:"
CHART_RENDER_TABLE_PREFIX = "chart_data:"


class _ChartProjectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChartProjectionTransform(_ChartProjectionModel):
    projection_version: Literal[1] = CHART_PROJECTION_VERSION
    transform_id: str
    chart_id: str
    operation: Literal["long_to_wide_grouped_axis"] = "long_to_wide_grouped_axis"
    source_table_id: str
    render_table_id: str
    axis_key: str
    group_by_key: str
    value_key: str
    group_values: list[str] = Field(min_length=1)
    source_columns: list[str] = Field(min_length=1)
    render_columns: list[str] = Field(min_length=1)
    source_row_count: int = Field(ge=1)
    render_row_count: int = Field(ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "transform_id",
        "chart_id",
        "source_table_id",
        "render_table_id",
        "axis_key",
        "group_by_key",
        "value_key",
    )
    @classmethod
    def _text_required(cls, value: str) -> str:
        cleaned = value.strip() if isinstance(value, str) else ""
        if not cleaned:
            raise ValueError("value must be a non-empty string")
        return cleaned

    @field_validator("group_values", "source_columns", "render_columns")
    @classmethod
    def _text_list_required(cls, value: list[str]) -> list[str]:
        cleaned = _dedupe_texts(value)
        if not cleaned:
            raise ValueError("value must include at least one non-empty string")
        return cleaned


def chart_source_table_id(chart_id: str) -> str:
    return f"{CHART_SOURCE_TABLE_PREFIX}{chart_id}"


def chart_render_table_id(chart_id: str) -> str:
    return f"{CHART_RENDER_TABLE_PREFIX}{chart_id}"


def chart_projection_transform_id(chart_id: str) -> str:
    return f"chart_projection:{chart_id}:long_to_wide"


def grouped_axis_projection_transform(
    *,
    chart_id: str,
    axis_key: str,
    group_by_key: str,
    value_key: str,
    group_values: list[str],
    source_columns: list[str],
    render_columns: list[str],
    source_row_count: int,
    render_row_count: int,
) -> ChartProjectionTransform:
    return ChartProjectionTransform(
        transform_id=chart_projection_transform_id(chart_id),
        chart_id=chart_id,
        source_table_id=chart_source_table_id(chart_id),
        render_table_id=chart_render_table_id(chart_id),
        axis_key=axis_key,
        group_by_key=group_by_key,
        value_key=value_key,
        group_values=group_values,
        source_columns=source_columns,
        render_columns=render_columns,
        source_row_count=source_row_count,
        render_row_count=render_row_count,
    )


def normalize_chart_projection_transforms(value: Any) -> list[ChartProjectionTransform]:
    if not _has_value(value):
        return []
    if isinstance(value, ChartProjectionTransform):
        return [value]
    if isinstance(value, Mapping):
        if _looks_like_projection_transform(value):
            return [ChartProjectionTransform(**dict(value))]
        return [
            ChartProjectionTransform(**dict(item))
            for item in value.values()
            if isinstance(item, Mapping)
        ]
    if isinstance(value, list):
        return [
            ChartProjectionTransform(**dict(item))
            for item in value
            if isinstance(item, Mapping)
        ]
    return []


def chart_projection_transforms_by_chart(
    value: Any,
) -> dict[str, ChartProjectionTransform]:
    return {
        transform.chart_id: transform
        for transform in normalize_chart_projection_transforms(value)
    }


def _looks_like_projection_transform(value: Mapping[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "transform_id",
            "chart_id",
            "source_table_id",
            "render_table_id",
            "group_by_key",
        )
    )


def _dedupe_texts(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        text = str(value).strip() if value is not None else ""
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


__all__ = [
    "ChartProjectionTransform",
    "chart_projection_transform_id",
    "chart_projection_transforms_by_chart",
    "chart_render_table_id",
    "chart_source_table_id",
    "grouped_axis_projection_transform",
    "normalize_chart_projection_transforms",
]
