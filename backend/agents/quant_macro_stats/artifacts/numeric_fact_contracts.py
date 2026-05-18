"""Reusable evidence helpers for quant execution summaries."""

from __future__ import annotations

import re
from typing import Any

from .._utils import finite_number as _finite
from .._utils import latest_finite_observation as _latest_finite_observation
from .._utils import rounded_number as _round

_UNIT_ALIASES = {
    "%": "percent",
    "pct": "percent",
    "percentage": "percent",
    "percentage_points": "percentage_point",
    "percentage points": "percentage_point",
    "pp": "percentage_point",
    "$": "usd",
    "dollar": "usd",
    "dollars": "usd",
    "month": "months",
}
_DURATION_UNITS = {"months"}
_CURRENT_STATE_DURATION_ROLE = "current_state_duration"
_ZERO_DURATION_STATE_DESCRIPTION = (
    "0 months means no active/current episode; describe the current state "
    "semantically instead of saying a historical episode lasted 0 months."
)
_ZERO_DURATION_MISUSE_RE = re.compile(
    r"\b(?:after|for|lasting|lasted|over|through|during|following)\s+"
    r"(?:about|around|roughly|approximately)?\s*0(?:\.0+)?\s*months?\b|"
    r"\b0(?:\.0+)?\s*months?\s+(?:of|long|duration|episode|period)\b",
    re.IGNORECASE,
)


def normalize_unit(unit: Any) -> str:
    """Return the canonical unit token used by numeric fact display helpers."""

    normalized = str(unit or "").strip().lower()
    return _UNIT_ALIASES.get(normalized, normalized)


def round_for_display(value: float, precision: int) -> float:
    return float(round(value, precision))


def display_value(value: Any, *, unit: str, precision: int) -> str | None:
    number = _finite(value)
    if number is None:
        return None
    canonical_unit = normalize_unit(unit)
    rounded = round_for_display(number, precision)
    decimals = max(precision, 0)
    if canonical_unit in {"usd", "usd_per_person"}:
        return f"${rounded:,.{decimals}f}"
    if canonical_unit == "usd_b":
        return f"${rounded:,.{decimals}f}B"
    if canonical_unit == "percent":
        return f"{rounded:,.{decimals}f}%"
    if canonical_unit == "percentage_point":
        return f"{rounded:,.{decimals}f} pp"
    if canonical_unit == "multiple":
        return f"{rounded:,.{decimals}f}x"
    if canonical_unit == "months":
        suffix = "month" if abs(rounded) == 1 else "months"
        return f"{rounded:,.{decimals}f} {suffix}"
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
    semantic_role: str | None = None,
    literal_required: bool | None = None,
    state_description: str | None = None,
) -> dict[str, Any] | None:
    number = _finite(raw_value)
    canonical_unit = normalize_unit(unit)
    display = display_value(number, unit=canonical_unit, precision=precision)
    if number is None or display is None:
        return None
    zero_duration_state = _is_zero_duration_state(number, canonical_unit)
    resolved_role = _semantic_role(semantic_role)
    if resolved_role is None and zero_duration_state:
        resolved_role = _CURRENT_STATE_DURATION_ROLE
    current_state_duration = _is_current_state_duration(number, canonical_unit, resolved_role)
    resolved_literal_required = _coerce_literal_required(
        literal_required,
        strict=True,
        location="literal_required",
        allow_none=True,
    )
    if resolved_literal_required is False and not current_state_duration:
        raise ValueError(_non_literal_error("literal_required"))
    if current_state_duration:
        resolved_literal_required = False
    fact: dict[str, Any] = {
        "id": fact_id,
        "label": label,
        "raw_value": _round(number, max(precision, 3) if precision >= 0 else 3),
        "display_value": display,
        "unit": canonical_unit,
        "precision": precision,
        "tolerance": tolerance,
        "source_key": source_key,
    }
    if resolved_role:
        fact["semantic_role"] = resolved_role
    if resolved_literal_required is not None:
        fact["literal_required"] = resolved_literal_required
    if state_description:
        fact["state_description"] = str(state_description)
    elif current_state_duration:
        fact["state_description"] = _ZERO_DURATION_STATE_DESCRIPTION
    if as_of_date is not None:
        fact["as_of_date"] = str(as_of_date)
    if subject:
        fact["subject"] = subject
    if metric:
        fact["metric"] = metric
    return fact


def latest_numeric_fact(
    panel: Any,
    key: str,
    *,
    fact_id: str,
    label: str,
    unit: str,
    precision: int,
    tolerance: float,
    source_key: str | None = None,
    subject: str | None = None,
    metric: str | None = None,
    digits: int | None = None,
) -> dict[str, Any] | None:
    value, as_of_date = _latest_finite_observation(
        panel,
        key,
        digits=digits if digits is not None else max(precision, 3),
    )
    return numeric_fact(
        fact_id=fact_id,
        label=label,
        raw_value=value,
        unit=unit,
        precision=precision,
        tolerance=tolerance,
        source_key=source_key or key,
        as_of_date=as_of_date,
        subject=subject,
        metric=metric or key,
    )


def normalize_numeric_fact(
    item: Any,
    *,
    strict: bool = False,
    index: int | None = None,
) -> dict[str, Any] | None:
    """Canonicalize a legacy or helper-produced numeric fact payload."""

    location = f"numeric_facts[{index}]" if index is not None else "numeric_fact"
    if not isinstance(item, dict):
        if strict:
            raise ValueError(f"{location} must be a JSON object")
        return None

    fact_id = str(item.get("id") or item.get("source_key") or "").strip()
    if not fact_id:
        if strict:
            raise ValueError(f"{location} must include id or source_key")
        return None

    raw_source = item.get("raw_value", item.get("value"))
    number = _finite(raw_source)
    if number is None:
        if strict:
            raise ValueError(f"{location} must include a finite raw_value or value")
        return None

    precision = _coerce_int(item.get("precision"), default=3)
    canonical_unit = normalize_unit(item.get("unit"))
    tolerance = _finite(item.get("tolerance"))
    if tolerance is None:
        tolerance = 0.0
    display = str(item.get("display_value") or "").strip()
    if not display:
        display = display_value(number, unit=canonical_unit, precision=precision) or ""
    if not display:
        if strict:
            raise ValueError(f"{location} must include a renderable display_value")
        return None

    literal_required = None
    if "literal_required" in item:
        literal_required = _coerce_literal_required(
            item.get("literal_required"),
            strict=strict,
            location=f"{location}.literal_required",
            allow_none=False,
        )

    fact = dict(item)
    fact.pop("value", None)
    fact.pop("literal_required", None)
    fact.update(
        {
            "id": fact_id,
            "label": str(item.get("label") or fact_id),
            "raw_value": _round(number, max(precision, 3) if precision >= 0 else 3),
            "display_value": display,
            "unit": canonical_unit,
            "precision": precision,
            "tolerance": tolerance,
            "source_key": str(item.get("source_key") or fact_id),
        }
    )

    semantic_role = _semantic_role(item.get("semantic_role"))
    if semantic_role is None and _is_zero_duration_state(number, canonical_unit):
        semantic_role = _CURRENT_STATE_DURATION_ROLE
    current_state_duration = _is_current_state_duration(number, canonical_unit, semantic_role)
    if literal_required is False and not current_state_duration:
        if strict:
            raise ValueError(_non_literal_error(f"{location}.literal_required"))
        literal_required = None
    if current_state_duration:
        literal_required = False
        fact.setdefault("state_description", _ZERO_DURATION_STATE_DESCRIPTION)
    if semantic_role is not None:
        fact["semantic_role"] = semantic_role
    if literal_required is not None:
        fact["literal_required"] = literal_required
    return fact


def normalize_numeric_facts(value: Any, *, strict: bool = False) -> list[dict[str, Any]]:
    """Return canonical numeric facts from an execution-summary field."""

    if value is None:
        return []
    if not isinstance(value, list):
        if strict:
            raise ValueError("numeric_facts must be a list")
        return []

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        fact = normalize_numeric_fact(item, strict=strict, index=index)
        if fact is not None:
            normalized.append(fact)
    return normalized


def numeric_fact_literal_required(fact: dict[str, Any]) -> bool:
    """Return whether report prose should include this fact's numeric value."""

    value = fact.get("literal_required", True)
    if value is False and _non_literal_allowed_for_fact(fact):
        return False
    return True


def numeric_fact_current_state_duration_misuse(text: str, fact: dict[str, Any]) -> bool:
    """Detect prose that turns a current-state zero duration into history."""

    if not _non_literal_allowed_for_fact(fact):
        return False
    return bool(_ZERO_DURATION_MISUSE_RE.search(text))


def _is_zero_duration_state(number: float, unit: str) -> bool:
    return unit in _DURATION_UNITS and abs(number) <= 1e-12


def _is_current_state_duration(
    number: float,
    unit: str,
    semantic_role: str | None,
) -> bool:
    return semantic_role == _CURRENT_STATE_DURATION_ROLE and _is_zero_duration_state(number, unit)


def _semantic_role(value: Any) -> str | None:
    role = str(value or "").strip()
    return role or None


def _non_literal_allowed_for_fact(fact: dict[str, Any]) -> bool:
    number = _finite(fact.get("raw_value", fact.get("value")))
    if number is None:
        return False
    return _is_current_state_duration(
        number,
        normalize_unit(fact.get("unit")),
        _semantic_role(fact.get("semantic_role")),
    )


def _non_literal_error(location: str) -> str:
    return (
        f"{location}=false is only valid for zero-duration "
        "current_state_duration numeric facts"
    )


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_literal_required(
    value: Any,
    *,
    strict: bool,
    location: str,
    allow_none: bool,
) -> bool | None:
    if value is None:
        if strict and not allow_none:
            raise ValueError(f"{location} must be a boolean when provided")
        return None
    if isinstance(value, bool):
        return value
    if strict:
        raise ValueError(f"{location} must be a boolean when provided")
    return None
