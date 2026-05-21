"""Typed scenario projection row contract shared by quant and report gates."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


SCENARIO_PROJECTION_ROWS_KEY = "scenario_projection_rows"

_UNIT_ALIASES = {
    "$": "usd",
    "$b": "usd_b",
    "$bn": "usd_b",
    "$m": "usd_m",
    "b": "usd_b",
    "billions": "usd_b",
    "billion_usd": "usd_b",
    "dollar": "usd",
    "dollars": "usd",
    "m": "usd_m",
    "millions": "usd_m",
    "million_usd": "usd_m",
    "pct": "percent",
    "percentage": "percent",
    "usd billions": "usd_b",
    "usd millions": "usd_m",
}
_CURRENCY_FACTORS = {
    "usd": 1.0,
    "usd_m": 1_000_000.0,
    "usd_b": 1_000_000_000.0,
}
_SUPPORTED_UNITS = frozenset((*_CURRENCY_FACTORS.keys(), "percent"))
_METRIC_TOLERANCE_KEYS = {
    "projected_revenue": ("projected_revenue_tolerance", "revenue_tolerance"),
    "projected_gross_profit": (
        "projected_gross_profit_tolerance",
        "gross_profit_tolerance",
    ),
    "projected_operating_income": (
        "projected_operating_income_tolerance",
        "operating_income_tolerance",
        "income_tolerance",
    ),
    "gross_margin_pct": (
        "gross_margin_tolerance",
        "gross_margin_pct_tolerance",
        "margin_tolerance",
    ),
}


def normalize_scenario_projection_rows(
    rows: Iterable[dict[str, Any]],
    *,
    validate_formulas: bool = True,
) -> list[dict[str, Any]]:
    """Normalize typed company scenario projection rows.

    Rows are intentionally explicit: the quant script owns the scenario
    assumptions, base period, units, derived revenue, and optional operating
    income math. Report tables and charts can use custom labels, but the row
    must preserve enough mapping metadata for artifact gates to check them.
    """

    if rows is None or isinstance(rows, (str, bytes, dict)):
        raise ValueError("scenario projection rows must be a non-empty list")

    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            errors.append(f"{SCENARIO_PROJECTION_ROWS_KEY}[{index}]: expected object")
            continue
        try:
            row = _normalize_projection_row(raw)
            if validate_formulas:
                formula_mismatches = scenario_projection_formula_mismatches(
                    row,
                    source=f"{SCENARIO_PROJECTION_ROWS_KEY}[{index}]",
                )
                if formula_mismatches:
                    errors.extend(
                        _format_formula_error(item)
                        for item in formula_mismatches
                    )
                    continue
            normalized.append(row)
        except ValueError as exc:
            errors.append(f"{SCENARIO_PROJECTION_ROWS_KEY}[{index}]: {exc}")

    if errors:
        raise ValueError("; ".join(errors))
    if not normalized:
        raise ValueError("scenario projection rows must include at least one row")
    return normalized


def scenario_projection_formula_mismatches(
    row: dict[str, Any],
    *,
    source: str,
) -> list[dict[str, Any]]:
    """Return structured formula mismatches for one normalized projection row."""

    scenario = str(row.get("scenario") or "unknown")
    subject = str(row.get("subject") or "unknown")
    tolerance = scenario_projection_metric_tolerance(
        row,
        "projected_revenue",
        row.get("projected_revenue_unit"),
    )

    mismatches: list[dict[str, Any]] = []
    expected_revenue = expected_projected_revenue(row)
    projected_revenue = _finite_float(row.get("projected_revenue"))
    if projected_revenue is None:
        mismatches.append(
            _formula_mismatch(
                scenario=scenario,
                subject=subject,
                metric="projected_revenue",
                reason="missing_projected_revenue",
                source=source,
                actual=None,
                expected=expected_revenue,
                unit=row.get("projected_revenue_unit"),
                tolerance=tolerance,
            )
        )
    elif abs(projected_revenue - expected_revenue) > max(tolerance, 1e-9):
        mismatches.append(
            _formula_mismatch(
                scenario=scenario,
                subject=subject,
                metric="projected_revenue",
                reason="projected_revenue_formula_mismatch",
                source=source,
                actual=projected_revenue,
                expected=expected_revenue,
                unit=row.get("projected_revenue_unit"),
                tolerance=tolerance,
                assumptions={
                    "base_revenue": row.get("base_revenue"),
                    "base_revenue_unit": row.get("base_revenue_unit"),
                    "revenue_growth_pct": row.get("revenue_growth_pct"),
                },
            )
        )

    gross_profit = _finite_float(row.get("projected_gross_profit"))
    if gross_profit is not None:
        expected_gross_profit = expected_projected_gross_profit(row)
        gross_profit_unit = str(row.get("projected_gross_profit_unit") or "")
        gross_tolerance = scenario_projection_metric_tolerance(
            row,
            "projected_gross_profit",
            gross_profit_unit,
        )
        if abs(gross_profit - expected_gross_profit) > max(gross_tolerance, 1e-9):
            mismatches.append(
                _formula_mismatch(
                    scenario=scenario,
                    subject=subject,
                    metric="projected_gross_profit",
                    reason="projected_gross_profit_formula_mismatch",
                    source=source,
                    actual=gross_profit,
                    expected=expected_gross_profit,
                    unit=gross_profit_unit,
                    tolerance=gross_tolerance,
                    assumptions={
                        "projected_revenue": row.get("projected_revenue"),
                        "gross_margin_pct": row.get("gross_margin_pct"),
                    },
                )
            )

    if "projected_operating_income" in row:
        expected_income = expected_projected_operating_income(row)
        operating_income = _finite_float(row.get("projected_operating_income"))
        income_unit = str(row.get("operating_income_unit") or "")
        income_tolerance = scenario_projection_metric_tolerance(
            row,
            "projected_operating_income",
            income_unit,
        )
        if operating_income is None:
            mismatches.append(
                _formula_mismatch(
                    scenario=scenario,
                    subject=subject,
                    metric="projected_operating_income",
                    reason="missing_projected_operating_income",
                    source=source,
                    actual=None,
                    expected=expected_income,
                    unit=income_unit,
                    tolerance=income_tolerance,
                )
            )
        elif abs(operating_income - expected_income) > max(income_tolerance, 1e-9):
            mismatches.append(
                _formula_mismatch(
                    scenario=scenario,
                    subject=subject,
                    metric="projected_operating_income",
                    reason="projected_operating_income_formula_mismatch",
                    source=source,
                    actual=operating_income,
                    expected=expected_income,
                    unit=income_unit,
                    tolerance=income_tolerance,
                    assumptions={
                        "projected_revenue": row.get("projected_revenue"),
                        "gross_margin_pct": row.get("gross_margin_pct"),
                        "operating_expense": row.get("operating_expense"),
                        "operating_expense_unit": row.get("operating_expense_unit"),
                    },
                )
            )
    return mismatches


def scenario_projection_metric_tolerance(
    row: dict[str, Any],
    metric: str,
    unit: Any,
) -> float:
    """Return the numeric tolerance in the same unit as ``metric``."""

    normalized_unit = _normalize_metric_unit(metric, unit)
    metric_tolerance = _metric_specific_tolerance(row, metric)
    if metric_tolerance is not None:
        return metric_tolerance
    if metric == "gross_margin_pct":
        return max(_default_tolerance(normalized_unit), 0.0)

    row_tolerance = _finite_float(row.get("tolerance"))
    revenue_unit = _normalize_currency_unit(
        row.get("projected_revenue_unit"),
        field_name="projected_revenue_unit",
    )
    if row_tolerance is not None and (
        metric == "projected_revenue" or normalized_unit == revenue_unit
    ):
        if row_tolerance < 0:
            raise ValueError("tolerance must be non-negative")
        return max(row_tolerance, 0.0)

    return max(_default_tolerance(normalized_unit), 0.0)


def expected_projected_revenue(row: dict[str, Any]) -> float:
    base_revenue = _required_number(row, "base_revenue")
    growth_pct = _required_number(row, "revenue_growth_pct")
    base_unit = str(row.get("base_revenue_unit") or "")
    output_unit = str(row.get("projected_revenue_unit") or "")
    projected_in_base_unit = base_revenue * (1.0 + growth_pct / 100.0)
    return _convert_units(projected_in_base_unit, base_unit, output_unit)


def expected_projected_gross_profit(row: dict[str, Any]) -> float:
    projected_revenue = _required_number(row, "projected_revenue")
    margin_pct = _required_number(row, "gross_margin_pct")
    revenue_unit = str(row.get("projected_revenue_unit") or "")
    gross_profit_unit = str(row.get("projected_gross_profit_unit") or revenue_unit)
    gross_profit = projected_revenue * margin_pct / 100.0
    return _convert_units(gross_profit, revenue_unit, gross_profit_unit)


def expected_projected_operating_income(row: dict[str, Any]) -> float:
    projected_revenue = _required_number(row, "projected_revenue")
    margin_pct = _required_number(row, "gross_margin_pct")
    operating_expense = _required_number(row, "operating_expense")
    revenue_unit = str(row.get("projected_revenue_unit") or "")
    expense_unit = str(row.get("operating_expense_unit") or "")
    income_unit = str(row.get("operating_income_unit") or revenue_unit)
    gross_profit = _convert_units(
        projected_revenue * margin_pct / 100.0,
        revenue_unit,
        income_unit,
    )
    expense = _convert_units(operating_expense, expense_unit, income_unit)
    return gross_profit - expense


def _normalize_projection_row(raw: dict[str, Any]) -> dict[str, Any]:
    scenario = _required_text(raw, "scenario", "name", "label")
    subject = _required_text(raw, "subject", "company", "ticker", "issuer")
    base_period = _required_text(raw, "base_period", "base_fiscal_year", "base_year")
    projection_period = _required_text(
        raw,
        "projection_period",
        "output_period",
        "projected_period",
        "target_period",
    )

    base_unit = _required_currency_unit(
        raw,
        "base_revenue_unit",
        "base_unit",
        "revenue_unit",
        "unit",
    )
    output_unit = _currency_unit_or_default(
        raw,
        base_unit,
        "projected_revenue_unit",
        "output_unit",
        "revenue_unit",
    )

    tolerance = _finite_float(_first_present(raw, "tolerance", "projection_tolerance"))
    if tolerance is None:
        tolerance = _default_tolerance(output_unit)
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")

    row: dict[str, Any] = {
        "scenario": scenario,
        "subject": subject,
        "base_period": base_period,
        "projection_period": projection_period,
        "base_revenue": _required_number_from(
            raw,
            "base_revenue",
            "base_value",
        ),
        "base_revenue_unit": base_unit,
        "revenue_growth_pct": _required_number_from(
            raw,
            "revenue_growth_pct",
            "growth_pct",
            "growth_rate_pct",
        ),
        "projected_revenue": _required_number_from(
            raw,
            "projected_revenue",
            "output_revenue",
            "revenue",
            "projected_value",
        ),
        "projected_revenue_unit": output_unit,
        "tolerance": tolerance,
    }
    _copy_optional_tolerance(
        raw,
        row,
        "projected_revenue_tolerance",
        "projected_revenue_tolerance",
        "revenue_tolerance",
    )

    _copy_optional_text(
        raw,
        row,
        "source_key",
        "method",
        "basis",
        "note",
        "notes",
    )

    gross_margin_pct = _finite_float(
        _first_present(raw, "gross_margin_pct", "margin_pct")
    )
    operating_expense = _finite_float(
        _first_present(
            raw,
            "operating_expense",
            "operating_expenses",
            "opex",
            "fixed_operating_expense",
        )
    )
    operating_income = _finite_float(
        _first_present(
            raw,
            "projected_operating_income",
            "operating_income",
            "projected_oi",
            "oi",
        )
    )
    gross_profit = _finite_float(
        _first_present(raw, "projected_gross_profit", "gross_profit")
    )
    if gross_margin_pct is not None:
        row["gross_margin_pct"] = gross_margin_pct
        _copy_optional_tolerance(
            raw,
            row,
            "gross_margin_tolerance",
            "gross_margin_tolerance",
            "gross_margin_pct_tolerance",
            "margin_tolerance",
        )
    if gross_profit is not None:
        if gross_margin_pct is None:
            raise ValueError(
                "projected_gross_profit requires gross_margin_pct or margin_pct"
            )
        row["projected_gross_profit"] = gross_profit
        row["projected_gross_profit_unit"] = _currency_unit_or_default(
            raw,
            output_unit,
            "projected_gross_profit_unit",
            "gross_profit_unit",
            "output_unit",
        )
        _copy_optional_tolerance(
            raw,
            row,
            "projected_gross_profit_tolerance",
            "projected_gross_profit_tolerance",
            "gross_profit_tolerance",
        )
    if operating_expense is not None or operating_income is not None:
        missing = []
        if gross_margin_pct is None:
            missing.append("gross_margin_pct")
        if operating_expense is None:
            missing.append("operating_expense")
        if operating_income is None:
            missing.append("projected_operating_income")
        if missing:
            raise ValueError(
                "operating-income scenario rows require "
                + ", ".join(missing)
            )
        row["operating_expense"] = operating_expense
        row["operating_expense_unit"] = _currency_unit_or_default(
            raw,
            output_unit,
            "operating_expense_unit",
            "opex_unit",
            "expense_unit",
            "output_unit",
        )
        row["projected_operating_income"] = operating_income
        row["operating_income_unit"] = _currency_unit_or_default(
            raw,
            output_unit,
            "operating_income_unit",
            "income_unit",
            "output_unit",
        )
        _copy_optional_tolerance(
            raw,
            row,
            "projected_operating_income_tolerance",
            "projected_operating_income_tolerance",
            "operating_income_tolerance",
            "income_tolerance",
        )

    chart_id = _optional_text(raw, "chart_id")
    if chart_id:
        row["chart_id"] = chart_id
        row["chart_label"] = (
            _optional_text(raw, "chart_label", "chart_row_label") or scenario
        )
        row["chart_label_key"] = (
            _optional_text(raw, "chart_label_key", "chart_row_key", "x_axis_key")
            or "scenario"
        )
        row["revenue_data_key"] = (
            _optional_text(raw, "revenue_data_key", "projected_revenue_data_key")
            or "projected_revenue"
        )
        if "projected_operating_income" in row:
            row["operating_income_data_key"] = (
                _optional_text(
                    raw,
                    "operating_income_data_key",
                    "projected_operating_income_data_key",
                )
                or "projected_operating_income"
            )
        if "projected_gross_profit" in row:
            row["gross_profit_data_key"] = (
                _optional_text(
                    raw,
                    "gross_profit_data_key",
                    "projected_gross_profit_data_key",
                )
                or "projected_gross_profit"
            )
        margin_data_key = _optional_text(
            raw,
            "gross_margin_data_key",
            "margin_data_key",
        )
        if margin_data_key:
            row["gross_margin_data_key"] = margin_data_key

    return row


def _formula_mismatch(
    *,
    scenario: str,
    subject: str,
    metric: str,
    reason: str,
    source: str,
    actual: float | None,
    expected: float,
    unit: Any,
    tolerance: float,
    assumptions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "subject": subject,
        "metric": metric,
        "reason": reason,
        "observations": [
            {
                "source": f"{source}.{metric}",
                "value": _rounded(actual),
                "unit": unit,
            },
            {
                "source": "scenario_projection_formula",
                "value": _rounded(expected),
                "unit": unit,
                **({"assumptions": assumptions} if assumptions else {}),
            },
        ],
        "tolerance": tolerance,
    }


def _format_formula_error(mismatch: dict[str, Any]) -> str:
    observations = mismatch.get("observations")
    actual = None
    expected = None
    if isinstance(observations, list) and len(observations) >= 2:
        if isinstance(observations[0], dict):
            actual = observations[0].get("value")
        if isinstance(observations[1], dict):
            expected = observations[1].get("value")
    return (
        f"{SCENARIO_PROJECTION_ROWS_KEY} "
        f"{mismatch.get('subject')}/{mismatch.get('scenario')} "
        f"{mismatch.get('metric')}={actual} contradicts formula expected "
        f"{expected} (reason={mismatch.get('reason')})"
    )


def _required_text(raw: dict[str, Any], *names: str) -> str:
    value = _optional_text(raw, *names)
    if value is None:
        raise ValueError(f"missing non-empty {names[0]}")
    return value


def _optional_text(raw: dict[str, Any], *names: str) -> str | None:
    value = _first_present(raw, *names)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _copy_optional_text(raw: dict[str, Any], row: dict[str, Any], *names: str) -> None:
    for name in names:
        value = _optional_text(raw, name)
        if value is not None:
            row[name] = value


def _copy_optional_tolerance(
    raw: dict[str, Any],
    row: dict[str, Any],
    canonical: str,
    *names: str,
) -> None:
    tolerance = _finite_float(_first_present(raw, *names))
    if tolerance is None:
        return
    if tolerance < 0:
        raise ValueError(f"{canonical} must be non-negative")
    row[canonical] = tolerance


def _metric_specific_tolerance(row: dict[str, Any], metric: str) -> float | None:
    for key in _METRIC_TOLERANCE_KEYS.get(metric, ()):
        tolerance = _finite_float(row.get(key))
        if tolerance is None:
            continue
        if tolerance < 0:
            raise ValueError(f"{key} must be non-negative")
        return tolerance
    return None


def _required_number_from(raw: dict[str, Any], *names: str) -> float:
    value = _finite_float(_first_present(raw, *names))
    if value is None:
        raise ValueError(f"missing finite {names[0]}")
    return value


def _required_number(row: dict[str, Any], name: str) -> float:
    value = _finite_float(row.get(name))
    if value is None:
        raise ValueError(f"missing finite {name}")
    return value


def _required_currency_unit(raw: dict[str, Any], *names: str) -> str:
    value = _optional_text(raw, *names)
    if value is None:
        raise ValueError(f"missing non-empty {names[0]}")
    return _normalize_currency_unit(value, field_name=names[0])


def _currency_unit_or_default(raw: dict[str, Any], default: str, *names: str) -> str:
    value = _optional_text(raw, *names)
    if value is None:
        return _normalize_currency_unit(default, field_name=names[0])
    return _normalize_currency_unit(value, field_name=names[0])


def _normalize_unit(value: Any) -> str:
    text = str(value or "").strip().lower()
    normalized = _UNIT_ALIASES.get(text, text)
    if normalized not in _SUPPORTED_UNITS:
        raise ValueError(f"unsupported scenario projection unit: {value}")
    return normalized


def _normalize_currency_unit(value: Any, *, field_name: str) -> str:
    normalized = _normalize_unit(value)
    if normalized not in _CURRENCY_FACTORS:
        raise ValueError(f"{field_name} must use a currency unit, got {value}")
    return normalized


def _normalize_metric_unit(metric: str, unit: Any) -> str:
    if metric == "gross_margin_pct":
        normalized = _normalize_unit(unit)
        if normalized != "percent":
            raise ValueError(f"{metric} must use percent units, got {unit}")
        return normalized
    return _normalize_currency_unit(unit, field_name=f"{metric}_unit")


def _convert_units(value: float, source_unit: str, target_unit: str) -> float:
    source_unit = _normalize_currency_unit(source_unit, field_name="source_unit")
    target_unit = _normalize_currency_unit(target_unit, field_name="target_unit")
    if source_unit == target_unit:
        return value
    return value * _CURRENCY_FACTORS[source_unit] / _CURRENCY_FACTORS[target_unit]


def _default_tolerance(unit: str) -> float:
    if unit in {"usd_b", "usd_m", "usd"}:
        return _convert_units(50_000_000.0, "usd", unit)
    if unit == "percent":
        return 0.05
    raise ValueError(f"unsupported scenario projection unit: {unit}")


def _first_present(raw: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in raw and raw.get(name) is not None:
            return raw.get(name)
    return None


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)
