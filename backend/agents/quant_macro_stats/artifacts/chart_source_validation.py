"""Strict source-table validation for chart data saved as quant artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .._utils import _finite_float
from .recharts_schema_normalization import (
    _canonical_chart_type,
    _canonicalize_axis_chart_schema,
    _chart_group_by_key,
    _chart_series_keys,
    _dedupe_preserving_order,
)


_AXIS_CHART_TYPES = {"line", "bar", "area", "composed"}
_VALIDATION_VERSION = 1


class _ValidationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChartSourceValidationIssue(_ValidationModel):
    chart_id: str
    table_id: str
    code: str
    message: str
    column: str | None = None
    row_index: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChartSourceTableValidation(_ValidationModel):
    status: Literal["valid"] = "valid"
    validation_version: int = _VALIDATION_VERSION
    chart_id: str
    table_id: str
    chart_type: str
    axis_key: str
    series_keys: list[str]
    row_count: int
    columns: list[str]
    group_by_key: str | None = None
    unique_axis_values: int
    unique_group_pairs: int | None = None


class ChartSourceValidationResult(_ValidationModel):
    valid: bool
    charts: dict[str, ChartSourceTableValidation] = Field(default_factory=dict)
    issues: list[ChartSourceValidationIssue] = Field(default_factory=list)

    def metadata_for_chart_ids(self, chart_ids: list[str]) -> dict[str, dict[str, Any]]:
        return {
            chart_id: self.charts[chart_id].model_dump(
                mode="json",
                exclude_none=True,
            )
            for chart_id in chart_ids
            if chart_id in self.charts
        }


def validate_chart_source_tables(
    charts: Mapping[str, Any],
) -> ChartSourceValidationResult:
    """Validate non-empty axis chart source tables."""

    validation = _validate_chart_source_tables(charts)
    if validation.issues:
        raise ValueError(_format_validation_error(validation.issues))
    return validation


def _validate_chart_source_tables(
    charts: Mapping[str, Any],
) -> ChartSourceValidationResult:
    metadata: dict[str, ChartSourceTableValidation] = {}
    issues: list[ChartSourceValidationIssue] = []

    for chart_id, chart in charts.items():
        chart_id_text = str(chart_id)
        if not isinstance(chart, Mapping):
            continue
        validation_chart = _canonical_axis_chart_schema_for_validation(chart)
        if not _is_axis_chart(validation_chart):
            continue

        table_id = _chart_data_table_id(chart_id_text)
        data = chart.get("data")
        if isinstance(data, list) and not data:
            continue
        if data is None:
            continue
        if not isinstance(data, list):
            if _has_value(data):
                issues.append(
                    _issue(
                        chart_id_text,
                        table_id,
                        "data",
                        "data_not_list",
                        "non-empty axis chart data must be a list of row objects",
                    )
                )
            continue

        metadata_for_chart, chart_issues = _validate_axis_chart_data(
            chart_id_text,
            table_id,
            validation_chart,
            data,
            group_by_key=_chart_group_by_key(dict(chart)),
        )
        issues.extend(chart_issues)
        if metadata_for_chart is not None and not chart_issues:
            metadata[chart_id_text] = metadata_for_chart

    return ChartSourceValidationResult(
        valid=not issues,
        charts=metadata if not issues else {},
        issues=issues,
    )


def _validate_axis_chart_data(
    chart_id: str,
    table_id: str,
    chart: Mapping[str, Any],
    data: list[Any],
    *,
    group_by_key: str | None,
) -> tuple[ChartSourceTableValidation | None, list[ChartSourceValidationIssue]]:
    issues: list[ChartSourceValidationIssue] = []
    x_key = _chart_axis_key(chart)
    if x_key is None:
        issues.append(
            _issue(
                chart_id,
                table_id,
                "xAxisKey",
                "missing_axis_key",
                "missing axis key for non-empty axis chart data",
            )
        )

    series_keys = _dedupe_preserving_order(_declared_series_keys(chart))
    if not series_keys:
        issues.append(
            _issue(
                chart_id,
                table_id,
                "series.dataKey",
                "missing_series_key",
                "missing plotted series dataKey for non-empty axis chart data",
            )
        )
    if issues:
        return None, issues

    if group_by_key:
        issues.extend(
            _validate_grouped_axis_rows(
                chart_id,
                table_id,
                data,
                x_key=x_key,
                group_by_key=group_by_key,
                series_keys=series_keys,
            )
        )
    else:
        issues.extend(
            _validate_wide_axis_rows(
                chart_id,
                table_id,
                data,
                x_key=x_key,
                series_keys=series_keys,
            )
        )

    if issues:
        return None, issues

    return (
        ChartSourceTableValidation(
            chart_id=chart_id,
            table_id=table_id,
            chart_type=_chart_type(chart),
            axis_key=x_key,
            series_keys=series_keys,
            group_by_key=group_by_key,
            row_count=len(data),
            columns=_chart_data_columns(data, x_key, series_keys, group_by_key),
            unique_axis_values=len(_axis_labels(data, x_key)),
            unique_group_pairs=_unique_group_pair_count(data, x_key, group_by_key)
            if group_by_key
            else None,
        ),
        [],
    )


def _validate_wide_axis_rows(
    chart_id: str,
    table_id: str,
    data: list[Any],
    *,
    x_key: str,
    series_keys: list[str],
) -> list[ChartSourceValidationIssue]:
    issues: list[ChartSourceValidationIssue] = []
    seen_axis_rows: dict[str, int] = {}

    for row_index, row in enumerate(data):
        if not isinstance(row, Mapping):
            issues.append(
                _issue(
                    chart_id,
                    table_id,
                    "data",
                    "row_not_object",
                    f"row {row_index} must be an object",
                    row_index=row_index,
                )
            )
            continue

        x_label = _required_label(row.get(x_key))
        if x_label is None:
            issues.append(
                _issue(
                    chart_id,
                    table_id,
                    x_key,
                    "missing_axis_value",
                    f"missing required axis value in row {row_index}",
                    row_index=row_index,
                )
            )
        elif x_label in seen_axis_rows:
            issues.append(
                _issue(
                    chart_id,
                    table_id,
                    x_key,
                    "duplicate_axis_value",
                    f"duplicate axis value {x_label!r} at rows "
                    f"{seen_axis_rows[x_label]} and {row_index}",
                    row_index=row_index,
                    metadata={"first_row_index": seen_axis_rows[x_label]},
                )
            )
        else:
            seen_axis_rows[x_label] = row_index

        for series_key in series_keys:
            issues.extend(
                _required_finite_value_issues(
                    chart_id,
                    table_id,
                    row,
                    series_key,
                    row_index,
                )
            )

    return issues


def _validate_grouped_axis_rows(
    chart_id: str,
    table_id: str,
    data: list[Any],
    *,
    x_key: str,
    group_by_key: str,
    series_keys: list[str],
) -> list[ChartSourceValidationIssue]:
    issues: list[ChartSourceValidationIssue] = []
    unique_series_keys = _dedupe_preserving_order(series_keys)
    if len(unique_series_keys) != 1:
        listed = ", ".join(unique_series_keys)
        return [
            _issue(
                chart_id,
                table_id,
                "series.dataKey",
                "ambiguous_grouped_series_keys",
                "groupBy axis charts must declare one shared plotted dataKey"
                f"; got {listed}",
            )
        ]

    value_key = unique_series_keys[0]
    seen_pairs: dict[tuple[str, str], int] = {}

    for row_index, row in enumerate(data):
        if not isinstance(row, Mapping):
            issues.append(
                _issue(
                    chart_id,
                    table_id,
                    "data",
                    "row_not_object",
                    f"row {row_index} must be an object",
                    row_index=row_index,
                )
            )
            continue

        x_label = _required_label(row.get(x_key))
        group_label = _required_label(row.get(group_by_key))
        if x_label is None:
            issues.append(
                _issue(
                    chart_id,
                    table_id,
                    x_key,
                    "missing_axis_value",
                    f"missing required axis value in row {row_index}",
                    row_index=row_index,
                )
            )
        if group_label is None:
            issues.append(
                _issue(
                    chart_id,
                    table_id,
                    group_by_key,
                    "missing_group_value",
                    f"missing required groupBy value in row {row_index}",
                    row_index=row_index,
                )
            )
        if x_label is not None and group_label is not None:
            pair = (x_label, group_label)
            if pair in seen_pairs:
                issues.append(
                    _issue(
                        chart_id,
                        table_id,
                        group_by_key,
                        "duplicate_group_pair",
                        f"duplicate groupBy pair {x_key}={x_label!r} "
                        f"{group_by_key}={group_label!r} at rows "
                        f"{seen_pairs[pair]} and {row_index}",
                        row_index=row_index,
                        metadata={"first_row_index": seen_pairs[pair]},
                    )
                )
            else:
                seen_pairs[pair] = row_index

        issues.extend(
            _required_finite_value_issues(
                chart_id,
                table_id,
                row,
                value_key,
                row_index,
            )
        )

    return issues


def _required_finite_value_issues(
    chart_id: str,
    table_id: str,
    row: Mapping[str, Any],
    column: str,
    row_index: int,
) -> list[ChartSourceValidationIssue]:
    if column not in row:
        return [
            _issue(
                chart_id,
                table_id,
                column,
                "missing_plotted_column",
                f"missing required plotted column in row {row_index}",
                row_index=row_index,
            )
        ]
    if _finite_float(row.get(column)) is None:
        return [
            _issue(
                chart_id,
                table_id,
                column,
                "non_finite_plotted_value",
                f"non-finite plotted value at row {row_index}",
                row_index=row_index,
            )
        ]
    return []


def _is_axis_chart(chart: Mapping[str, Any]) -> bool:
    chart_type = _chart_type(chart)
    if chart_type in _AXIS_CHART_TYPES:
        return True
    if chart_type:
        return False
    return (
        _chart_axis_key(chart) is not None
        or bool(_declared_series_keys(chart))
        or bool(_chart_series_keys(dict(chart)))
    )


def _canonical_axis_chart_schema_for_validation(
    chart: Mapping[str, Any],
) -> dict[str, Any]:
    return _canonicalize_axis_chart_schema(deepcopy(dict(chart)))


def _chart_type(chart: Mapping[str, Any]) -> str:
    return (
        _canonical_chart_type(chart.get("type"))
        or _canonical_chart_type(chart.get("chart_type"))
        or ""
    )


def _chart_axis_key(chart: Mapping[str, Any]) -> str | None:
    direct = _first_text(
        chart.get("xAxisKey"),
        chart.get("xKey"),
        chart.get("x_key"),
    )
    if direct:
        return direct

    for source_key in ("layout", "config"):
        source = chart.get(source_key)
        if not isinstance(source, Mapping):
            continue
        nested = _first_text(
            source.get("xAxisKey"),
            source.get("xKey"),
            source.get("x_key"),
            source.get("x_data_key"),
        )
        if nested:
            return nested
        x_axis = source.get("xAxis") or source.get("x_axis")
        if isinstance(x_axis, Mapping):
            nested = _first_text(x_axis.get("dataKey"), x_axis.get("key"))
            if nested:
                return nested

    x_axis = chart.get("xAxis")
    if isinstance(x_axis, Mapping):
        return _first_text(x_axis.get("dataKey"), x_axis.get("key"))
    return None


def _declared_series_keys(chart: Mapping[str, Any]) -> list[str]:
    keys: list[str] = []
    for source in (chart, chart.get("layout"), chart.get("config")):
        if not isinstance(source, Mapping):
            continue
        series = source.get("series")
        if isinstance(series, list):
            for item in series:
                if isinstance(item, Mapping):
                    key = _first_text(item.get("dataKey"), item.get("key"))
                    if key:
                        keys.append(key)
        y_axis = source.get("yAxis") or source.get("y_axis")
        if isinstance(y_axis, list):
            for item in y_axis:
                if isinstance(item, Mapping):
                    key = _first_text(item.get("dataKey"), item.get("key"))
                    if key:
                        keys.append(key)
        for field in ("y_keys", "yKeys"):
            values = source.get(field)
            if isinstance(values, list):
                keys.extend(str(value) for value in values if _has_value(value))
    return _dedupe_preserving_order(keys)


def _chart_data_columns(
    data: list[Any],
    x_key: str,
    series_keys: list[str],
    group_by_key: str | None,
) -> list[str]:
    columns: list[str] = []
    for row in data:
        if isinstance(row, Mapping):
            columns.extend(str(key) for key in row)
    columns.append(x_key)
    columns.extend(series_keys)
    if group_by_key:
        columns.append(group_by_key)
    return _dedupe_preserving_order(columns)


def _axis_labels(data: list[Any], x_key: str) -> list[str]:
    labels: list[str] = []
    for row in data:
        if isinstance(row, Mapping):
            label = _required_label(row.get(x_key))
            if label is not None:
                labels.append(label)
    return _dedupe_preserving_order(labels)


def _unique_group_pair_count(
    data: list[Any],
    x_key: str,
    group_by_key: str | None,
) -> int | None:
    if group_by_key is None:
        return None
    pairs: list[str] = []
    for row in data:
        if not isinstance(row, Mapping):
            continue
        x_label = _required_label(row.get(x_key))
        group_label = _required_label(row.get(group_by_key))
        if x_label is not None and group_label is not None:
            pairs.append(f"{x_label}\x1f{group_label}")
    return len(_dedupe_preserving_order(pairs))


def _required_label(value: Any) -> str | None:
    if value is None:
        return None
    label = str(value).strip()
    return label or None


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _chart_data_table_id(chart_id: str) -> str:
    return f"chart_data:{chart_id}"


def _issue(
    chart_id: str,
    table_id: str,
    column: str,
    code: str,
    detail: str,
    *,
    row_index: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> ChartSourceValidationIssue:
    return ChartSourceValidationIssue(
        chart_id=chart_id,
        table_id=table_id,
        column=column,
        code=code,
        message=(
            f"chart {chart_id!r} table {table_id!r} column {column!r}: {detail}"
        ),
        row_index=row_index,
        metadata=metadata or {},
    )


def _format_validation_error(issues: list[ChartSourceValidationIssue]) -> str:
    messages = "; ".join(issue.message for issue in issues)
    return f"chart_source_table_validation failed: {messages}"


__all__ = [
    "ChartSourceTableValidation",
    "ChartSourceValidationIssue",
    "ChartSourceValidationResult",
    "validate_chart_source_tables",
]
