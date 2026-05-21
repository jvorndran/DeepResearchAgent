"""Latest chart-endpoint facts for quant artifact handoffs."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from .._utils import finite_number as _finite
from .numeric_fact_contracts import numeric_fact, normalize_numeric_facts


_DATE_KEYS = (
    "date",
    "period",
    "month",
    "quarter",
    "year",
    "timestamp",
    "time",
    "fiscal_year",
)
_TEMPORAL_AXIS_KEYS = set(_DATE_KEYS)
_SERIES_CONTAINER_KEYS = ("series", "lines", "bars", "areas")
_PERCENT_TOKENS = {
    "apr",
    "breakeven",
    "cpi",
    "inflation",
    "margin",
    "pct",
    "percent",
    "percentage",
    "rate",
    "spread",
    "unemployment",
    "yield",
    "yoy",
}
_PERCENTAGE_POINT_TOKENS = {"pp", "ppt", "percentage_point", "percentage_points"}


def attach_chart_latest_numeric_facts(
    summary: dict[str, Any],
    charts: Mapping[str, Any],
) -> None:
    """Merge latest chart endpoint facts into ``summary.numeric_facts``.

    Authored facts are preserved. Generated facts are placed first so writer and
    QA handoffs see current chart readings before longer helper fact lists.
    """

    generated = chart_latest_numeric_facts(charts)
    if not generated:
        return

    existing = normalize_numeric_facts(summary.get("numeric_facts"), strict=True)
    existing_chart_keys = {
        _chart_fact_key(fact)
        for fact in existing
        if _chart_fact_key(fact) is not None
    }
    existing_ids = {str(fact.get("id") or "") for fact in existing}

    merged_generated = [
        fact
        for fact in generated
        if _chart_fact_key(fact) not in existing_chart_keys
        and str(fact.get("id") or "") not in existing_ids
    ]
    if not merged_generated:
        summary["numeric_facts"] = existing
        return

    summary["numeric_facts"] = normalize_numeric_facts(
        [*merged_generated, *existing],
        strict=True,
    )


def chart_latest_numeric_facts(charts: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return canonical numeric facts for latest finite declared chart series."""

    facts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for chart_id, chart in charts.items():
        if not isinstance(chart, Mapping):
            continue
        chart_key = str(chart.get("id") or chart_id)
        if _has_sec_company_source(chart):
            continue
        rows = chart.get("data")
        if not isinstance(rows, list) or not rows:
            continue
        axis_key = _axis_key(chart)
        if axis_key and not _is_temporal_axis_key(axis_key):
            continue
        for series_index, series in _series_items(chart):
            data_key = _series_data_key(series)
            if not data_key or data_key == axis_key:
                continue
            key = (chart_key, data_key)
            if key in seen:
                continue
            seen.add(key)
            latest = _latest_finite_row(rows, data_key)
            if latest is None:
                continue
            row_index, row, value = latest
            as_of_date = _row_date(row, axis_key=axis_key)
            if as_of_date is None:
                continue
            label = _series_label(series, data_key)
            unit = _unit_for_series(
                data_key=data_key,
                label=label,
                chart_title=chart.get("title"),
            )
            precision = _precision_for_value(value, unit=unit)
            fact = numeric_fact(
                fact_id=f"chart_latest.{_slug(chart_key)}.{_slug(data_key)}",
                label=f"Latest {label} from {chart.get('title') or chart_key}",
                raw_value=value,
                unit=unit,
                precision=precision,
                tolerance=_tolerance_for_precision(precision),
                source_key=_source_key(
                    chart,
                    chart_id=chart_key,
                    data_key=data_key,
                    label=label,
                    series_index=series_index,
                ),
                as_of_date=as_of_date,
                metric=data_key,
                operation="latest finite chart endpoint",
                transform_basis=(
                    "latest finite row in charts.json for the declared chart "
                    "series; upstream chart provenance defines the source and "
                    "series transformation basis"
                ),
            )
            if fact is None:
                continue
            fact["fact_origin"] = "chart_latest_point"
            fact["chart_id"] = chart_key
            fact["data_key"] = data_key
            fact["series_label"] = label
            fact["row_index"] = row_index
            if chart.get("title") is not None:
                fact["chart_title"] = str(chart.get("title"))
            if axis_key:
                fact["x_axis_key"] = axis_key
            facts.append(fact)
    return facts


def _chart_fact_key(fact: dict[str, Any]) -> tuple[str, str] | None:
    chart_id = _clean_text(fact.get("chart_id"))
    data_key = _clean_text(fact.get("data_key"))
    if not chart_id or not data_key:
        return None
    return chart_id, data_key


def _series_items(chart: Mapping[str, Any]) -> Iterable[tuple[int, Mapping[str, Any]]]:
    index = 0
    for key in _SERIES_CONTAINER_KEYS:
        values = chart.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, Mapping):
                yield index, item
                index += 1


def _series_data_key(series: Mapping[str, Any]) -> str | None:
    for key in ("dataKey", "data_key", "key", "field", "valueKey", "value_key"):
        value = _clean_text(series.get(key))
        if value:
            return value
    return None


def _series_label(series: Mapping[str, Any], data_key: str) -> str:
    for key in ("label", "name", "title"):
        value = _clean_text(series.get(key))
        if value:
            return value
    return data_key.replace("_", " ").replace("-", " ").title()


def _axis_key(chart: Mapping[str, Any]) -> str | None:
    for key in ("xAxisKey", "x_axis_key", "axisKey", "categoryKey"):
        value = _clean_text(chart.get(key))
        if value:
            return value
    axis = chart.get("xAxis")
    if isinstance(axis, Mapping):
        for key in ("dataKey", "data_key", "key"):
            value = _clean_text(axis.get(key))
            if value:
                return value
    return None


def _latest_finite_row(
    rows: list[Any],
    data_key: str,
) -> tuple[int, Mapping[str, Any], float] | None:
    for index in range(len(rows) - 1, -1, -1):
        row = rows[index]
        if not isinstance(row, Mapping):
            continue
        value = _finite(row.get(data_key))
        if value is not None:
            return index, row, float(value)
    return None


def _row_date(row: Mapping[str, Any], *, axis_key: str | None) -> str | None:
    keys = (axis_key, *_DATE_KEYS) if _is_temporal_axis_key(axis_key) else _DATE_KEYS
    seen: set[str] = set()
    for key in keys:
        if not key or key in seen:
            continue
        seen.add(key)
        value = row.get(key)
        if value is not None and _looks_temporal_value(value):
            return str(value).strip()
    return None


def _is_temporal_axis_key(axis_key: str | None) -> bool:
    if axis_key is None:
        return False
    return axis_key.strip().lower() in _TEMPORAL_AXIS_KEYS


def _looks_temporal_value(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return float(value).is_integer() and 1900 <= int(value) <= 2200
    text = str(value or "").strip()
    if not text:
        return False
    lower = text.lower()
    if re.search(
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b",
        lower,
    ):
        return bool(re.search(r"\b(?:19|20|21)\d{2}\b", lower))
    return bool(
        re.search(
            r"\b(?:19|20|21)\d{2}(?:[-/](?:0?[1-9]|1[0-2])(?:[-/]\d{1,2})?)?\b",
            lower,
        )
        or re.search(r"\b(?:19|20|21)\d{2}\s*[- ]?q[1-4]\b", lower)
        or re.search(r"\bq[1-4]\s*[- ]?(?:19|20|21)\d{2}\b", lower)
    )


def _unit_for_series(
    *,
    data_key: str,
    label: str,
    chart_title: Any,
) -> str:
    text = f"{data_key} {label} {chart_title or ''}".lower()
    tokens = set(re.split(r"[^a-z0-9_]+", text))
    if "$" in text or " usd" in f" {text} ":
        return "usd"
    if _PERCENTAGE_POINT_TOKENS & tokens or re.search(r"\((?:pp|ppt)\)", text):
        return "percentage_point"
    if "%" in text or _PERCENT_TOKENS & tokens:
        return "percent"
    return "index"


def _precision_for_value(value: float, *, unit: str) -> int:
    if unit in {"percent", "percentage_point"}:
        return 2
    if abs(value) >= 1000 and float(value).is_integer():
        return 0
    return 2


def _tolerance_for_precision(precision: int) -> float:
    if precision <= 0:
        return 0.5
    return 0.5 * (10 ** -precision)


def _source_key(
    chart: Mapping[str, Any],
    *,
    chart_id: str,
    data_key: str,
    label: str,
    series_index: int,
) -> str:
    source_id = _source_id_for_series(
        chart,
        data_key=data_key,
        label=label,
        series_index=series_index,
    )
    if source_id:
        return f"{source_id}.{chart_id}.{data_key}"
    return f"chart_latest.{chart_id}.{data_key}"


def _source_id_for_series(
    chart: Mapping[str, Any],
    *,
    data_key: str,
    label: str,
    series_index: int,
) -> str | None:
    source_series = _source_series(chart)
    if isinstance(source_series, Mapping):
        for key in (data_key, label):
            value = _clean_text(source_series.get(key))
            if value:
                return value
        for key, value in source_series.items():
            if _tokens_match((data_key, label), (key, value)):
                text = _clean_text(value)
                if text:
                    return text
        return None
    if isinstance(source_series, list):
        text_items = [_clean_text(item) for item in source_series]
        sources = [item for item in text_items if item]
        if not sources:
            return None
        for source in sources:
            if _tokens_match((data_key, label), (source,)):
                return source
        if len(sources) > series_index:
            return sources[series_index]
        if len(sources) == 1:
            return sources[0]
    return None


def _has_sec_company_source(chart: Mapping[str, Any]) -> bool:
    source_series = _source_series(chart)
    values: list[Any] = []
    if isinstance(source_series, Mapping):
        values.extend(source_series.keys())
        values.extend(source_series.values())
    elif isinstance(source_series, list):
        values.extend(source_series)
    return any(str(value).strip().lower() == "sec_company_facts" for value in values)


def _source_series(chart: Mapping[str, Any]) -> Any:
    provenance = chart.get("provenance")
    if not isinstance(provenance, Mapping):
        return None
    source_series = provenance.get("source_series")
    if isinstance(source_series, str):
        return [part.strip() for part in source_series.split(",") if part.strip()]
    if isinstance(source_series, (list, tuple)):
        return list(source_series)
    if isinstance(source_series, Mapping):
        return source_series
    return None


def _tokens_match(left_values: Iterable[Any], right_values: Iterable[Any]) -> bool:
    left_tokens = _tokens(*left_values)
    right_tokens = _tokens(*right_values)
    return bool(left_tokens and right_tokens and left_tokens & right_tokens)


def _tokens(*values: Any) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        text = str(value or "").lower()
        tokens.update(token for token in re.split(r"[^a-z0-9]+", text) if token)
    return tokens


def _slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return slug or "value"


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
