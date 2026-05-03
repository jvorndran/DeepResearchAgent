"""Scenario-table and recession-regime helper functions."""
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

def _finite_dict(values: dict[str, Any]) -> dict[str, float]:
    cleaned: dict[str, float] = {}
    for key, value in values.items():
        numeric = _finite_float(value)
        if numeric is not None:
            cleaned[str(key)] = numeric
    return cleaned


def _non_empty_strings(value: Any, field: str, scenario: str) -> list[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        raise ValueError(f"{scenario}.{field} must be a non-empty string list")
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        raise ValueError(f"{scenario}.{field} must include at least one non-empty item")
    return cleaned


def _non_empty_text(value: Any, field: str, scenario: str) -> str:
    if isinstance(value, list):
        value = "; ".join(str(item).strip() for item in value if str(item).strip())
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{scenario}.{field} must be non-empty")
    return text


def _normalize_scenario_confidence(raw: dict[str, Any], scenario: str) -> str:
    """Accept common generated confidence shapes without repair loops."""

    value = raw.get("confidence")
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in {"moderate", "moderately confident"}:
            return "medium"
        tokens = {
            token
            for token in cleaned.replace("/", "-").replace("_", "-").split("-")
            if token
        }
        for label in ("low", "medium", "high"):
            if cleaned == label or label in tokens:
                return label

    probability = raw.get("probability")
    if probability is not None:
        if isinstance(probability, str):
            probability = probability.strip().rstrip("%")
        numeric = _finite_float(probability)
        if numeric is not None:
            if numeric > 1:
                numeric = numeric / 100
            if numeric >= 0.6:
                return "high"
            if numeric >= 0.3:
                return "medium"
            if numeric >= 0:
                return "low"

    raise ValueError(f"{scenario}.confidence must be low, medium, or high")


def validate_scenario_table(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Validate and normalize base/bull/bear scenario rows for report handoff.

    This helper performs no data retrieval. Quant scripts should derive the row
    content from local computations, then save the normalized list under the
    top-level ``scenario_table`` key in ``execution_summary.json``.
    """

    if rows is None:
        raise ValueError("scenario_table rows are required")
    normalized_by_name: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("each scenario row must be a JSON object")
        raw_scenario = raw.get("scenario", raw.get("name", ""))
        scenario = SCENARIO_ALIASES.get(
            str(raw_scenario).strip().lower(),
            str(raw_scenario).strip().lower(),
        )
        if scenario not in REQUIRED_SCENARIOS:
            raise ValueError(
                "scenario row must include `scenario` (or legacy `name`) as one "
                "of: base, bull/bear, or natural aliases such as upside/downside"
            )
        if scenario in normalized_by_name:
            raise ValueError(f"duplicate scenario row: {scenario}")
        confidence = _normalize_scenario_confidence(raw, scenario)
        uncertainty_notes = _non_empty_text(
            raw.get("uncertainty_notes"), "uncertainty_notes", scenario
        )
        normalized_by_name[scenario] = {
            "scenario": scenario,
            "assumptions": _non_empty_strings(raw.get("assumptions"), "assumptions", scenario),
            "indicator_triggers": _non_empty_strings(
                raw.get("indicator_triggers"), "indicator_triggers", scenario
            ),
            "confidence": confidence,
            "uncertainty_notes": uncertainty_notes,
        }

    missing = [scenario for scenario in REQUIRED_SCENARIOS if scenario not in normalized_by_name]
    if missing:
        raise ValueError(f"scenario_table missing required row(s): {', '.join(missing)}")
    return [normalized_by_name[scenario] for scenario in REQUIRED_SCENARIOS]


def _summarize_latest_frame_row(data: pd.DataFrame) -> tuple[str | None, list[str]]:
    """Extract compact, JSON-safe signal labels from a local analysis panel."""

    if data.empty:
        return None, []
    frame = data.copy()
    latest = frame.iloc[-1]
    latest_date = _iso_date(latest.get("date")) if "date" in frame.columns else None
    signals: list[str] = []
    for column in frame.columns:
        if column == "date":
            continue
        value = _finite_float(latest.get(column))
        if value is None:
            continue
        signals.append(f"{column}={value:.3g}")
        if len(signals) >= 5:
            break
    return latest_date, signals


def _default_scenario_rows_from_panel(data: pd.DataFrame) -> list[dict[str, Any]]:
    latest_date, signals = _summarize_latest_frame_row(data)
    signal_text = ", ".join(signals) if signals else "latest available local indicators"
    as_of = f" as of {latest_date}" if latest_date else ""
    return [
        {
            "scenario": "base",
            "assumptions": [
                f"Mixed macro conditions persist{as_of}; use {signal_text} as the baseline signal set.",
            ],
            "indicator_triggers": [
                "Labor, inflation, credit, production, and consumption signals remain directionally mixed rather than jointly recessionary.",
            ],
            "confidence": "medium",
            "uncertainty_notes": "Base case is a deterministic stress row derived from the local analysis panel, not a probability estimate.",
        },
        {
            "scenario": "bull",
            "assumptions": [
                "Inflation cools while employment and production stay resilient.",
            ],
            "indicator_triggers": [
                "Claims and unemployment remain contained, real activity improves, and credit stress does not broaden.",
            ],
            "confidence": "low",
            "uncertainty_notes": "Upside requires policy lags and data revisions not to reveal delayed demand weakness.",
        },
        {
            "scenario": "bear",
            "assumptions": [
                "Policy, credit, and consumer stress reinforce a downturn path.",
            ],
            "indicator_triggers": [
                "Unemployment or claims rise, production/consumption weaken, and credit stress confirms the slowdown.",
            ],
            "confidence": "medium",
            "uncertainty_notes": "Downside timing is uncertain because macro data are revised and released with different lags.",
        },
    ]


def build_scenario_stress_test(
    rows: Iterable[dict[str, Any]] | pd.DataFrame,
    *legacy_args: Any,
    topic: str = "macro_risk",
    **legacy_kwargs: Any,
) -> dict[str, Any]:
    """Return a JSON-safe scenario stress-test payload for execution_summary.json.

    ``rows`` is normally the canonical list of base/bull/bear scenario dicts.
    Generated quant scripts sometimes pass their local analysis panel plus
    forecast/model keyword arguments. Treat that legacy shape as a request to
    create a compact deterministic scenario table from the latest panel row
    instead of raising a signature error and entering a repair loop.
    """

    if legacy_args:
        first_arg = legacy_args[0]
        if isinstance(first_arg, str) and topic == "macro_risk":
            topic = first_arg
        elif isinstance(first_arg, (list, tuple)) and isinstance(rows, pd.DataFrame):
            rows = first_arg

    cleaned_topic = str(topic or "macro_risk").strip() or "macro_risk"
    scenario_rows: Iterable[dict[str, Any]]
    if isinstance(rows, pd.DataFrame):
        scenario_rows = _default_scenario_rows_from_panel(rows)
    else:
        scenario_rows = rows
    limitations = [
        "Scenario rows are deterministic stress cases, not probabilities or guaranteed forecasts.",
        "Indicator triggers should be revisited when input data revisions or new releases arrive.",
    ]
    if legacy_args or legacy_kwargs:
        limitations.append(
            "Legacy scenario helper arguments were ignored; scenario rows were normalized from the provided local analysis inputs."
        )
    return {
        "topic": cleaned_topic,
        "scenario_table": validate_scenario_table(scenario_rows),
        "methods_used": [METHOD_SCENARIO_STRESS_TEST],
        "limitations": limitations,
    }


def _score_indicator_value(
    value: Any,
    *,
    favorable_when: str = "high",
    weak_threshold: float = -0.5,
    strong_threshold: float = 0.5,
) -> float | None:
    numeric = _finite_float(value)
    if numeric is None:
        return None
    if favorable_when not in {"high", "low"}:
        raise ValueError("indicator favorable_when must be 'high' or 'low'")
    weak = _finite_float(weak_threshold)
    strong = _finite_float(strong_threshold)
    if weak is None or strong is None or weak == strong:
        raise ValueError(
            "indicator thresholds must be finite and weak_threshold < strong_threshold"
        )
    if weak > strong:
        weak, strong = strong, weak

    if numeric <= weak:
        score = -1.0
    elif numeric >= strong:
        score = 1.0
    else:
        midpoint = (weak + strong) / 2
        half_range = (strong - weak) / 2
        score = (numeric - midpoint) / half_range
    if favorable_when == "low":
        score *= -1
    return float(np.clip(score, -1.0, 1.0))


def _category_scores_from_row(
    row: pd.Series,
    indicator_specs: Iterable[dict[str, Any]],
) -> tuple[dict[str, float], list[dict[str, Any]], list[dict[str, str]]]:
    grouped: dict[str, list[tuple[float, float]]] = {}
    evidence: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for raw_spec in indicator_specs:
        spec = dict(raw_spec)
        name = str(spec.get("name") or spec.get("column") or "").strip()
        column = str(spec.get("column") or name).strip()
        category = str(spec.get("category") or name).strip().lower()
        if not name or not column or not category:
            raise ValueError("each indicator spec requires name, column, and category")
        if column not in row.index:
            missing.append({"indicator": name, "category": category, "reason": "missing_column"})
            continue
        raw_value = row[column]
        raw_score = _score_indicator_value(
            raw_value,
            favorable_when=str(spec.get("favorable_when", "high")),
            weak_threshold=float(spec.get("weak_threshold", -0.5)),
            strong_threshold=float(spec.get("strong_threshold", 0.5)),
        )
        if raw_score is None:
            missing.append({"indicator": name, "category": category, "reason": "missing_value"})
            continue
        indicator_weight = float(spec.get("indicator_weight", 1.0))
        if not np.isfinite(indicator_weight) or indicator_weight <= 0:
            raise ValueError("indicator_weight must be a positive finite number")
        grouped.setdefault(category, []).append((raw_score, indicator_weight))
        evidence.append(
            {
                "indicator": name,
                "category": category,
                "value": _finite_float(raw_value),
                "score": _finite_float(raw_score),
                "weight": _finite_float(indicator_weight),
                "signal": "supportive"
                if raw_score >= 0.25
                else "weak"
                if raw_score <= -0.25
                else "neutral",
                "rationale": str(spec.get("rationale", "")).strip()
                or "Positive score supports expansion; negative score points to slowdown or recession risk.",
            }
        )

    category_scores: dict[str, float] = {}
    for category, values in grouped.items():
        weight_sum = sum(weight for _, weight in values)
        if weight_sum > 0:
            category_scores[category] = sum(score * weight for score, weight in values) / weight_sum
    return category_scores, evidence, missing


def _weighted_regime_score(
    category_scores: dict[str, float],
    category_weights: dict[str, float],
) -> tuple[float | None, dict[str, float]]:
    usable_weights = {
        category: float(category_weights.get(category, 0.0))
        for category in category_scores
        if np.isfinite(float(category_weights.get(category, 0.0)))
        and float(category_weights.get(category, 0.0)) > 0
    }
    total = sum(usable_weights.values())
    if total <= 0:
        return None, {}
    normalized = {category: weight / total for category, weight in usable_weights.items()}
    score = sum(category_scores[category] * weight for category, weight in normalized.items())
    return _finite_float(score), normalized


def _classify_regime_label(
    score: float,
    momentum: float | None,
    *,
    recession_flag: bool,
    weak_categories: int,
) -> str:
    if recession_flag or (score <= -0.45 and weak_categories >= 3):
        return "recession"
    if momentum is not None and momentum >= 0.25 and score < 0.35:
        return "recovery"
    if score >= 0.25 and momentum is not None and momentum >= 0.20:
        return "reacceleration"
    if score <= 0.20 and ((momentum is not None and momentum <= -0.15) or weak_categories >= 2):
        return "slowdown"
    return "expansion"


def _historical_analogs(
    scored: pd.DataFrame,
    *,
    date_col: str,
    category_columns: list[str],
    latest_index: int,
    limit: int,
) -> list[dict[str, Any]]:
    if latest_index <= 0 or not category_columns:
        return []
    latest_vector = scored.loc[latest_index, category_columns].to_numpy(dtype=float)
    analogs: list[dict[str, Any]] = []
    for index, row in scored.iloc[:latest_index].iterrows():
        candidate = row[category_columns].to_numpy(dtype=float)
        if np.isnan(candidate).any() or np.isnan(latest_vector).any():
            continue
        distance = float(np.linalg.norm(candidate - latest_vector))
        analogs.append(
            {
                "date": _iso_date(row[date_col]),
                "distance": _finite_float(distance),
                "regime_score": _finite_float(row["_regime_score"]),
                "label": row.get("_regime_label"),
            }
        )
    return sorted(
        analogs, key=lambda item: item["distance"] if item["distance"] is not None else np.inf
    )[:limit]


def classify_recession_regime(
    data: pd.DataFrame,
    *,
    date_col: str = "date",
    indicator_specs: Iterable[dict[str, Any]] | None = None,
    category_weights: dict[str, float] | None = None,
    recession_col: str | None = None,
    momentum_periods: int = 3,
    min_categories: int = 3,
    analog_count: int = 3,
) -> dict[str, Any]:
    """
    Classify the latest macro regime with transparent local scoring.

    Inputs should be local, already-fetched observations. By default the helper
    treats columns named rates, labor, inflation, credit, and output as
    pre-scored category signals where +1 supports expansion and -1 signals
    contraction/stress. Custom ``indicator_specs`` can score raw columns with
    explicit weak/strong thresholds and high/low favorable direction.
    """

    if data is None or data.empty:
        raise ValueError("data must include at least one local observation")
    if momentum_periods < 1:
        raise ValueError("momentum_periods must be at least 1")
    if min_categories < 1:
        raise ValueError("min_categories must be at least 1")
    if analog_count < 0:
        raise ValueError("analog_count must be non-negative")

    weights = {**DEFAULT_REGIME_WEIGHTS, **(category_weights or {})}
    if indicator_specs is None:
        specs = [
            {
                "name": category,
                "column": category,
                "category": category,
                "weak_threshold": -0.5,
                "strong_threshold": 0.5,
                "favorable_when": "high",
            }
            for category in DEFAULT_REGIME_CATEGORIES
        ]
    else:
        specs = list(indicator_specs)
        if not specs:
            raise ValueError("indicator_specs must include at least one indicator when provided")

    frame = data.copy()
    _require_columns(frame, [date_col])
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame = frame.dropna(subset=[date_col]).sort_values(date_col).reset_index(drop=True)
    if frame.empty:
        raise ValueError("data has no usable dates after cleaning")

    scored_rows: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    for row_index, row in frame.iterrows():
        category_scores, evidence, missing = _category_scores_from_row(row, specs)
        score, normalized_weights = _weighted_regime_score(category_scores, weights)
        if score is None or len(category_scores) < min_categories:
            payload = {
                "date": _iso_date(row[date_col]),
                "status": "insufficient_categories",
                "regime_label": "unclassified",
                "regime_score": score,
                "available_categories": sorted(category_scores),
                "missing_indicators": missing,
                "evidence_table": evidence,
            }
        else:
            prior_position = row_index - momentum_periods
            prior_score = (
                scored_rows[prior_position]["_regime_score"]
                if prior_position >= 0
                and scored_rows[prior_position].get("_regime_score") is not None
                else None
            )
            momentum = _finite_float(score - prior_score) if prior_score is not None else None
            recession_value = (
                _finite_float(row[recession_col]) if recession_col in row.index else None
            )
            recession_flag = bool(
                recession_col and recession_value is not None and recession_value > 0
            )
            weak_categories = sum(1 for value in category_scores.values() if value <= -0.25)
            label = _classify_regime_label(
                score,
                momentum,
                recession_flag=recession_flag,
                weak_categories=weak_categories,
            )
            payload = {
                "date": _iso_date(row[date_col]),
                "status": "ok",
                "regime_label": label,
                "regime_score": score,
                "score_momentum": momentum,
                "category_scores": {
                    key: _finite_float(value) for key, value in category_scores.items()
                },
                "category_weights": normalized_weights,
                "weak_categories": weak_categories,
                "recession_indicator": recession_col if recession_col else None,
                "recession_indicator_active": recession_flag if recession_col else None,
                "available_categories": sorted(category_scores),
                "missing_indicators": missing,
                "evidence_table": evidence,
            }

        scored_row = {
            date_col: row[date_col],
            "_regime_score": payload["regime_score"],
            "_regime_label": payload["regime_label"],
            **{f"_category_{key}": value for key, value in category_scores.items()},
        }
        scored_rows.append(scored_row)
        payloads.append(payload)

    assert payloads  # for type checkers
    selected_index = len(payloads) - 1
    latest_payload = payloads[selected_index]
    for index in range(len(payloads) - 1, -1, -1):
        if payloads[index]["status"] == "ok":
            selected_index = index
            latest_payload = payloads[index]
            break
    scored = pd.DataFrame(scored_rows)
    category_columns = [
        column
        for column in scored.columns
        if column.startswith("_category_") and pd.notna(scored[column].iloc[selected_index])
    ]
    analogs = (
        _historical_analogs(
            scored,
            date_col=date_col,
            category_columns=category_columns,
            latest_index=selected_index,
            limit=analog_count,
        )
        if latest_payload["status"] == "ok"
        else []
    )

    return {
        **latest_payload,
        "historical_analogs": analogs,
        "methods_used": [METHOD_RECESSION_REGIME_CLASSIFIER],
        "false_positive_caveat": (
            "Regime classification is a transparent deterministic score, not a black-box model "
            "or recession call. False positives can occur when noisy, revised, or lagging macro "
            "series briefly resemble prior downturns."
        ),
        "fallback_behavior": (
            f"Returns status='insufficient_categories' unless at least {min_categories} "
            "categories have usable local observations. When trailing partial rows from "
            "mixed-frequency data are insufficient, the latest usable row is classified "
            "instead of letting a high-frequency-only period erase the regime."
        ),
    }
