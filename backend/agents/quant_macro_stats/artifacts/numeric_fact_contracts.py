"""Reusable evidence helpers for quant execution summaries."""

from __future__ import annotations

from typing import Any

from .._utils import finite_number as _finite
from .._utils import rounded_number as _round


def round_for_display(value: float, precision: int) -> float:
    return float(round(value, precision))


def display_value(value: Any, *, unit: str, precision: int) -> str | None:
    number = _finite(value)
    if number is None:
        return None
    rounded = round_for_display(number, precision)
    decimals = max(precision, 0)
    if unit in {"usd", "usd_per_person"}:
        return f"${rounded:,.{decimals}f}"
    if unit == "usd_b":
        return f"${rounded:,.{decimals}f}B"
    if unit == "percent":
        return f"{rounded:,.{decimals}f}%"
    if unit == "percentage_point":
        return f"{rounded:,.{decimals}f} pp"
    if unit == "multiple":
        return f"{rounded:,.{decimals}f}x"
    return f"{rounded:,.{decimals}f}"


def numeric_fact(
    *,
    fact_id: str,
    label: str,
    raw_value: Any,
    unit: str,
    precision: int,
    tolerance: float,
    source_key: str,
    as_of_date: Any = None,
    subject: str | None = None,
    metric: str | None = None,
) -> dict[str, Any] | None:
    number = _finite(raw_value)
    display = display_value(number, unit=unit, precision=precision)
    if number is None or display is None:
        return None
    fact: dict[str, Any] = {
        "id": fact_id,
        "label": label,
        "raw_value": _round(number, max(precision, 3) if precision >= 0 else 3),
        "display_value": display,
        "unit": unit,
        "precision": precision,
        "tolerance": tolerance,
        "source_key": source_key,
    }
    if as_of_date is not None:
        fact["as_of_date"] = str(as_of_date)
    if subject:
        fact["subject"] = subject
    if metric:
        fact["metric"] = metric
    return fact
