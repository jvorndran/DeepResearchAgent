"""Correlation, recession-window, and method-label helpers."""
import sys

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

def rolling_correlation(
    data: pd.DataFrame,
    x_col: str,
    y_col: str,
    *,
    date_col: str = "date",
    window: int = 12,
    min_periods: int | None = None,
) -> pd.DataFrame:
    """Return rolling Pearson correlations without imputing missing observations."""

    if window <= 1:
        raise ValueError("window must be greater than 1")
    min_obs = window if min_periods is None else min_periods
    if min_obs <= 1 or min_obs > window:
        raise ValueError("min_periods must be greater than 1 and no larger than window")

    frame = _as_ordered_frame(data, date_col, [x_col, y_col])
    pair_observations = (frame[[x_col, y_col]].notna().all(axis=1)).rolling(window).sum()
    corr = frame[x_col].rolling(window, min_periods=min_obs).corr(frame[y_col])

    return pd.DataFrame(
        {
            date_col: frame[date_col],
            "correlation": corr,
            "observations": pair_observations.fillna(0).astype(int),
            "method": METHOD_ROLLING_CORRELATION,
        }
    )


def _pearson_pair(x: pd.Series, y: pd.Series) -> tuple[float | None, float | None, str]:
    if len(x) < 2:
        return None, None, "insufficient_observations"
    if x.nunique(dropna=True) < 2 or y.nunique(dropna=True) < 2:
        return None, None, "constant_input"
    public_module = sys.modules.get("agents.quant_macro_stats")
    scipy_stats = getattr(public_module, "_scipy_stats", _scipy_stats)
    if scipy_stats is not None:
        result = scipy_stats.pearsonr(x.to_numpy(dtype=float), y.to_numpy(dtype=float))
        return float(result.statistic), float(result.pvalue), "ok"
    return float(np.corrcoef(x.to_numpy(dtype=float), y.to_numpy(dtype=float))[0, 1]), None, "ok"


def lead_lag_correlations(
    data: pd.DataFrame,
    predictor_col: str,
    target_col: str,
    *,
    date_col: str = "date",
    lags: Iterable[int] = range(0, 13),
    min_observations: int = 8,
) -> dict[str, Any]:
    """
    Score whether ``predictor_col`` leads ``target_col``.

    A positive lag means predictor at period t is compared with target at
    period t + lag. Negative lags are allowed for diagnostics but are not
    described as lead evidence.
    """

    if min_observations < 2:
        raise ValueError("min_observations must be at least 2")
    lag_values = [int(lag) for lag in lags]
    if not lag_values:
        raise ValueError("lags must include at least one integer")

    frame = _as_ordered_frame(data, date_col, [predictor_col, target_col])
    results: list[dict[str, Any]] = []
    for lag in lag_values:
        shifted_target = frame[target_col].shift(-lag)
        pair = pd.DataFrame({"predictor": frame[predictor_col], "target": shifted_target}).dropna()
        nobs = int(len(pair))
        if nobs < min_observations:
            r_value, p_value, status = None, None, "insufficient_observations"
        else:
            r_value, p_value, status = _pearson_pair(pair["predictor"], pair["target"])
        results.append(
            {
                "lag": lag,
                "nobs": nobs,
                "correlation": r_value,
                "p_value": p_value,
                "status": status,
                "method": METHOD_LEAD_LAG_CORRELATION,
            }
        )

    valid = [item for item in results if item["correlation"] is not None]
    selected = max(valid, key=lambda item: abs(item["correlation"])) if valid else None
    return {
        "predictor": predictor_col,
        "target": target_col,
        "selected_lag": selected["lag"] if selected else None,
        "selected_result": selected,
        "lag_results": results,
        "methods_used": [METHOD_LEAD_LAG_CORRELATION],
        "method_caveats": [
            "Positive lag means predictor at t is compared with target at t+lag.",
            "Correlation is descriptive lead-lag evidence, not proof of causality.",
        ],
    }


def recession_window_summary(
    data: pd.DataFrame,
    value_cols: Iterable[str] | None = None,
    *,
    recession_col: str = "recession",
    date_col: str = "date",
    lookback_periods: Iterable[int] | None = (6, 12),
    variables: Iterable[str] | None = None,
    target_col: str | None = None,
    target: str | None = None,
    windows: Iterable[int] | None = None,
) -> dict[str, Any]:
    """
    Summarize contiguous recession windows marked by a binary recession column.

    ``lookback_periods`` are exact ordered-row offsets before the first recession
    observation. They intentionally exclude the recession start row to avoid
    lookahead and overlapping-window leakage in leading-indicator summaries.

    Generated analysis scripts sometimes use alias names while repairing
    helper calls. ``variables``, ``target_col``, and ``target`` map to
    ``value_cols``; ``windows`` maps to ``lookback_periods``.
    """

    if value_cols is None and variables is not None:
        value_cols = variables
    if value_cols is None and target_col is not None:
        value_cols = [target_col]
    if value_cols is None and target is not None:
        value_cols = [target]
    if windows is not None:
        lookback_periods = windows
    if value_cols is None:
        numeric_columns = data.select_dtypes(include=[np.number]).columns
        value_cols = [
            column
            for column in numeric_columns
            if column not in {date_col, recession_col}
        ]
    columns = list(value_cols)
    if not columns:
        raise ValueError(
            "recession_window_summary requires at least one value column; pass "
            "value_cols or variables, or provide numeric columns to infer."
        )
    lookbacks = sorted({int(period) for period in (lookback_periods or [])})
    if any(period <= 0 for period in lookbacks):
        raise ValueError("lookback_periods must contain positive integers")

    frame = _as_ordered_frame(data, date_col, [recession_col, *columns])
    in_recession = frame[recession_col].fillna(0).astype(float) > 0
    window_id = (in_recession.ne(in_recession.shift(fill_value=False))).cumsum()

    windows: list[dict[str, Any]] = []
    for _, window in frame[in_recession].groupby(window_id[in_recession]):
        start_position = int(window.index[0])
        summary: dict[str, Any] = {
            "start": window[date_col].iloc[0].date().isoformat(),
            "end": window[date_col].iloc[-1].date().isoformat(),
            "periods": int(len(window)),
        }
        for column in columns:
            values = window[column].dropna()
            start_value = _finite_float(window[column].iloc[0])
            exact_lookbacks = {
                f"{period}_periods_before": (
                    _finite_float(frame[column].iloc[start_position - period])
                    if start_position - period >= 0
                    else None
                )
                for period in lookbacks
            }
            prior_windows: dict[str, dict[str, Any]] = {}
            for period in lookbacks:
                prior = (
                    frame[column].iloc[max(0, start_position - period) : start_position].dropna()
                )
                prior_windows[f"prior_{period}_periods"] = {
                    "observations": int(len(prior)),
                    "mean": float(prior.mean()) if len(prior) else None,
                    "min": float(prior.min()) if len(prior) else None,
                    "max": float(prior.max()) if len(prior) else None,
                }
            summary[column] = {
                "observations": int(len(values)),
                "at_start": start_value,
                "exact_lookbacks": exact_lookbacks,
                "prior_windows": prior_windows,
                "mean": float(values.mean()) if len(values) else None,
                "min": float(values.min()) if len(values) else None,
                "max": float(values.max()) if len(values) else None,
                "change": float(values.iloc[-1] - values.iloc[0]) if len(values) >= 2 else None,
            }
        windows.append(summary)

    return {
        "recession_col": recession_col,
        "windows": windows,
        "methods_used": [METHOD_RECESSION_WINDOW_SUMMARY],
        "method_notes": [
            "Recession windows are contiguous periods where the recession indicator is positive.",
            "Exact lookbacks use ordered rows before the recession start and exclude the start month to avoid lookahead.",
            "Prior-window statistics also exclude recession observations at the window start.",
        ],
    }


def _normalize_method_labels(methods: str | Iterable[str]) -> list[str]:
    if isinstance(methods, str):
        candidates = [methods]
    else:
        candidates = list(methods)
    return list(dict.fromkeys(method for method in candidates if method))


def _looks_like_chart_definition(payload: dict[str, Any]) -> bool:
    return isinstance(payload.get("id"), str) and isinstance(payload.get("type"), str)


def attach_methods_used(charts: dict[str, Any], methods: str | Iterable[str]) -> dict[str, Any]:
    """Return chart definition(s) with compact ``methods_used`` labels.

    The canonical input is a ``charts.json`` style dict keyed by chart ID. The
    helper also accepts a single chart definition because generated analysis
    scripts commonly annotate charts before assembling the final chart map.
    """

    method_list = _normalize_method_labels(methods)
    annotated = deepcopy(charts)
    chart_items = [annotated] if _looks_like_chart_definition(annotated) else annotated.values()
    for chart in chart_items:
        if not isinstance(chart, dict):
            continue
        existing = chart.get("methods_used", [])
        if not isinstance(existing, list):
            existing = []
        chart["methods_used"] = list(dict.fromkeys([*existing, *method_list]))
    return annotated


def summarize_sec_company_facts(
    data: pd.DataFrame | str | Path,
    *,
    periods: int = 5,
    scale: float = 1_000_000_000,
) -> dict[str, Any]:
    """Summarize SEC EDGAR company-facts CSVs using named financial columns.

    The SEC client emits many numeric columns, including shares and balance-sheet
    items. Generated scripts should not infer revenue or margins from numeric
    column position; this helper keeps issuer fundamentals tied to explicit SEC
    fields.
    """

    if isinstance(data, str | Path):
        frame = pd.read_csv(data)
    else:
        frame = data.copy()
    _require_columns(frame, ["fiscal_year", "revenue", "net_income"])
    frame["fiscal_year"] = pd.to_numeric(frame["fiscal_year"], errors="coerce")
    for column in (
        "revenue",
        "net_income",
        "gross_profit",
        "operating_income",
        "operating_cash_flow",
        "capital_expenditures",
        "research_and_development",
        "selling_general_and_admin",
        "diluted_eps",
        "assets",
        "liabilities",
        "long_term_debt",
        "shares",
    ):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = (
        frame.dropna(subset=["fiscal_year"])
        .sort_values("fiscal_year")
        .tail(max(int(periods), 1))
        .reset_index(drop=True)
    )
    if frame.empty:
        raise ValueError("SEC company facts summary requires at least one fiscal-year row")

    latest = frame.iloc[-1]
    first = frame.iloc[0]

    def value(column: str, row: pd.Series = latest) -> float | None:
        if column not in frame.columns:
            return None
        return _finite_float(row.get(column))

    def scaled(column: str) -> float | None:
        raw = value(column)
        return None if raw is None else raw / scale

    def growth_pct(column: str) -> float | None:
        start = value(column, first)
        end = value(column, latest)
        if start in (None, 0) or end is None:
            return None
        return ((end / start) - 1.0) * 100.0

    def cagr_pct(column: str) -> float | None:
        start = value(column, first)
        end = value(column, latest)
        start_year = _finite_float(first.get("fiscal_year"))
        end_year = _finite_float(latest.get("fiscal_year"))
        if start in (None, 0) or end is None or start_year is None or end_year is None:
            return None
        span = end_year - start_year
        if span <= 0:
            return None
        return ((end / start) ** (1.0 / span) - 1.0) * 100.0

    def ratio_pct(numerator: str, denominator: str, row: pd.Series = latest) -> float | None:
        num = value(numerator, row)
        den = value(denominator, row)
        if num is None or den in (None, 0):
            return None
        return (num / den) * 100.0

    latest_year = _finite_float(latest.get("fiscal_year"))
    first_year = _finite_float(first.get("fiscal_year"))
    return {
        "fiscal_year_latest": int(latest_year) if latest_year is not None else None,
        "fiscal_year_start": int(first_year) if first_year is not None else None,
        "periods": int(len(frame)),
        "revenue_latest": scaled("revenue"),
        "net_income_latest": scaled("net_income"),
        "revenue_growth_pct": growth_pct("revenue"),
        "net_income_growth_pct": growth_pct("net_income"),
        "revenue_cagr_pct": cagr_pct("revenue"),
        "net_income_cagr_pct": cagr_pct("net_income"),
        "net_margin_pct": ratio_pct("net_income", "revenue"),
        "gross_margin_pct": ratio_pct("gross_profit", "revenue"),
        "operating_margin_pct": ratio_pct("operating_income", "revenue"),
        "operating_cash_flow_latest": scaled("operating_cash_flow"),
        "capital_expenditures_latest": scaled("capital_expenditures"),
        "free_cash_flow_latest": (
            None
            if value("operating_cash_flow") is None
            or value("capital_expenditures") is None
            else (value("operating_cash_flow") - value("capital_expenditures")) / scale
        ),
        "research_and_development_latest": scaled("research_and_development"),
        "selling_general_and_admin_latest": scaled("selling_general_and_admin"),
        "diluted_eps_latest": value("diluted_eps"),
        "research_and_development_pct_revenue": ratio_pct(
            "research_and_development", "revenue"
        ),
        "selling_general_and_admin_pct_revenue": ratio_pct(
            "selling_general_and_admin", "revenue"
        ),
        "assets_latest": scaled("assets"),
        "liabilities_latest": scaled("liabilities"),
        "debt_to_assets_pct": ratio_pct("long_term_debt", "assets"),
        "methods_used": [METHOD_SEC_COMPANY_FACTS_SUMMARY],
        "method_notes": [
            "SEC EDGAR company facts are summarized from named columns such as revenue and net_income, never numeric column position.",
            f"Monetary latest values are scaled by {scale:g}. Growth metrics compare the first and latest fiscal-year rows in the selected window.",
        ],
    }


def attach_summary_methods(summary: dict[str, Any], methods: str | Iterable[str]) -> dict[str, Any]:
    """Return an execution_summary-style payload with a stable ``methods_used`` list."""
    result = deepcopy(summary)
    existing = result.get("methods_used", [])
    result["methods_used"] = _normalize_method_labels(
        [*(_normalize_method_labels(existing) if existing else []), *_normalize_method_labels(methods)]
    )
    return result
