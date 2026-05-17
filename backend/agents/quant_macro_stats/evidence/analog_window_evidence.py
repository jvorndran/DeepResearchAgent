"""Shared analog-window evidence helpers for quant scripts."""

from __future__ import annotations

import math
from typing import Any, Iterable

import pandas as pd

from .._utils import window_coverage


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: Any, digits: int = 4) -> float | None:
    number = _finite(value)
    return None if number is None else round(number, digits)


def _explicit_analog_windows(windows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate caller-selected analog windows without inventing defaults."""

    raw_windows = list(windows or [])
    if not raw_windows:
        raise ValueError("analog_windows must include at least one explicit window")
    windows: list[dict[str, Any]] = []
    seen_labels: set[str] = set()

    for raw in raw_windows:
        if not isinstance(raw, dict):
            continue
        window = dict(raw)
        label = str(window.get("label") or window.get("name") or "").strip()
        if not label or label in seen_labels:
            continue
        if not window.get("start") or not window.get("end"):
            raise ValueError("each analog window must include label, start, and end")
        pd.Timestamp(window["start"])
        pd.Timestamp(window["end"])
        window["label"] = label
        windows.append(window)
        seen_labels.add(label)

    if not windows:
        raise ValueError("analog_windows must include at least one valid window")
    return windows


def _window_coverage_rows(
    panel: pd.DataFrame,
    analog_windows: Iterable[dict[str, Any]],
    coverage_cols: list[str],
    *,
    min_required_cap: int,
    min_coverage: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in analog_windows:
        row = window_coverage(
            panel,
            window,
            coverage_cols,
            min_required_cap=min_required_cap,
            min_coverage=min_coverage,
        )
        for key in ("requested", "requested_years", "window_source"):
            if key in window:
                row[key] = window[key]
        rows.append(row)
    return rows


def normalize_analog_ranking(
    ranking: Iterable[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in ranking or []:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("analog") or raw.get("label") or raw.get("name") or "").strip()
        if not label:
            continue
        raw_distance = _finite(
            raw.get("raw_distance", raw.get("distance_score", raw.get("distance")))
        )
        normalized_similarity = _finite(
            raw.get("normalized_similarity", raw.get("similarity_score"))
        )
        if normalized_similarity is None and raw_distance is not None:
            normalized_similarity = 100.0 / (1.0 + max(raw_distance, 0.0))
        status = str(raw.get("status") or "covered")
        row = dict(raw)
        row["analog"] = label
        row["label"] = label
        row["status"] = status
        row["included"] = status.lower() in {
            "ok",
            "covered",
            "descriptive_replay",
            "included",
        }
        row["raw_distance"] = _round(raw_distance)
        row["distance_score"] = _round(raw_distance, 3)
        row["normalized_similarity"] = _round(normalized_similarity, 3)
        if "top_divergences" in row and "divergence_facts" not in row:
            row["divergence_facts"] = row["top_divergences"]
        rows.append(row)

    rows.sort(
        key=lambda row: (
            not bool(row.get("included")),
            float(row["raw_distance"])
            if row.get("raw_distance") is not None
            else -float(row["normalized_similarity"])
            if row.get("normalized_similarity") is not None
            else math.inf,
            str(row.get("label") or ""),
        )
    )
    return rows


def _metric_specs(
    value_cols: Iterable[str],
    profile_metrics: Iterable[tuple[str, str]] | None,
) -> list[tuple[str, str]]:
    if profile_metrics is None:
        return [(str(column), str(column)) for column in value_cols if str(column)]
    return [
        (str(label), str(column))
        for label, column in profile_metrics
        if str(label) and str(column)
    ]


def _project_profile(
    profile: dict[str, Any],
    metrics: Iterable[tuple[str, str]],
    *,
    default: float | None = 50.0,
) -> dict[str, float | None]:
    row: dict[str, float | None] = {}
    for label, column in metrics:
        value = _round(profile.get(column), 2)
        row[label] = default if value is None else value
    return row


def analog_window_profile(
    panel: pd.DataFrame,
    start: Any,
    end: Any,
    profile_metrics: Iterable[tuple[str, str]],
    *,
    date_col: str = "date",
    default: float | None = 50.0,
) -> dict[str, float | None]:
    """Return labeled window-average profile values for analog replay charts."""

    metrics = list(profile_metrics)
    rows = panel.loc[
        (panel[date_col] >= pd.Timestamp(start)) & (panel[date_col] <= pd.Timestamp(end))
    ]
    profile: dict[str, Any] = {}
    for _, column in metrics:
        if column not in rows:
            profile[column] = default
            continue
        values = pd.to_numeric(rows[column], errors="coerce").dropna()
        profile[column] = default if values.empty else float(values.mean())
    return _project_profile(profile, metrics, default=default)


def _analog_profile_rows(
    *,
    ranking: Iterable[dict[str, Any]],
    analog_profiles: dict[str, dict[str, Any]],
    current_profile: dict[str, Any],
    analog_windows: Iterable[dict[str, Any]],
    metrics: Iterable[tuple[str, str]],
) -> list[dict[str, Any]]:
    metric_list = list(metrics)
    current = _project_profile(current_profile, metric_list)
    windows_by_label = {
        str(window.get("label")): window
        for window in analog_windows
        if isinstance(window, dict) and window.get("label")
    }
    rows: list[dict[str, Any]] = []
    for item in ranking:
        if not isinstance(item, dict):
            continue
        label = str(item.get("analog") or item.get("label") or "").strip()
        if not label:
            continue
        profile = _project_profile(analog_profiles.get(label, {}), metric_list)
        window = windows_by_label.get(label, {})
        rows.append(
            {
                "label": label,
                "analog": label,
                "start": window.get("start"),
                "end": window.get("end"),
                "status": "analog_profile",
                "distance_score": _round(item.get("distance_score")),
                "raw_distance": _round(item.get("raw_distance")),
                "normalized_similarity": _round(item.get("normalized_similarity")),
                "current_minus_analog": {
                    key: _round(
                        current.get(key) - profile.get(key)
                        if current.get(key) is not None and profile.get(key) is not None
                        else None
                    )
                    for key, _ in metric_list
                },
                "analog_profile": profile,
                **{
                    key: profile.get(key)
                    for key, _ in metric_list
                    if key not in {"current_minus_analog", "analog_profile"}
                },
            }
        )
    return rows


def build_analog_evidence(
    panel: pd.DataFrame,
    *,
    value_cols: Iterable[str],
    current_window: dict[str, Any],
    analog_windows: Iterable[dict[str, Any]],
    date_col: str = "date",
    coverage_value_cols: Iterable[str] | None = None,
    profile_metrics: Iterable[tuple[str, str]] | None = None,
    min_required_cap: int = 12,
    min_coverage: float = 0.5,
    top_n_divergences: int = 3,
) -> dict[str, Any]:
    """Return reusable analog-window evidence rows for quant scripts."""

    comparison_cols = [str(column) for column in value_cols if str(column)]
    if not comparison_cols:
        raise ValueError("value_cols must include at least one column")
    selected_windows = _explicit_analog_windows(analog_windows)
    coverage_cols = [
        str(column)
        for column in (coverage_value_cols if coverage_value_cols is not None else comparison_cols)
        if str(column)
    ]
    metrics = _metric_specs(comparison_cols, profile_metrics)
    historical_window_coverage = _window_coverage_rows(
        panel,
        selected_windows,
        coverage_cols,
        min_required_cap=min_required_cap,
        min_coverage=min_coverage,
    )
    coverage_by_label = {
        str(row.get("label")): str(row.get("status") or "")
        for row in historical_window_coverage
        if isinstance(row, dict) and row.get("label")
    }
    covered_analog_windows = [
        window
        for window in selected_windows
        if coverage_by_label.get(str(window.get("label"))) == "covered"
    ]

    from ..stats.ols_forecasting import compare_analog_windows

    comparison = compare_analog_windows(
        panel.dropna(how="all", subset=comparison_cols),
        date_col=date_col,
        value_cols=comparison_cols,
        windows=covered_analog_windows,
        current_window=current_window,
        top_n_divergences=top_n_divergences,
    )
    ranking = normalize_analog_ranking(comparison["analog_similarity_ranking"])
    raw_profiles = {
        str(label): profile
        for label, profile in comparison.get("analog_profiles", {}).items()
        if isinstance(profile, dict)
    }
    analog_profiles = {
        label: _project_profile(profile, metrics)
        for label, profile in raw_profiles.items()
    }
    analog_profile_rows = _analog_profile_rows(
        ranking=ranking,
        analog_profiles=raw_profiles,
        current_profile=raw_profiles.get("current", {}),
        analog_windows=covered_analog_windows,
        metrics=metrics,
    )
    comparison_design = {
        **comparison.get("comparison_design", {}),
        "named_windows": covered_analog_windows,
        "excluded_windows": [
            window
            for window in selected_windows
            if window not in covered_analog_windows
        ],
        "current_window": current_window,
    }
    return {
        "historical_window_coverage": historical_window_coverage,
        "analog_similarity_ranking": ranking,
        "analog_profiles": analog_profiles,
        "analog_profile_rows": analog_profile_rows,
        "comparison_design": comparison_design,
        "methods_used": comparison.get("methods_used", []),
        "limitations": comparison.get("limitations", []),
    }
