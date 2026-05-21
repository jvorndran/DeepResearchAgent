"""Reusable evidence helpers for quant execution summaries."""

from __future__ import annotations

import re
from typing import Any

from .._utils import finite_number as _finite
from .._utils import latest_finite_observation as _latest_finite_observation
from .._utils import rounded_number as _round
from .current_scalar_aliases import expand_current_scalar_aliases

_UNIT_ALIASES = {
    "%": "percent",
    "pct": "percent",
    "percentage": "percent",
    "percentage_points": "percentage_point",
    "percentage points": "percentage_point",
    "pp": "percentage_point",
    "$": "usd",
    "day": "days",
    "dollar": "usd",
    "dollars": "usd",
    "month": "months",
    "week": "weeks",
}
_DURATION_UNITS = {"days", "weeks", "months"}
_CURRENT_STATE_DURATION_ROLE = "current_state_duration"
_INACTIVE_DURATION_STATE_DESCRIPTION_TEMPLATE = (
    "0 {unit} means no active/current episode; describe the current state "
    "semantically instead of saying a historical episode lasted 0 {unit}."
)
_ZERO_DURATION_MISUSE_RE = re.compile(
    r"\b(?:after|for|lasting|lasted|over|through|during|following)\s+"
    r"(?:about|around|roughly|approximately)?\s*0(?:\.0+)?\s*"
    r"(?:days?|weeks?|months?)\b|"
    r"\b0(?:\.0+)?\s*(?:days?|weeks?|months?)\s+"
    r"(?:of|long|duration|episode|period)\b",
    re.IGNORECASE,
)
_NUMERIC_FACT_VALUE_TOKEN_RE = re.compile(
    r"(?<![\w.])-?\$?\d[\d,]*(?:\.\d+)?%?(?![\w]|\.\d)"
)
_NUMERIC_FACT_CONTEXT_SPLIT_RE = re.compile(r"[\n\r|]+|(?<=[.!?])\s+")
_NUMERIC_FACT_SEMICOLON_METRIC_CLAUSE_SPLIT_RE = re.compile(r"\s*;\s*")
_NUMERIC_FACT_STRONG_METRIC_CLAUSE_SPLIT_RE = re.compile(
    r"\s+\b(?:while|whereas|whilst)\b\s+",
    re.IGNORECASE,
)
_NUMERIC_FACT_AND_METRIC_CLAUSE_SPLIT_RE = re.compile(
    r"\s+\band\b\s+",
    re.IGNORECASE,
)
_NUMERIC_FACT_COMMA_METRIC_CLAUSE_SPLIT_RE = re.compile(r"(?<!\d),(?!\d)\s+")
_NUMERIC_FACT_COMPARISON_METRIC_CLAUSE_SPLIT_RE = re.compile(
    r"\s+\b(?:above|below|under|over|within|outside|inside|versus|vs\.?|"
    r"relative\s+to|compared\s+with|compared\s+to)\s+",
    re.IGNORECASE,
)
_NUMERIC_FACT_CURRENT_ASSERTION_RE = re.compile(
    r"\b(?:as\s+of|current(?:ly)?|latest|most\s+recent|now|today|"
    r"stands?|sits?|runs?|reads?|prints?|registered|came\s+in|comes\s+in|"
    r"is|are|was|were|eased|slowed|cooled|rose|rises|fell|falls|"
    r"declined|declines|increased|increases|decreased|decreases|"
    r"accelerated|accelerates|decelerated|decelerates|decelerating|"
    r"moderated|moderates|moderating)\b",
    re.IGNORECASE,
)
_NUMERIC_FACT_HISTORICAL_VALUE_MARKER_RE = re.compile(
    r"\b(?:historical|history|average|avg|mean|median|prior|previous|"
    r"previously|last\s+(?:month|quarter|year)|pre[-\s]?pandemic|"
    r"(?:in|during|through|for)\s+"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+"
    r"(?:19|20)\d{2}|"
    r"in\s+(?:19|20)\d{2}|during\s+(?:19|20)\d{2}|"
    r"through\s+(?:19|20)\d{2}|between\s+(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_NUMERIC_FACT_FROM_VALUE_MARKER_RE = re.compile(
    r"\bfrom\s+(?:about|around|roughly|approximately|approx\.?)?\s*$",
    re.IGNORECASE,
)
_NUMERIC_FACT_CURRENT_ENDPOINT_BRIDGE_RE = re.compile(r"\bto\s*$", re.IGNORECASE)
_NUMERIC_FACT_CHANGE_DELTA_BEFORE_RE = re.compile(
    r"\b(?:rose|rises|rising|fell|falls|falling|increased|increases|"
    r"increasing|decreased|decreases|decreasing|declined|declines|"
    r"declining|eased|eases|easing|slowed|slows|slowing|cooled|cools|"
    r"cooling|accelerated|accelerates|accelerating|decelerated|decelerates|"
    r"decelerating|moderated|moderates|moderating|widened|widens|"
    r"widening|narrowed|narrows|narrowing|jumped|jumps|jumping|dropped|"
    r"drops|dropping|moved|moves|moving|changed|changes|changing|up|"
    r"down|higher|lower)\s+(?:by\s+)?"
    r"(?:(?:about|around|roughly|approximately|approx\.?)\s+)?$",
    re.IGNORECASE,
)
_NUMERIC_FACT_CHANGE_DELTA_UNIT_AFTER_RE = re.compile(
    r"^\s*(?:%|pct\.?|percent(?:age)?|percentage\s+points?|pp)\b",
    re.IGNORECASE,
)
_NUMERIC_FACT_NON_CURRENT_VALUE_MARKER_RE = re.compile(
    r"\b(?:threshold|trigger|target|scenario|forecast|projection|"
    r"reference\s+line|reference\s+band|range|watchlist\s+trigger)\b",
    re.IGNORECASE,
)
_NUMERIC_FACT_COMPARISON_BRIDGE_RE = re.compile(
    r"\b(?:above|below|under|over|within|outside|inside|versus|vs\.?|"
    r"relative\s+to|compared\s+with|compared\s+to)\b",
    re.IGNORECASE,
)
_NUMERIC_FACT_MONTH_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b",
    re.IGNORECASE,
)
_NUMERIC_FACT_QUARTER_RE = re.compile(r"\bq[1-4]\b", re.IGNORECASE)
_NUMERIC_FACT_DATE_QUALIFIER_RE = re.compile(
    r"\b(?:as\s+of|through|during|for|on|in)\s*$",
    re.IGNORECASE,
)
_NUMERIC_FACT_YEAR_RE = re.compile(r"^(?:19|20|21)\d{2}$")
_NUMERIC_FACT_GENERIC_MARKER_TOKENS = {
    "chart",
    "current",
    "data",
    "date",
    "display",
    "fact",
    "from",
    "index",
    "latest",
    "line",
    "numeric",
    "pct",
    "percent",
    "percentage",
    "point",
    "points",
    "pp",
    "rate",
    "series",
    "value",
    "yoy",
}
_NUMERIC_FACT_TABLE_CURRENT_HEADER_RE = re.compile(
    r"\b(?:as\s+of|current|latest|most\s+recent|now|today|reading|value)\b",
    re.IGNORECASE,
)
_NUMERIC_FACT_TABLE_METRIC_HEADER_RE = re.compile(
    r"\b(?:indicator|metric|measure|series|variable|name|factor)\b",
    re.IGNORECASE,
)
_NUMERIC_FACT_MARKER_SCOPE_SPLIT_TOKENS = {"and", "vs", "versus"}


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
    if canonical_unit in _DURATION_UNITS:
        suffix = canonical_unit[:-1] if abs(rounded) == 1 else canonical_unit
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
    operation: str | None = None,
    transform_basis: str | None = None,
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
    current_state_duration = _is_current_state_duration(canonical_unit, resolved_role)
    inactive_current_state_duration = current_state_duration and zero_duration_state
    resolved_literal_required = _coerce_literal_required(
        literal_required,
        strict=True,
        location="literal_required",
        allow_none=True,
    )
    if resolved_literal_required is False and not inactive_current_state_duration:
        raise ValueError(_non_literal_error("literal_required"))
    if inactive_current_state_duration:
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
    elif inactive_current_state_duration:
        fact["state_description"] = _inactive_duration_state_description(canonical_unit)
    if as_of_date is not None:
        fact["as_of_date"] = str(as_of_date)
    if subject:
        fact["subject"] = subject
    if metric:
        fact["metric"] = metric
    if operation:
        fact["operation"] = str(operation)
    if transform_basis:
        fact["transform_basis"] = str(transform_basis)
    return fact


def current_state_duration_fact(
    *,
    fact_id: str,
    label: str,
    raw_value: Any,
    unit: str,
    precision: int,
    tolerance: float,
    source_key: str,
    episode_active: bool,
    as_of_date: Any = None,
    subject: str | None = None,
    metric: str | None = None,
    operation: str | None = None,
    transform_basis: str | None = None,
    active_state_description: str | None = None,
    inactive_state_description: str | None = None,
) -> dict[str, Any] | None:
    """Build a duration fact for a currently active or inactive threshold episode."""

    if not isinstance(episode_active, bool):
        raise ValueError("episode_active must be a boolean")
    canonical_unit = normalize_unit(unit)
    number = _finite(raw_value)
    if number is not None:
        _validate_current_state_duration_fact(
            number,
            canonical_unit,
            episode_active=episode_active,
            location="current_state_duration_fact",
        )
    state_description = (
        active_state_description if episode_active else inactive_state_description
    )
    if not episode_active and not state_description:
        state_description = _inactive_duration_state_description(canonical_unit)
    fact = numeric_fact(
        fact_id=fact_id,
        label=label,
        raw_value=raw_value,
        unit=canonical_unit,
        precision=precision,
        tolerance=tolerance,
        source_key=source_key,
        as_of_date=as_of_date,
        subject=subject,
        metric=metric,
        semantic_role=_CURRENT_STATE_DURATION_ROLE,
        operation=operation,
        transform_basis=transform_basis,
        literal_required=False if not episode_active else None,
        state_description=state_description,
    )
    if fact is not None:
        fact["episode_active"] = episode_active
        if episode_active:
            fact.pop("literal_required", None)
            if not active_state_description:
                fact.pop("state_description", None)
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
    current_state_duration = _is_current_state_duration(canonical_unit, semantic_role)
    episode_active = _coerce_optional_bool(
        item.get("episode_active"),
        strict=strict,
        location=f"{location}.episode_active",
    )
    inactive_current_state_duration = (
        current_state_duration
        and episode_active is not True
        and _is_zero_duration_state(number, canonical_unit)
    )
    if current_state_duration and episode_active is not None:
        try:
            _validate_current_state_duration_fact(
                number,
                canonical_unit,
                episode_active=episode_active,
                location=location,
            )
        except ValueError:
            if strict:
                raise
    if literal_required is False and not inactive_current_state_duration:
        if strict:
            raise ValueError(_non_literal_error(f"{location}.literal_required"))
        literal_required = None
    if inactive_current_state_duration:
        literal_required = False
        fact.setdefault("state_description", _inactive_duration_state_description(canonical_unit))
    if semantic_role is not None:
        fact["semantic_role"] = semantic_role
    if episode_active is not None:
        fact["episode_active"] = episode_active
    if item.get("operation"):
        fact["operation"] = str(item["operation"])
    if item.get("transform_basis"):
        fact["transform_basis"] = str(item["transform_basis"])
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
    """Detect prose that turns an inactive current-state duration into history."""

    if not _non_literal_allowed_for_fact(fact):
        return False
    return bool(_ZERO_DURATION_MISUSE_RE.search(text))


def numeric_fact_conflicting_current_value_contexts(
    text: str,
    fact: dict[str, Any],
    *,
    limit: int = 4,
) -> list[str]:
    """Return chart-latest clauses that assert a different current value.

    This intentionally applies only to chart-linked latest-point facts. The
    global literal check still verifies that the correct display value appears
    somewhere in the report; this contextual check catches stale prose that
    names the same metric and substitutes a different current reading.
    """

    if not _requires_current_value_context_check(fact):
        return []
    raw_value = _finite(fact.get("raw_value", fact.get("value")))
    if raw_value is None:
        return []
    tolerance = abs(_finite(fact.get("tolerance")) or 0.0)
    blockers: list[str] = []
    for context in _numeric_fact_contexts(text):
        if not context or not _context_mentions_numeric_fact(context, fact):
            continue
        if not _NUMERIC_FACT_CURRENT_ASSERTION_RE.search(context):
            continue
        if _context_has_conflicting_numeric_value(
            context,
            raw_value=raw_value,
            tolerance=tolerance,
        ):
            blockers.append(_compact_context(context))
            if len(blockers) >= limit:
                break
    return blockers


def _is_zero_duration_state(number: float, unit: str) -> bool:
    return unit in _DURATION_UNITS and abs(number) <= 1e-12


def _is_current_state_duration(
    unit: str,
    semantic_role: str | None,
) -> bool:
    return semantic_role == _CURRENT_STATE_DURATION_ROLE and unit in _DURATION_UNITS


def _semantic_role(value: Any) -> str | None:
    role = str(value or "").strip()
    return role or None


def _non_literal_allowed_for_fact(fact: dict[str, Any]) -> bool:
    number = _finite(fact.get("raw_value", fact.get("value")))
    if number is None:
        return False
    unit = normalize_unit(fact.get("unit"))
    return _is_current_state_duration(
        unit,
        _semantic_role(fact.get("semantic_role")),
    ) and fact.get("episode_active") is not True and _is_zero_duration_state(
        number, unit
    )


def _requires_current_value_context_check(fact: dict[str, Any]) -> bool:
    return bool(
        str(fact.get("chart_id") or "").strip()
        and str(fact.get("data_key") or "").strip()
    )


def _numeric_fact_contexts(text: str) -> list[str]:
    contexts: list[str] = []
    text_value = str(text or "")
    contexts.extend(_numeric_fact_current_table_contexts(text_value))
    for chunk in _NUMERIC_FACT_CONTEXT_SPLIT_RE.split(text_value):
        for clause in _numeric_fact_comma_clauses(chunk):
            for metric_clause in _numeric_fact_metric_clauses(clause):
                cleaned = " ".join(metric_clause.split())
                if cleaned:
                    contexts.append(cleaned)
    return contexts


def _numeric_fact_comma_clauses(chunk: str) -> list[str]:
    parts = [
        part
        for part in _NUMERIC_FACT_COMMA_METRIC_CLAUSE_SPLIT_RE.split(chunk)
        if part.strip()
    ]
    split_parts = _metric_clause_split_parts(
        parts,
        require_current_assertion=True,
    )
    return split_parts if split_parts is not None else parts


def _numeric_fact_metric_clauses(clause: str) -> list[str]:
    clauses = [clause]
    for pattern, require_current_assertion in (
        (_NUMERIC_FACT_SEMICOLON_METRIC_CLAUSE_SPLIT_RE, True),
        (_NUMERIC_FACT_STRONG_METRIC_CLAUSE_SPLIT_RE, False),
        (_NUMERIC_FACT_COMPARISON_METRIC_CLAUSE_SPLIT_RE, True),
        (_NUMERIC_FACT_AND_METRIC_CLAUSE_SPLIT_RE, True),
    ):
        next_clauses: list[str] = []
        for candidate in clauses:
            parts = [part for part in pattern.split(candidate) if part.strip()]
            split_parts = _metric_clause_split_parts(
                parts,
                require_current_assertion=require_current_assertion,
            )
            if split_parts is not None:
                next_clauses.extend(split_parts)
            else:
                next_clauses.append(candidate)
        clauses = next_clauses
    return clauses


def _metric_clause_split_parts(
    parts: list[str],
    *,
    require_current_assertion: bool,
) -> list[str] | None:
    if len(parts) < 2:
        return None
    if any(_NUMERIC_FACT_VALUE_TOKEN_RE.search(part) is None for part in parts):
        return None
    if not require_current_assertion:
        return parts
    if all(_NUMERIC_FACT_CURRENT_ASSERTION_RE.search(part) for part in parts):
        return parts
    if not _NUMERIC_FACT_CURRENT_ASSERTION_RE.search(parts[0]):
        return None
    if not all(
        _metric_clause_has_metric_before_value(part)
        for part in parts[1:]
        if _NUMERIC_FACT_CURRENT_ASSERTION_RE.search(part) is None
    ):
        return None
    return [
        part
        if _NUMERIC_FACT_CURRENT_ASSERTION_RE.search(part)
        else f"current {part}"
        for part in parts
    ]


def _metric_clause_has_metric_before_value(part: str) -> bool:
    match = _NUMERIC_FACT_VALUE_TOKEN_RE.search(part)
    if match is None:
        return False
    leading_tokens = [
        token
        for token in _marker_tokens(part[: match.start()])
        if token not in _NUMERIC_FACT_GENERIC_MARKER_TOKENS
    ]
    return bool(leading_tokens)


def _numeric_fact_current_table_contexts(text: str) -> list[str]:
    contexts: list[str] = []
    lines = str(text or "").splitlines()
    index = 0
    while index < len(lines) - 1:
        header = _markdown_table_cells(lines[index])
        separator = _markdown_table_cells(lines[index + 1])
        if not header or not _is_markdown_table_separator(separator):
            index += 1
            continue

        current_columns = [
            position
            for position, cell in enumerate(header)
            if _NUMERIC_FACT_TABLE_CURRENT_HEADER_RE.search(cell)
        ]
        if not current_columns:
            index += 1
            continue
        metric_columns = [
            position
            for position, cell in enumerate(header)
            if _NUMERIC_FACT_TABLE_METRIC_HEADER_RE.search(cell)
        ]
        if not metric_columns:
            metric_columns = [0]

        index += 2
        while index < len(lines):
            row = _markdown_table_cells(lines[index])
            if not row:
                break
            if _is_markdown_table_separator(row):
                index += 1
                continue
            metric_pieces: list[str] = ["current table row"]
            for position in metric_columns:
                if position >= len(row):
                    continue
                metric_pieces.append(header[position])
                metric_pieces.append(row[position])
            metric_context = " ".join(
                piece.strip() for piece in metric_pieces if piece.strip()
            )
            for position in current_columns:
                if position >= len(row):
                    continue
                local_contexts = _numeric_fact_table_current_cell_contexts(
                    current_header=header[position],
                    current_cell=row[position],
                )
                if local_contexts:
                    contexts.extend(local_contexts)
                    continue
                cleaned = " ".join(
                    piece.strip()
                    for piece in (metric_context, header[position], row[position])
                    if piece.strip()
                )
                if cleaned:
                    contexts.append(cleaned)
            index += 1
    return contexts


def _numeric_fact_table_current_cell_contexts(
    *,
    current_header: str,
    current_cell: str,
) -> list[str]:
    seed = " ".join(
        piece.strip()
        for piece in ("current", current_header, current_cell)
        if piece.strip()
    )
    contexts: list[str] = []
    for clause in _numeric_fact_comma_clauses(seed):
        for metric_clause in _numeric_fact_metric_clauses(clause):
            cleaned = " ".join(metric_clause.split())
            if cleaned:
                contexts.append(cleaned)
    if len(contexts) < 2:
        return []
    header_tokens = set(_marker_tokens(current_header))
    if not all(
        _NUMERIC_FACT_CURRENT_ASSERTION_RE.search(context)
        for context in contexts
    ):
        return []
    if not all(
        _metric_clause_has_table_cell_metric_before_value(
            context,
            header_tokens=header_tokens,
        )
        for context in contexts
    ):
        return []
    return [f"current table row {context}" for context in contexts]


def _metric_clause_has_table_cell_metric_before_value(
    part: str,
    *,
    header_tokens: set[str],
) -> bool:
    match = _NUMERIC_FACT_VALUE_TOKEN_RE.search(part)
    if match is None:
        return False
    leading_tokens = [
        token
        for token in _marker_tokens(part[: match.start()])
        if token not in _NUMERIC_FACT_GENERIC_MARKER_TOKENS
        and token not in header_tokens
    ]
    return bool(leading_tokens)


def _markdown_table_cells(line: str) -> list[str] | None:
    if "|" not in line:
        return None
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    cells = [" ".join(cell.strip().split()) for cell in stripped.split("|")]
    return cells if len(cells) >= 2 else None


def _is_markdown_table_separator(cells: list[str] | None) -> bool:
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _context_mentions_numeric_fact(context: str, fact: dict[str, Any]) -> bool:
    context_tokens = set(_marker_tokens(context))
    if not context_tokens:
        return False
    marker_candidates: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    qualified_marker_tokens: set[str] = set()
    for marker in _numeric_fact_marker_phrases(fact):
        original_tokens = _marker_tokens(marker)
        marker_tokens = tuple(
            token
            for token in original_tokens
            if token not in _NUMERIC_FACT_GENERIC_MARKER_TOKENS
        )
        if not marker_tokens:
            continue
        marker_candidates.append((original_tokens, marker_tokens))
        if len(original_tokens) > 1:
            qualified_marker_tokens.update(marker_tokens)

    for original_tokens, marker_tokens in marker_candidates:
        if (
            len(original_tokens) == 1
            and len(marker_tokens) == 1
            and marker_tokens[0] in qualified_marker_tokens
        ):
            continue
        if all(
            _marker_token_matches_context(token, context_tokens)
            for token in marker_tokens
        ):
            return True
    return False


def _marker_token_matches_context(token: str, context_tokens: set[str]) -> bool:
    token_variants = _marker_token_variants(token)
    if token_variants & context_tokens:
        return True
    context_token_variants = set(context_tokens)
    for context_token in context_tokens:
        variant = _singular_marker_token(context_token)
        if variant is not None:
            context_token_variants.add(variant)
    return bool(token_variants & context_token_variants)


def _marker_token_variants(token: str) -> set[str]:
    tokens = {token}
    singular = _singular_marker_token(token)
    if singular is not None:
        tokens.add(singular)
    return expand_current_scalar_aliases(tokens)


def _numeric_fact_marker_phrases(fact: dict[str, Any]) -> tuple[str, ...]:
    if _requires_current_value_context_check(fact):
        return _chart_numeric_fact_marker_phrases(fact)

    markers: list[str] = []
    for key in ("metric", "data_key", "label", "chart_title", "id", "source_key"):
        _append_numeric_fact_marker_phrases(markers, fact.get(key))
    return tuple(dict.fromkeys(markers))


def _chart_numeric_fact_marker_phrases(fact: dict[str, Any]) -> tuple[str, ...]:
    markers: list[str] = []
    for key in ("metric", "data_key", "series_label"):
        _append_numeric_fact_marker_phrases(
            markers,
            fact.get(key),
            include_token_markers=False,
        )
    _append_numeric_fact_marker_phrases(
        markers,
        _chart_numeric_fact_local_label(fact),
        include_token_markers=False,
    )
    for key in ("chart_title", "chart_id"):
        _append_chart_scope_marker_phrase(markers, fact.get(key))
    return tuple(dict.fromkeys(markers))


def _chart_numeric_fact_local_label(fact: dict[str, Any]) -> str | None:
    label = _normalized_marker_text(fact.get("label"))
    if not label:
        return None

    chart_title = _normalized_marker_text(fact.get("chart_title"))
    if chart_title:
        suffix = f" from {chart_title}"
        if label.endswith(suffix):
            label = label[: -len(suffix)].strip()
    if label.startswith("latest "):
        label = label[len("latest ") :].strip()
    return label or None


def _append_chart_scope_marker_phrase(markers: list[str], value: Any) -> None:
    text = _normalized_marker_text(value)
    if not text:
        return
    tokens = _marker_tokens(text)
    if (
        len(tokens) < 2
        or any(token in _NUMERIC_FACT_MARKER_SCOPE_SPLIT_TOKENS for token in tokens)
    ):
        return
    _append_numeric_fact_marker_phrases(
        markers,
        text,
        include_token_markers=False,
    )


def _append_numeric_fact_marker_phrases(
    markers: list[str],
    value: Any,
    *,
    include_token_markers: bool = True,
) -> None:
    text = _normalized_marker_text(value)
    if not text:
        return
    markers.append(text)
    if not include_token_markers:
        return
    for token in _marker_tokens(text):
        if len(token) <= 2 or token in _NUMERIC_FACT_GENERIC_MARKER_TOKENS:
            continue
        markers.append(token)
        variant = _singular_marker_token(token)
        if variant is not None and variant not in _NUMERIC_FACT_GENERIC_MARKER_TOKENS:
            markers.append(variant)


def _singular_marker_token(token: str) -> str | None:
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return None


def _normalized_marker_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("_", " ").replace("-", " ")
    return text or None


def _marker_tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in re.split(r"[^a-z0-9]+", value.lower()) if token)


def _context_has_conflicting_numeric_value(
    context: str,
    *,
    raw_value: float,
    tolerance: float,
) -> bool:
    for match in _NUMERIC_FACT_VALUE_TOKEN_RE.finditer(context):
        if _numeric_token_is_non_current_value(context, match.start(), match.end()):
            continue
        token = match.group(0).replace("$", "").replace(",", "").replace("%", "")
        try:
            candidate = float(token)
        except ValueError:
            continue
        if abs(candidate - raw_value) > max(tolerance, 1e-9):
            return True
    return False


def _numeric_token_is_non_current_value(context: str, start: int, end: int) -> bool:
    return _numeric_token_is_date_value(
        context,
        start,
        end,
    ) or _numeric_token_is_change_delta_value(
        context,
        start,
        end,
    ) or _numeric_token_is_historical_reference_value(
        context,
        start,
        end,
    ) or _numeric_token_is_qualified_non_current_value(
        context,
        start,
        end,
    ) or _numeric_token_is_comparison_reference_value(context, start)


def _numeric_token_is_date_value(context: str, start: int, end: int) -> bool:
    before = context[start - 1] if start > 0 else ""
    after = context[end] if end < len(context) else ""
    if before in {"-", "/"} or after in {"-", "/"}:
        return True

    token = context[start:end].strip().replace(",", "")
    if not _NUMERIC_FACT_YEAR_RE.fullmatch(token):
        return False

    nearby_before = context[max(0, start - 32) : start]
    nearby_after = context[end : min(len(context), end + 24)]
    return bool(
        _NUMERIC_FACT_MONTH_RE.search(nearby_before)
        or _NUMERIC_FACT_MONTH_RE.search(nearby_after)
        or _NUMERIC_FACT_QUARTER_RE.search(nearby_before)
        or _NUMERIC_FACT_QUARTER_RE.search(nearby_after)
        or _NUMERIC_FACT_DATE_QUALIFIER_RE.search(nearby_before)
    )


def _numeric_token_is_change_delta_value(context: str, start: int, end: int) -> bool:
    before = context[max(0, start - 80) : start]
    if not _NUMERIC_FACT_CHANGE_DELTA_BEFORE_RE.search(before):
        return False
    token = context[start:end].strip()
    if token.endswith("%"):
        return True
    after = context[end : min(len(context), end + 48)]
    return bool(_NUMERIC_FACT_CHANGE_DELTA_UNIT_AFTER_RE.match(after))


def _numeric_token_is_historical_reference_value(
    context: str,
    start: int,
    end: int,
) -> bool:
    return _from_marker_before_token(
        context,
        start,
    ) or _historical_marker_before_token(
        context,
        start,
    ) or _historical_marker_after_token(context, end)


def _numeric_token_is_qualified_non_current_value(
    context: str,
    start: int,
    end: int,
) -> bool:
    return _non_current_marker_before_token(
        context,
        start,
    ) or _non_current_marker_after_token(context, end)


def _numeric_token_is_comparison_reference_value(context: str, start: int) -> bool:
    window = context[max(0, start - 48) : start]
    matches = list(_NUMERIC_FACT_COMPARISON_BRIDGE_RE.finditer(window))
    if not matches:
        return False
    bridge = window[matches[-1].end() :]
    return _NUMERIC_FACT_VALUE_TOKEN_RE.search(bridge) is None


def _from_marker_before_token(context: str, start: int) -> bool:
    window = context[max(0, start - 48) : start]
    return bool(_NUMERIC_FACT_FROM_VALUE_MARKER_RE.search(window))


def _historical_marker_before_token(context: str, start: int) -> bool:
    window = context[max(0, start - 72) : start]
    matches = list(_NUMERIC_FACT_HISTORICAL_VALUE_MARKER_RE.finditer(window))
    if not matches:
        return False
    bridge = window[matches[-1].end() :]
    return (
        _NUMERIC_FACT_VALUE_TOKEN_RE.search(bridge) is None
        and _NUMERIC_FACT_CURRENT_ENDPOINT_BRIDGE_RE.search(bridge) is None
    )


def _historical_marker_after_token(context: str, end: int) -> bool:
    window = context[end : min(len(context), end + 72)]
    match = _NUMERIC_FACT_HISTORICAL_VALUE_MARKER_RE.search(window)
    if match is None:
        return False
    bridge = window[: match.start()]
    return _NUMERIC_FACT_VALUE_TOKEN_RE.search(bridge) is None


def _non_current_marker_before_token(context: str, start: int) -> bool:
    window = context[max(0, start - 48) : start]
    matches = list(_NUMERIC_FACT_NON_CURRENT_VALUE_MARKER_RE.finditer(window))
    if not matches:
        return False
    bridge = window[matches[-1].end() :]
    return _NUMERIC_FACT_VALUE_TOKEN_RE.search(bridge) is None


def _non_current_marker_after_token(context: str, end: int) -> bool:
    window = context[end : min(len(context), end + 48)]
    match = _NUMERIC_FACT_NON_CURRENT_VALUE_MARKER_RE.search(window)
    if match is None:
        return False
    bridge = window[: match.start()]
    return (
        _NUMERIC_FACT_VALUE_TOKEN_RE.search(bridge) is None
        and _NUMERIC_FACT_COMPARISON_BRIDGE_RE.search(bridge) is None
    )


def _compact_context(context: str) -> str:
    compact = " ".join(context.split())
    if len(compact) <= 180:
        return compact
    return compact[:177].rstrip() + "..."


def _non_literal_error(location: str) -> str:
    return (
        f"{location}=false is only valid for inactive "
        "current_state_duration numeric facts"
    )


def _inactive_duration_state_description(unit: str) -> str:
    return _INACTIVE_DURATION_STATE_DESCRIPTION_TEMPLATE.format(unit=unit)


def _validate_current_state_duration_fact(
    number: float,
    unit: str,
    *,
    episode_active: bool,
    location: str,
) -> None:
    if unit not in _DURATION_UNITS:
        raise ValueError(
            f"{location}: current_state_duration unit must be days, weeks, or months"
        )
    if not episode_active and not _is_zero_duration_state(number, unit):
        raise ValueError(
            f"{location}: inactive current_state_duration facts must use 0 {unit}; "
            "use semantic_role=historical_duration for completed historical episodes"
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


def _coerce_optional_bool(
    value: Any,
    *,
    strict: bool,
    location: str,
) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if strict:
        raise ValueError(f"{location} must be a boolean when provided")
    return None
