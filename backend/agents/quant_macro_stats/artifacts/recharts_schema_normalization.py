"""Chart-contract normalization helpers for quant artifacts."""
from copy import deepcopy
from typing import Any

import pandas as pd

from .._utils import _finite_float

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
        y_axis = config.get("yAxis") or config.get("y_axis")
        if isinstance(y_axis, list):
            keys = [
                str(item.get("dataKey") or item.get("key"))
                for item in y_axis
                if isinstance(item, dict) and (item.get("dataKey") or item.get("key"))
            ]
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


def _chart_group_by_key(chart: dict[str, Any]) -> str | None:
    for source in (chart, chart.get("config"), chart.get("layout")):
        if not isinstance(source, dict):
            continue
        group_key = source.get("groupBy") or source.get("group_by")
        if isinstance(group_key, str) and group_key.strip():
            return group_key.strip()
    return None


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _is_positive_finite(value: Any) -> bool:
    numeric = _finite_float(value)
    return numeric is not None and numeric > 0


def _hierarchy_value_key(value: Any, preferred: Any = None) -> str:
    if preferred in {"size", "value"}:
        return str(preferred)
    stack = list(value) if isinstance(value, list) else [value]
    while stack:
        node = stack.pop(0)
        if not isinstance(node, dict):
            continue
        if node.get("size") is not None:
            return "size"
        if node.get("value") is not None:
            return "value"
        children = node.get("children")
        if isinstance(children, list):
            stack.extend(children)
    return "value"


def _hierarchy_has_positive_values(value: Any, value_key: str, *, require_children: bool = False) -> bool:
    if not isinstance(value, dict):
        return False
    children = value.get("children")
    if children is not None:
        return isinstance(children, list) and bool(children) and all(
            _hierarchy_has_positive_values(child, value_key) for child in children
        )
    if require_children:
        return False
    fallback_key = "value" if value_key == "size" else "size"
    return _is_positive_finite(value.get(value_key)) or _is_positive_finite(
        value.get(fallback_key)
    )


def _chart_has_finite_values(chart: dict[str, Any]) -> bool:
    raw_chart_type = chart.get("type") or chart.get("chart_type") or ""
    chart_type = _canonical_chart_type(raw_chart_type) or str(raw_chart_type).strip()
    data = chart.get("data")

    if chart_type in {"line", "bar", "area", "composed"} or (
        not chart_type and _chart_series_keys(chart)
    ):
        if not isinstance(data, list) or not data:
            return False
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
        if not isinstance(data, list) or not data:
            return False
        keys = [chart.get("xKey"), chart.get("yKey")]
        if not all(
            isinstance(key, str)
            and any(isinstance(row, dict) and _finite_float(row.get(key)) is not None for row in data)
            for key in keys
        ):
            return False
        size_key = chart.get("sizeKey")
        return not isinstance(size_key, str) or any(
            isinstance(row, dict) and _is_positive_finite(row.get(size_key)) for row in data
        )
    if chart_type == "radar":
        if not isinstance(data, list) or not data:
            return False
        angle_key = chart.get("angleKey")
        if isinstance(angle_key, str) and angle_key and any(
            not isinstance(row, dict)
            or row.get(angle_key) is None
            or str(row.get(angle_key)).strip() == ""
            for row in data
        ):
            return False
        keys = _chart_series_keys(chart)
        return bool(keys) and all(
            any(isinstance(row, dict) and _finite_float(row.get(key)) is not None for row in data)
            for key in keys
        )
    if chart_type in {"pie", "radialBar", "funnel"}:
        if not isinstance(data, list) or not data:
            return False
        data_key = chart.get("dataKey") if chart_type != "pie" else "value"
        if not isinstance(data_key, str) or not data_key:
            data_key = "value"
        return all(
            isinstance(row, dict) and _is_positive_finite(row.get(data_key))
            for row in data
        )
    if chart_type == "treemap":
        if not isinstance(data, list) or not data:
            return False
        value_key = _hierarchy_value_key(data, chart.get("valueKey"))
        return all(_hierarchy_has_positive_values(node, value_key) for node in data)
    if chart_type == "sunburst":
        value_key = _hierarchy_value_key(data, chart.get("valueKey"))
        return _hierarchy_has_positive_values(data, value_key, require_children=True)
    if chart_type == "sankey":
        if not isinstance(data, dict):
            return False
        nodes = data.get("nodes")
        links = data.get("links")
        return (
            isinstance(nodes, list)
            and bool(nodes)
            and isinstance(links, list)
            and bool(links)
            and all(
                isinstance(link, dict)
                and isinstance(link.get("source"), int)
                and isinstance(link.get("target"), int)
                and 0 <= link["source"] < len(nodes)
                and 0 <= link["target"] < len(nodes)
                and _is_positive_finite(link.get("value"))
                for link in links
            )
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
        "dualaxis": "composed",
        "dualaxischart": "composed",
        "dualaxislinebar": "composed",
        "scatter": "scatter",
        "scatterchart": "scatter",
        "pie": "pie",
        "piechart": "pie",
        "treemap": "treemap",
        "treemapchart": "treemap",
        "radar": "radar",
        "radarchart": "radar",
        "radialbar": "radialBar",
        "radialbarchart": "radialBar",
        "funnel": "funnel",
        "funnelchart": "funnel",
        "sankey": "sankey",
        "sankeychart": "sankey",
        "sunburst": "sunburst",
        "sunburstchart": "sunburst",
    }
    return aliases.get(cleaned)


def _canonicalize_axis_chart_schema(chart: dict[str, Any]) -> dict[str, Any]:
    """Translate legacy quant chart layout fields into the frontend contract."""

    chart_type = _canonical_chart_type(chart.get("type")) or _canonical_chart_type(
        chart.get("chart_type")
    )
    if chart_type and chart.get("type") != chart_type:
        chart["type"] = chart_type

    layout = chart.get("layout")
    config = chart.get("config")
    axis_source = layout if isinstance(layout, dict) else config if isinstance(config, dict) else {}
    if not isinstance(axis_source, dict):
        return chart
    if isinstance(layout, dict):
        layout_value = layout.get("layout") or layout.get("chartLayout") or layout.get("orientation")
        if layout_value in {"horizontal", "vertical"}:
            chart["layout"] = layout_value
        else:
            chart.pop("layout", None)

    x_key = (
        chart.get("xAxisKey")
        or chart.get("xKey")
        or chart.get("x_key")
        or axis_source.get("xAxisKey")
        or axis_source.get("xKey")
        or axis_source.get("x_key")
        or axis_source.get("x_data_key")
    )
    x_axis = axis_source.get("xAxis") or axis_source.get("x_axis")
    if not x_key and isinstance(x_axis, dict):
        x_key = x_axis.get("dataKey") or x_axis.get("key")
    if isinstance(x_key, str) and x_key and not isinstance(chart.get("xAxisKey"), str):
        chart["xAxisKey"] = x_key

    if isinstance(chart.get("series"), list) and chart["series"]:
        return chart

    series_items: list[dict[str, Any]] = []
    for field, default_type in (("lines", "line"), ("bars", "bar"), ("areas", "area")):
        raw_items = axis_source.get(field)
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

    y_axis = axis_source.get("yAxis") or axis_source.get("y_axis")
    colors = axis_source.get("colors") if isinstance(axis_source.get("colors"), list) else []
    if isinstance(y_axis, list):
        for idx, item in enumerate(y_axis):
            if not isinstance(item, dict):
                continue
            data_key = item.get("dataKey") or item.get("data_key") or item.get("key")
            if not isinstance(data_key, str) or not data_key:
                continue
            series_item = {
                "dataKey": data_key,
                "label": item.get("label") or item.get("name") or data_key,
                "color": item.get("color") or (colors[idx] if idx < len(colors) else "#2563eb"),
            }
            item_type = _canonical_chart_type(item.get("type"))
            if chart_type == "composed" and item_type:
                series_item["type"] = item_type
            y_axis_id = item.get("yAxisId") or item.get("y_axis_id") or item.get("axis")
            if isinstance(y_axis_id, str):
                series_item["yAxisId"] = y_axis_id
            elif len(y_axis) > 1:
                series_item["yAxisId"] = "left" if idx == 0 else "right"
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


def _strip_group_by_fields(chart: dict[str, Any]) -> None:
    chart.pop("groupBy", None)
    chart.pop("group_by", None)
    config = chart.get("config")
    if isinstance(config, dict):
        config.pop("groupBy", None)
        config.pop("group_by", None)
        if not config:
            chart.pop("config", None)


def _normalize_grouped_axis_chart(
    chart: dict[str, Any],
    group_by_key: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Pivot unsupported long-form groupBy axis charts into wide series."""

    if not group_by_key:
        return chart, []

    chart_type = _canonical_chart_type(chart.get("type")) or _canonical_chart_type(
        chart.get("chart_type")
    )
    if chart_type not in {"line", "bar", "area", "composed"}:
        return chart, []

    data = chart.get("data")
    x_key = chart.get("xAxisKey") or chart.get("xKey") or chart.get("x_key")
    series = chart.get("series")
    if (
        not isinstance(data, list)
        or not data
        or not isinstance(x_key, str)
        or not x_key
        or not isinstance(series, list)
        or not series
    ):
        return None, [
            f"dropped unsupported groupBy={group_by_key} chart: missing axis data, xAxisKey, or series"
        ]

    series_keys: list[str] = []
    for item in series:
        if not isinstance(item, dict):
            return None, [
                f"dropped unsupported groupBy={group_by_key} chart: "
                "every series must declare one shared value dataKey"
            ]
        key = item.get("dataKey") or item.get("key")
        if not isinstance(key, str) or not key.strip():
            return None, [
                f"dropped unsupported groupBy={group_by_key} chart: "
                "every series must declare one shared value dataKey"
            ]
        series_keys.append(key.strip())

    unique_series_keys = _dedupe_preserving_order(series_keys)
    if len(unique_series_keys) != 1:
        listed_keys = ", ".join(unique_series_keys[:4])
        if len(unique_series_keys) > 4:
            listed_keys = f"{listed_keys}, ..."
        return None, [
            f"dropped unsupported groupBy={group_by_key} chart: "
            f"multiple series dataKeys cannot be pivoted ({listed_keys})"
        ]
    value_key = unique_series_keys[0]

    rows_by_x: dict[str, dict[str, Any]] = {}
    x_value_by_label: dict[str, Any] = {}
    x_order: list[str] = []
    group_order_from_data: list[str] = []
    seen_pairs: set[tuple[str, str]] = set()
    duplicate_pairs: set[tuple[str, str]] = set()

    for row in data:
        if not isinstance(row, dict):
            return None, [
                f"dropped unsupported groupBy={group_by_key} chart: every row must be an object"
            ]
        x_value = row.get(x_key)
        group_value = row.get(group_by_key)
        x_label = str(x_value).strip() if x_value is not None else ""
        group_label = str(group_value).strip() if group_value is not None else ""
        if not x_label or not group_label:
            return None, [
                f"dropped unsupported groupBy={group_by_key} chart: rows must include {x_key} and {group_by_key}"
            ]
        numeric_value = _finite_float(row.get(value_key))
        if numeric_value is None:
            continue

        pair = (x_label, group_label)
        if pair in seen_pairs:
            duplicate_pairs.add(pair)
            continue
        seen_pairs.add(pair)
        if x_label not in rows_by_x:
            rows_by_x[x_label] = {x_key: x_value}
            x_value_by_label[x_label] = x_value
            x_order.append(x_label)
        if group_label not in group_order_from_data:
            group_order_from_data.append(group_label)
        rows_by_x[x_label][group_label] = numeric_value

    if duplicate_pairs:
        return None, [
            f"dropped unsupported groupBy={group_by_key} chart: duplicate finite values for {x_key}/{group_by_key} pairs"
        ]
    if not rows_by_x or not group_order_from_data:
        return None, [
            f"dropped unsupported groupBy={group_by_key} chart: no finite {value_key} values to pivot"
        ]

    preferred_group_order = [
        str(item.get("label") or item.get("name") or "").strip()
        for item in series
        if isinstance(item, dict)
        and str(item.get("label") or item.get("name") or "").strip()
    ]
    group_order = [
        group
        for group in _dedupe_preserving_order(
            preferred_group_order + group_order_from_data
        )
        if group in group_order_from_data
    ]
    pivoted_series: list[dict[str, Any]] = []
    for index, group_label in enumerate(group_order):
        source = (
            series[index]
            if index < len(series) and isinstance(series[index], dict)
            else {}
        )
        source_label = str(source.get("label") or source.get("name") or "").strip()
        label = source_label if source_label == group_label else group_label
        item: dict[str, Any] = {
            "dataKey": group_label,
            "label": label,
            "color": source.get("color") or "#2563eb",
        }
        for field in ("type", "yAxisId", "stackId", "shape", "strokeDasharray"):
            if source.get(field) is not None:
                item[field] = source[field]
        pivoted_series.append(item)

    chart["series"] = pivoted_series
    chart["data"] = [
        {
            **{x_key: x_value_by_label[x_label]},
            **{group: rows_by_x[x_label].get(group) for group in group_order},
        }
        for x_label in x_order
    ]
    _strip_group_by_fields(chart)
    return chart, [
        f"converted unsupported groupBy={group_by_key} long-form {value_key} chart into wide series columns"
    ]


def _collapse_duplicate_axis_rows(chart: dict[str, Any]) -> dict[str, Any]:
    data = chart.get("data")
    x_key = chart.get("xAxisKey") or chart.get("xKey") or chart.get("x_key")
    if not isinstance(data, list) or not isinstance(x_key, str) or not x_key:
        return chart

    series_keys = _chart_series_keys(chart)
    if not series_keys:
        return chart

    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        x_value = row.get(x_key)
        x_label = str(x_value).strip() if x_value is not None else ""
        if not x_label:
            return chart
        if x_label not in grouped:
            grouped[x_label] = []
            order.append(x_label)
        grouped[x_label].append(row)

    if all(len(rows) == 1 for rows in grouped.values()) or sum(
        len(rows) for rows in grouped.values()
    ) != len(data):
        return chart

    series_key_set = set(series_keys)
    collapsed: list[dict[str, Any]] = []
    for x_label in order:
        rows = grouped[x_label]
        if len(rows) == 1:
            collapsed.append(rows[0])
            continue
        merged: dict[str, Any] = {x_key: rows[0].get(x_key)}
        for row in rows:
            for key, value in row.items():
                if key == x_key or key in series_key_set or key in merged:
                    continue
                if value is not None and str(value).strip():
                    merged[key] = value
        for key in series_keys:
            numeric_values = [
                numeric
                for row in rows
                if (numeric := _finite_float(row.get(key))) is not None
            ]
            if numeric_values:
                merged[key] = sum(numeric_values) / len(numeric_values)
                continue
            for row in rows:
                value = row.get(key)
                if value is not None and str(value).strip():
                    merged[key] = value
                    break
        collapsed.append(merged)

    chart["data"] = collapsed
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


def _finite_chart_values(data: list[Any], key: str) -> list[float]:
    values: list[float] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        value = _finite_float(row.get(key))
        if value is not None:
            values.append(value)
    return values


def _collapse_same_scale_dual_axes(chart: dict[str, Any]) -> dict[str, Any]:
    """Use one axis when dual-axis series are already on similar numeric scales."""

    chart_type = _canonical_chart_type(chart.get("type")) or _canonical_chart_type(
        chart.get("chart_type")
    )
    if chart_type not in {"line", "bar", "area", "composed"}:
        return chart

    data = chart.get("data")
    series = chart.get("series")
    if not isinstance(data, list) or not isinstance(series, list):
        return chart

    axis_ids = {
        item.get("yAxisId") or item.get("y_axis_id") or item.get("axis")
        for item in series
        if isinstance(item, dict)
    }
    if not {"left", "right"}.issubset(axis_ids):
        return chart

    ranges: list[float] = []
    magnitudes: list[float] = []
    for item in series:
        if not isinstance(item, dict):
            continue
        key = item.get("dataKey") or item.get("key")
        if not isinstance(key, str) or not key:
            continue
        values = _finite_chart_values(data, key)
        if len(values) < 2:
            continue
        value_range = max(values) - min(values)
        if value_range > 0:
            ranges.append(value_range)
        magnitude = max(abs(value) for value in values)
        if magnitude > 0:
            magnitudes.append(magnitude)

    if len(ranges) < 2 or len(magnitudes) < 2:
        return chart
    min_range = min(ranges)
    max_range = max(ranges)
    min_magnitude = min(magnitudes)
    max_magnitude = max(magnitudes)
    if (
        min_range <= 0
        or min_magnitude <= 0
        or max_range / min_range >= 2
        or max_magnitude / min_magnitude >= 5
    ):
        return chart

    for item in series:
        if not isinstance(item, dict):
            continue
        if item.get("yAxisId") == "right":
            item["yAxisId"] = "left"
        if item.get("y_axis_id") == "right":
            item["y_axis_id"] = "left"
        if item.get("axis") == "right":
            item["axis"] = "left"
    return chart


def _drop_empty_chart_definitions(
    chart_map: dict[str, Any],
) -> tuple[dict[str, Any], list[str], dict[str, list[str]]]:
    """Remove charts that cannot satisfy the frontend render contract."""

    filtered: dict[str, Any] = {}
    dropped: list[str] = []
    normalization_issues: dict[str, list[str]] = {}
    for chart_id, chart in chart_map.items():
        if isinstance(chart, dict):
            group_by_key = _chart_group_by_key(chart)
            chart = _canonicalize_axis_chart_schema(chart)
            chart = _repair_axis_chart_x_aliases(chart)
            chart, grouped_issues = _normalize_grouped_axis_chart(chart, group_by_key)
            if grouped_issues:
                normalization_issues[chart_id] = grouped_issues
            if chart is None:
                dropped.append(chart_id)
                continue
            chart = _collapse_duplicate_axis_rows(chart)
            chart = _normalize_axis_chart_extent(chart)
            chart = _collapse_same_scale_dual_axes(chart)
        if not isinstance(chart, dict) or not _chart_has_finite_values(chart):
            dropped.append(chart_id)
            continue
        filtered[chart_id] = chart
    return filtered, dropped, normalization_issues


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


def normalize_quant_report_charts(
    charts: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a renderable Recharts map plus IDs dropped by schema cleanup."""

    chart_map, dropped_chart_ids, normalization_issues = _drop_empty_chart_definitions(
        _chart_map_from_payload(charts)
    )
    return {
        "charts": chart_map,
        "chart_ids": list(chart_map),
        "dropped_chart_ids": dropped_chart_ids,
        "chart_normalization_issues": normalization_issues,
    }


__all__ = ["normalize_quant_report_charts"]
