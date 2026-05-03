"""Chart-contract normalization helpers for quant artifacts."""
from .shared import *
from .shared import (
    _adfuller,
    _as_ordered_frame,
    _clean_regression_frame,
    _direction_multiplier,
    _finite_float,
    _iso_date,
    _require_columns,
    _scipy_stats,
    _statsmodels_api,
)

def _looks_like_chart_definition(payload: dict[str, Any]) -> bool:
    return any(
        key in payload
        for key in (
            "type",
            "chart_type",
            "data",
            "series",
            "xAxisKey",
            "layout",
        )
    )

def _chart_map_from_payload(charts: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    if isinstance(charts, list):
        chart_map: dict[str, Any] = {}
        for chart in charts:
            if not isinstance(chart, dict) or not isinstance(chart.get("id"), str):
                raise ValueError("each chart list item must be an object with string id")
            chart_map[chart["id"]] = chart
        return chart_map

    if not isinstance(charts, dict):
        raise ValueError("charts must be a dict keyed by chart id or a list of chart objects")
    if _looks_like_chart_definition(charts):
        return {charts["id"]: charts}

    chart_map = deepcopy(charts)
    for chart_id, chart in chart_map.items():
        if not isinstance(chart_id, str) or not chart_id:
            raise ValueError("chart ids must be non-empty strings")
        if not isinstance(chart, dict):
            raise ValueError(f"chart {chart_id!r} must be a JSON object")
        chart.setdefault("id", chart_id)
        if chart["id"] != chart_id:
            raise ValueError(f"chart key {chart_id!r} does not match chart id {chart['id']!r}")
    return chart_map


def _chart_series_keys(chart: dict[str, Any]) -> list[str]:
    def keys_from_series(series: Any) -> list[str]:
        if not isinstance(series, list):
            return []
        keys: list[str] = []
        for item in series:
            if isinstance(item, dict):
                key = item.get("dataKey") or item.get("key")
                if isinstance(key, str) and key:
                    keys.append(key)
        return keys

    keys = keys_from_series(chart.get("series"))
    if keys:
        return keys

    layout = chart.get("layout")
    if isinstance(layout, dict):
        keys = keys_from_series(layout.get("series"))
        if keys:
            return keys
        for field in ("y_keys", "yKeys"):
            values = layout.get(field)
            if isinstance(values, list):
                keys = []
                for value in values:
                    if isinstance(value, dict):
                        key = value.get("dataKey") or value.get("key")
                        if isinstance(key, str) and key:
                            keys.append(key)
                    elif str(value):
                        keys.append(str(value))
                return keys

    config = chart.get("config")
    if isinstance(config, dict):
        keys = keys_from_series(config.get("series"))
        if keys:
            return keys
        for field in ("y_keys", "yKeys"):
            values = config.get(field)
            if isinstance(values, list):
                return [str(value) for value in values if str(value)]

    for field in ("y_keys", "yKeys"):
        values = chart.get(field)
        if isinstance(values, list):
            return [str(value) for value in values if str(value)]

    data = chart.get("data")
    if isinstance(data, list):
        first_row = next((row for row in data if isinstance(row, dict)), None)
        if isinstance(first_row, dict):
            x_key = chart.get("xAxisKey") or chart.get("xKey") or chart.get("x_key")
            if not isinstance(x_key, str) and isinstance(layout, dict):
                x_key = (
                    layout.get("xAxisKey")
                    or layout.get("xKey")
                    or layout.get("x_key")
                )
            return [
                key
                for key, value in first_row.items()
                if key != x_key
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ]
    return []


def _chart_has_finite_values(chart: dict[str, Any]) -> bool:
    data = chart.get("data")
    if not isinstance(data, list) or not data:
        return False

    chart_type = str(chart.get("type") or chart.get("chart_type") or "").lower()
    if chart_type in {"line", "bar", "area", "composed"} or _chart_series_keys(chart):
        x_key = chart.get("xAxisKey") or chart.get("xKey") or chart.get("x_key")
        if isinstance(x_key, str) and x_key:
            if any(
                not isinstance(row, dict)
                or row.get(x_key) is None
                or str(row.get(x_key)).strip() == ""
                for row in data
            ):
                return False
        keys = _chart_series_keys(chart)
        if not keys:
            return False
        return all(
            any(isinstance(row, dict) and _finite_float(row.get(key)) is not None for row in data)
            for key in keys
        )
    if chart_type == "scatter":
        keys = [chart.get("xKey"), chart.get("yKey")]
        return all(
            isinstance(key, str)
            and any(isinstance(row, dict) and _finite_float(row.get(key)) is not None for row in data)
            for key in keys
        )
    if chart_type == "pie":
        return all(
            isinstance(row, dict) and _finite_float(row.get("value")) is not None
            for row in data
        )
    return True


def _canonical_chart_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower().replace("_", "").replace("-", "")
    aliases = {
        "line": "line",
        "linechart": "line",
        "bar": "bar",
        "barchart": "bar",
        "area": "area",
        "areachart": "area",
        "composed": "composed",
        "composedchart": "composed",
        "scatter": "scatter",
        "scatterchart": "scatter",
        "pie": "pie",
        "piechart": "pie",
    }
    return aliases.get(cleaned)


def _canonicalize_axis_chart_schema(chart: dict[str, Any]) -> dict[str, Any]:
    """Translate legacy quant chart layout fields into the frontend contract."""

    chart_type = _canonical_chart_type(chart.get("type")) or _canonical_chart_type(
        chart.get("chart_type")
    )
    if chart_type and not isinstance(chart.get("type"), str):
        chart["type"] = chart_type

    layout = chart.get("layout")
    if not isinstance(layout, dict):
        return chart

    x_key = (
        chart.get("xAxisKey")
        or chart.get("xKey")
        or chart.get("x_key")
        or layout.get("xAxisKey")
        or layout.get("xKey")
        or layout.get("x_key")
        or layout.get("x_data_key")
    )
    if isinstance(x_key, str) and x_key and not isinstance(chart.get("xAxisKey"), str):
        chart["xAxisKey"] = x_key

    if isinstance(chart.get("series"), list) and chart["series"]:
        return chart

    series_items: list[dict[str, Any]] = []
    for field, default_type in (("lines", "line"), ("bars", "bar"), ("areas", "area")):
        raw_items = layout.get(field)
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            data_key = item.get("dataKey") or item.get("data_key") or item.get("key")
            if not isinstance(data_key, str) or not data_key:
                continue
            series_item = {
                "dataKey": data_key,
                "label": item.get("label") or data_key,
                "color": item.get("color") or "#2563eb",
            }
            item_type = _canonical_chart_type(item.get("type")) or default_type
            if chart_type == "composed" or item_type != chart_type:
                series_item["type"] = item_type
            if isinstance(item.get("y_axis_id"), str):
                series_item["yAxisId"] = item["y_axis_id"]
            if isinstance(item.get("stroke_dasharray"), str):
                series_item["strokeDasharray"] = item["stroke_dasharray"]
            series_items.append(series_item)

    if series_items:
        chart["series"] = series_items
    return chart


def _repair_axis_chart_x_aliases(chart: dict[str, Any]) -> dict[str, Any]:
    """Fill common x-axis aliases so render validation sees canonical keys."""

    data = chart.get("data")
    x_key = chart.get("xAxisKey") or chart.get("xKey") or chart.get("x_key")
    if not isinstance(data, list) or not isinstance(x_key, str) or not x_key:
        return chart

    aliases_by_key = {
        "date": ("period", "month", "quarter", "year"),
        "window": ("analog", "label", "period", "name", "scenario"),
        "scenario": ("name", "label", "case"),
        "period": ("date", "month", "quarter", "year", "label"),
    }
    aliases = aliases_by_key.get(x_key, ("label", "name"))
    for row in data:
        if not isinstance(row, dict):
            continue
        current = row.get(x_key)
        if current is not None and str(current).strip():
            continue
        for alias in aliases:
            value = row.get(alias)
            if value is not None and str(value).strip():
                row[x_key] = value
                break
    return chart


def _parse_chart_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed)


def _normalize_axis_chart_extent(chart: dict[str, Any]) -> dict[str, Any]:
    """Drop empty date-history tails and clamp reference bands to plotted data."""

    data = chart.get("data")
    x_key = chart.get("xAxisKey") or chart.get("xKey") or chart.get("x_key")
    if not isinstance(data, list) or not isinstance(x_key, str) or not x_key:
        return chart

    series_keys = _chart_series_keys(chart)
    if not series_keys:
        return chart

    dated_rows: list[tuple[int, pd.Timestamp]] = []
    finite_series_indexes: list[int] = []
    for index, row in enumerate(data):
        if not isinstance(row, dict):
            continue
        timestamp = _parse_chart_timestamp(row.get(x_key))
        if timestamp is not None:
            dated_rows.append((index, timestamp))
        if any(_finite_float(row.get(key)) is not None for key in series_keys):
            finite_series_indexes.append(index)

    if dated_rows and finite_series_indexes:
        first_index = min(finite_series_indexes)
        last_index = max(finite_series_indexes)
        if first_index > 0 or last_index < len(data) - 1:
            chart["data"] = data[first_index : last_index + 1]
            data = chart["data"]
            dated_rows = []
            for index, row in enumerate(data):
                if isinstance(row, dict):
                    timestamp = _parse_chart_timestamp(row.get(x_key))
                    if timestamp is not None:
                        dated_rows.append((index, timestamp))

    if not dated_rows:
        return chart

    min_date = min(timestamp for _, timestamp in dated_rows)
    max_date = max(timestamp for _, timestamp in dated_rows)
    reference_areas = chart.get("referenceAreas")
    if not isinstance(reference_areas, list):
        return chart

    filtered_areas: list[Any] = []
    for area in reference_areas:
        if not isinstance(area, dict):
            filtered_areas.append(area)
            continue
        start = _parse_chart_timestamp(area.get("x1") or area.get("start"))
        end = _parse_chart_timestamp(area.get("x2") or area.get("end") or area.get("x1"))
        if start is None or end is None:
            filtered_areas.append(area)
            continue
        if end < min_date or start > max_date:
            continue
        filtered_areas.append(area)
    chart["referenceAreas"] = filtered_areas
    return chart


def _drop_empty_chart_definitions(chart_map: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Remove charts that cannot satisfy the frontend render contract."""

    filtered: dict[str, Any] = {}
    dropped: list[str] = []
    for chart_id, chart in chart_map.items():
        if isinstance(chart, dict):
            chart = _canonicalize_axis_chart_schema(chart)
            chart = _repair_axis_chart_x_aliases(chart)
            chart = _normalize_axis_chart_extent(chart)
        if not isinstance(chart, dict) or not _chart_has_finite_values(chart):
            dropped.append(chart_id)
            continue
        filtered[chart_id] = chart
    return filtered, dropped


def _declared_since_year(key: str) -> int | None:
    marker = "_since_"
    if marker not in key:
        return None
    suffix = key.rsplit(marker, 1)[1]
    year_text = ""
    for char in suffix:
        if not char.isdigit():
            break
        year_text += char
    if len(year_text) != 4:
        return None
    return int(year_text)


def _normalize_declared_since_lists(value: Any, key: str | None = None) -> None:
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            _normalize_declared_since_lists(child_value, child_key)
        return
    if not isinstance(value, list) or not key:
        return

    since_year = _declared_since_year(key)
    if since_year is None:
        return

    cutoff = pd.Timestamp(year=since_year, month=1, day=1)
    filtered: list[Any] = []
    for item in value:
        if not isinstance(item, dict):
            filtered.append(item)
            continue
        start = _parse_chart_timestamp(item.get("x1") or item.get("start") or item.get("date"))
        end = _parse_chart_timestamp(item.get("x2") or item.get("end") or item.get("x1"))
        if start is None and end is None:
            filtered.append(item)
            continue
        if (end or start) >= cutoff:
            filtered.append(item)
    value[:] = filtered

