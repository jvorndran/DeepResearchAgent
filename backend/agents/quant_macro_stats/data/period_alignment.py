"""Period alignment and composite predictive indicator helpers."""

from typing import Any, Iterable

import numpy as np
import pandas as pd

from .._utils import (
    METHOD_COMPOSITE_PREDICTIVE_INDICATOR,
    _as_ordered_frame,
    _direction_multiplier,
    _finite_float,
    _iso_date,
    _require_columns,
)


def align_period_features(
    series_frames: dict[str, pd.DataFrame],
    *,
    date_col: str = "date",
    value_col: str = "value",
    frequency: str = "M",
    aggregation: str = "mean",
    how: str = "outer",
    timestamp_position: str = "start",
    fill_method: str | None = None,
    fill_limit: int | None = None,
    max_date: str | pd.Timestamp | None = "today",
) -> pd.DataFrame:
    """
    Align local single-series frames by period key before merging.

    This is intended for data-engineer handoffs where daily rates, monthly
    macro series, and quarterly output series need a deterministic common
    frequency. It performs no network calls. By default it never imputes
    missing values; pass ``fill_method="ffill"`` with a small ``fill_limit``
    when quarterly series such as GDP should be carried into a monthly panel
    without creating hand-rolled Cartesian joins.
    The output date defaults to the period start because FRED monthly and
    quarterly observations are commonly stamped at the first day of the period;
    pass ``timestamp_position="end"`` when chart labels should use period-end
    dates instead.

    By default, observations dated after today are dropped before alignment.
    This prevents forward-looking projection series, such as FRED natural-rate
    estimates, from extending a "current" mixed-frequency panel into future
    periods and forward-filling stale current indicators. Pass ``max_date=None``
    only for explicit projection/forecast analyses.
    """

    if not series_frames:
        raise ValueError("series_frames must include at least one named series")
    if frequency not in {"M", "Q"}:
        raise ValueError("frequency must be 'M' for monthly or 'Q' for quarterly")
    if aggregation not in {"mean", "last", "first", "sum"}:
        raise ValueError("aggregation must be one of: mean, last, first, sum")
    if how not in {"outer", "inner", "left", "right"}:
        raise ValueError("how must be one of: outer, inner, left, right")
    if timestamp_position not in {"start", "end"}:
        raise ValueError("timestamp_position must be 'start' or 'end'")
    if fill_method not in {None, "ffill"}:
        raise ValueError("fill_method must be None or 'ffill'")
    if fill_limit is not None and fill_limit < 0:
        raise ValueError("fill_limit must be non-negative")
    if max_date == "today":
        max_timestamp = pd.Timestamp.today().normalize()
    elif max_date is None:
        max_timestamp = None
    else:
        max_timestamp = pd.Timestamp(max_date).normalize()

    period_col = "month" if frequency == "M" else "quarter"
    aligned_frames: list[pd.DataFrame] = []
    for name, raw in series_frames.items():
        if raw is None or raw.empty:
            raise ValueError(
                f"Series '{name}' is empty; provide local observations before alignment"
            )
        _require_columns(raw, [date_col])
        frame = raw.copy()
        frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
        if max_timestamp is not None:
            frame = frame[frame[date_col] <= max_timestamp]
        candidate_value_col = value_col
        if candidate_value_col not in frame.columns:
            non_date_cols = [column for column in frame.columns if column != date_col]
            if len(non_date_cols) != 1:
                raise ValueError(
                    f"Series '{name}' must include '{value_col}' or exactly one non-date value column"
                )
            candidate_value_col = non_date_cols[0]
        frame[name] = pd.to_numeric(frame[candidate_value_col], errors="coerce")
        frame = frame.dropna(subset=[date_col, name])
        if frame.empty:
            raise ValueError(f"Series '{name}' has no usable numeric observations after cleaning")
        frame[period_col] = frame[date_col].dt.to_period(frequency)
        grouped = getattr(frame.groupby(period_col)[name], aggregation)().reset_index()
        aligned_frames.append(grouped)

    merged = aligned_frames[0]
    for frame in aligned_frames[1:]:
        merged = merged.merge(frame, on=period_col, how=how)
    merged = merged.sort_values(period_col).reset_index(drop=True)
    if fill_method == "ffill":
        value_columns = [name for name in series_frames if name in merged.columns]
        merged[value_columns] = merged[value_columns].ffill(limit=fill_limit)
    timestamp_how = "start" if timestamp_position == "start" else "end"
    merged[date_col] = merged[period_col].dt.to_timestamp(how=timestamp_how).dt.normalize()
    columns = [date_col, *series_frames.keys()]
    return merged[columns]


def _transform_feature(series: pd.Series, transform: str) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if transform in {"level", "none"}:
        return values
    if transform in {"diff", "change"}:
        return values.diff()
    if transform == "pct_change":
        return values.pct_change() * 100
    if transform == "yoy":
        return values.pct_change(12) * 100
    raise ValueError(
        f"Unsupported feature transform '{transform}'. Use level, diff, pct_change, or yoy."
    )


def _rank_against_train(values: pd.Series, train_values: pd.Series) -> pd.Series:
    reference = train_values.dropna().sort_values().to_numpy(dtype=float)
    if len(reference) == 0:
        return pd.Series(np.nan, index=values.index)
    ranks = [
        np.searchsorted(reference, value, side="right") / len(reference)
        if pd.notna(value)
        else np.nan
        for value in values
    ]
    return pd.Series(ranks, index=values.index, dtype=float)


def _classify_threshold(value: float | None, thresholds: dict[str, Any]) -> str | None:
    numeric = _finite_float(value)
    low = _finite_float(thresholds.get("low"))
    high = _finite_float(thresholds.get("high"))
    if numeric is None or low is None or high is None:
        return None
    if numeric < low:
        return "low"
    if numeric >= high:
        return "high"
    return "medium"


def build_composite_predictive_indicator(
    data: pd.DataFrame,
    *,
    target_col: str,
    feature_cols: Iterable[str],
    date_col: str = "date",
    target: str = "recession_risk",
    prediction_horizon: int = 6,
    feature_transforms: dict[str, str] | None = None,
    feature_lags: dict[str, int] | None = None,
    feature_directions: dict[str, int | float] | None = None,
    normalization_method: str = "zscore",
    weights: dict[str, float] | None = None,
    train_fraction: float = 0.7,
    target_event_threshold: float = 0.5,
    min_observations: int = 12,
    min_feature_coverage: int | None = None,
) -> dict[str, Any]:
    """
    Build a transparent local composite predictive indicator.

    Positive ``prediction_horizon`` means features at period t are scored
    against target(t+h). Positive feature lags use older predictor values at t
    and therefore avoid lookahead.
    """

    features = list(dict.fromkeys(feature_cols))
    if not features:
        raise ValueError("feature_cols must include at least one feature")
    if prediction_horizon < 1:
        raise ValueError("prediction_horizon must be at least 1")
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1")
    if normalization_method not in {"zscore", "rank"}:
        raise ValueError("normalization_method must be 'zscore' or 'rank'")

    transforms = {feature: "level" for feature in features}
    transforms.update(feature_transforms or {})
    lags = {feature: int((feature_lags or {}).get(feature, 0)) for feature in features}
    if any(lag < 0 for lag in lags.values()):
        raise ValueError("feature_lags must be non-negative to avoid lookahead")
    directions = {
        feature: _direction_multiplier((feature_directions or {}).get(feature, 1.0))
        for feature in features
    }

    frame = _as_ordered_frame(data, date_col, [target_col, *features])
    working = frame[[date_col, target_col]].copy()
    usable_features: list[str] = []
    dropped_features: list[dict[str, str]] = []
    transform_summary: dict[str, dict[str, Any]] = {}
    for feature in features:
        transformed = _transform_feature(frame[feature], transforms[feature])
        lagged = transformed.shift(lags[feature])
        out_col = f"{feature}__signal"
        working[out_col] = lagged
        if lagged.notna().sum() == 0:
            dropped_features.append(
                {"feature": feature, "reason": "all_missing_after_transform_or_lag"}
            )
            continue
        usable_features.append(feature)
        transform_summary[feature] = {
            "transform": transforms[feature],
            "lag_periods": lags[feature],
            "direction": directions[feature],
        }

    if not usable_features:
        raise ValueError("No usable features remained after transforms and lags")

    working["_target_future"] = working[target_col].shift(-prediction_horizon)
    signal_cols = [f"{feature}__signal" for feature in usable_features]
    train_cutoff = max(int(len(working) * train_fraction), 1)
    train = working.iloc[:train_cutoff]
    if min_feature_coverage is None:
        required_feature_count = max(1, int(np.ceil(len(usable_features) / 2)))
    else:
        required_feature_count = int(min_feature_coverage)
    if required_feature_count < 1:
        raise ValueError("min_feature_coverage must be at least 1")
    if required_feature_count > len(usable_features):
        raise ValueError("min_feature_coverage cannot exceed the number of usable features")
    train_coverage = train[signal_cols].notna().sum(axis=1)
    if int((train_coverage >= required_feature_count).sum()) < min_observations:
        raise ValueError(
            "Not enough training observations meeting feature coverage for composite "
            f"predictive indicator: need at least {min_observations}; require "
            f"{required_feature_count} of {len(usable_features)} usable features per training row"
        )

    normalized = working[[date_col, target_col, "_target_future", *signal_cols]].copy()
    normalization_stats: dict[str, dict[str, float | None]] = {}
    for feature, signal_col in zip(usable_features, signal_cols, strict=False):
        train_values = train[signal_col].dropna()
        norm_col = f"{feature}__normalized"
        if normalization_method == "zscore":
            if len(train_values) < 2:
                dropped_features.append(
                    {"feature": feature, "reason": "insufficient_training_signal"}
                )
                normalized[norm_col] = np.nan
                continue
            mean = float(train_values.mean())
            std = float(train_values.std(ddof=0))
            if not np.isfinite(std) or std == 0:
                dropped_features.append({"feature": feature, "reason": "constant_training_signal"})
                normalized[norm_col] = np.nan
                continue
            normalized[norm_col] = (normalized[signal_col] - mean) / std
            normalization_stats[feature] = {"mean": _finite_float(mean), "std": _finite_float(std)}
        else:
            if len(train_values) == 0:
                dropped_features.append(
                    {"feature": feature, "reason": "insufficient_training_signal"}
                )
                normalized[norm_col] = np.nan
                continue
            normalized[norm_col] = _rank_against_train(normalized[signal_col], train_values)
            normalization_stats[feature] = {
                "train_min": _finite_float(train_values.min()),
                "train_max": _finite_float(train_values.max()),
            }

    normalized_features = [
        feature for feature in usable_features if normalized[f"{feature}__normalized"].notna().any()
    ]
    if not normalized_features:
        raise ValueError("No usable features remained after normalization")
    if required_feature_count > len(normalized_features):
        required_feature_count = len(normalized_features)

    if weights is None:
        base_weight = 1.0 / len(normalized_features)
        clean_weights = {
            feature: base_weight * directions.get(feature, 1.0) for feature in normalized_features
        }
        weight_method = "equal_weight_directional"
    else:
        clean_weights = {
            feature: numeric
            for feature in normalized_features
            if (numeric := _finite_float(weights.get(feature, 0.0))) is not None
        }
        total_abs = sum(abs(value) for value in clean_weights.values())
        if total_abs == 0:
            raise ValueError("weights must include at least one non-zero finite feature weight")
        clean_weights = {feature: value / total_abs for feature, value in clean_weights.items()}
        weight_method = "user_supplied_normalized_abs_sum"

    score = pd.Series(0.0, index=normalized.index)
    active_weight_abs = pd.Series(0.0, index=normalized.index)
    active_feature_count = pd.Series(0, index=normalized.index, dtype=int)
    for feature, weight in clean_weights.items():
        norm_col = f"{feature}__normalized"
        present = normalized[norm_col].notna()
        active_feature_count = active_feature_count + present.astype(int)
        active_weight_abs = active_weight_abs + present.astype(float) * abs(weight)
        score = score + normalized[norm_col].fillna(0) * weight
    coverage_mask = (active_feature_count >= required_feature_count) & (active_weight_abs > 0)
    normalized["feature_count_used"] = active_feature_count
    normalized["composite_index"] = (score / active_weight_abs).where(coverage_mask)
    normalized["_target_event"] = normalized["_target_future"] >= target_event_threshold

    train_scores = normalized["composite_index"].iloc[:train_cutoff].dropna()
    if len(train_scores) < min_observations:
        raise ValueError(
            "Not enough normalized training observations meeting feature coverage for thresholds: "
            f"need at least {min_observations}; require {required_feature_count} of "
            f"{len(normalized_features)} features per scored row"
        )
    thresholds = {
        "low": _finite_float(train_scores.quantile(1 / 3)),
        "high": _finite_float(train_scores.quantile(2 / 3)),
        "classification": "low below lower tercile, medium between terciles, high at or above upper tercile",
    }

    latest_row = normalized.dropna(subset=["composite_index"]).tail(1)
    current_row: dict[str, Any] | None = None
    if not latest_row.empty:
        latest = latest_row.iloc[0]
        current_index_value = _finite_float(latest["composite_index"])
        current_row = {
            "date": _iso_date(latest[date_col]),
            "target": target,
            "target_variable": target_col,
            "prediction_horizon": prediction_horizon,
            "composite_index": current_index_value,
            "composite_percentile_0_100": None,
            "classification": _classify_threshold(current_index_value, thresholds),
            "target_value": _finite_float(latest[target_col]),
            "target_future": _finite_float(latest["_target_future"]),
            "target_event": bool(latest["_target_event"]),
            "feature_count_used": int(latest["feature_count_used"]),
            "feature_values": {
                feature: _finite_float(latest[f"{feature}__signal"])
                for feature in normalized_features
            },
        }

    composite_score_rows: list[dict[str, Any]] = []
    train_score_values = np.sort(train_scores.to_numpy(dtype=float))
    for _, row in normalized.dropna(subset=["composite_index"]).iterrows():
        index_value = _finite_float(row["composite_index"])
        percentile = (
            _finite_float(
                100.0
                * np.searchsorted(train_score_values, row["composite_index"], side="right")
                / len(train_score_values)
            )
            if index_value is not None and len(train_score_values)
            else None
        )
        score_row = {
            "date": _iso_date(row[date_col]),
            "composite_index": index_value,
            "composite_percentile_0_100": percentile,
            "target_value": _finite_float(row[target_col]),
            "target_future": _finite_float(row["_target_future"]),
            "target_event": bool(row["_target_event"]),
            "feature_count_used": int(row["feature_count_used"]),
            "classification": _classify_threshold(index_value, thresholds),
        }
        composite_score_rows.append(score_row)
        if current_row is not None and score_row["date"] == current_row["date"]:
            current_row["composite_percentile_0_100"] = percentile

    if current_row is None and composite_score_rows:
        current_row = {
            **composite_score_rows[-1],
            "target": target,
            "target_variable": target_col,
            "prediction_horizon": prediction_horizon,
            "feature_values": {},
        }

    validation_design = {
        "method": METHOD_COMPOSITE_PREDICTIVE_INDICATOR,
        "target": target,
        "target_variable": target_col,
        "target_event_threshold": target_event_threshold,
        "prediction_horizon": prediction_horizon,
        "train_fraction": train_fraction,
        "train_window": {
            "start": _iso_date(train[date_col].iloc[0]) if not train.empty else None,
            "end": _iso_date(train[date_col].iloc[-1]) if not train.empty else None,
        },
        "normalization_method": normalization_method,
        "weight_method": weight_method,
        "minimum_features_per_scored_row": required_feature_count,
        "classification_rule": thresholds["classification"],
    }

    test = (
        normalized.iloc[train_cutoff:].dropna(subset=["composite_index", "_target_future"]).copy()
    )
    if test.empty:
        validation_metrics = {
            "status": "insufficient_test_observations",
            "test_observations": 0,
            "test_window": None,
            "metrics": {},
        }
    else:
        test["_predicted_event"] = test["composite_index"] >= thresholds["high"]
        actual = test["_target_event"].astype(bool)
        predicted = test["_predicted_event"].astype(bool)
        tp = int((actual & predicted).sum())
        fp = int((~actual & predicted).sum())
        tn = int((~actual & ~predicted).sum())
        fn = int((actual & ~predicted).sum())
        observations = int(len(test))
        validation_metrics = {
            "status": "ok",
            "test_observations": observations,
            "test_window": {
                "start": _iso_date(test[date_col].iloc[0]),
                "end": _iso_date(test[date_col].iloc[-1]),
            },
            "metrics": {
                "accuracy": _finite_float((tp + tn) / observations if observations else None),
                "precision": _finite_float(tp / (tp + fp) if tp + fp else None),
                "recall": _finite_float(tp / (tp + fn) if tp + fn else None),
                "true_positive": tp,
                "false_positive": fp,
                "true_negative": tn,
                "false_negative": fn,
            },
        }

    return {
        "composite_current_row": current_row,
        "composite_score_rows": composite_score_rows,
        "composite_validation_metrics": validation_metrics,
        "composite_validation_design": validation_design,
        "target": target,
        "target_variable": target_col,
        "prediction_horizon": prediction_horizon,
        "input_features": normalized_features,
        "dropped_features": dropped_features,
        "feature_transforms": transform_summary,
        "normalization_method": normalization_method,
        "normalization_stats": normalization_stats,
        "weights_or_model": {
            "type": "transparent_weighted_score",
            "weight_method": weight_method,
            "weights": clean_weights,
        },
        "feature_coverage": {
            "minimum_features_per_scored_row": required_feature_count,
            "available_features": len(normalized_features),
            "scored_observations": int(normalized["composite_index"].notna().sum()),
            "full_feature_observations": int(
                (normalized["feature_count_used"] == len(normalized_features)).sum()
            ),
        },
        "thresholds": thresholds,
        "methods_used": [METHOD_COMPOSITE_PREDICTIVE_INDICATOR],
        "limitations": [
            "This is a predictive indicator, not a guaranteed forecast.",
            "Training-set normalization and thresholds reduce lookahead but remain sensitive to revisions and sample choice.",
            "Binary validation metrics depend on the selected target event threshold and prediction horizon.",
        ],
    }
