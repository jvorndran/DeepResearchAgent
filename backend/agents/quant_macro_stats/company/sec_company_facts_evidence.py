"""SEC company-facts helpers for reusable quant evidence."""

from __future__ import annotations

import re
from functools import partial
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from ..artifacts.numeric_fact_contracts import numeric_fact
from .._utils import (
    METHOD_SEC_COMPANY_FACTS_SUMMARY,
    _finite_float,
    _require_columns,
    find_data_file_key,
    finite_number as _finite,
    read_value_series as _read_monthly_series,
    rounded_number as _round,
)

_METHOD = "sec_company_fundamentals"
_SEC_SUMMARY_METHOD = "sec_company_facts_summary"
_SEC_TICKER_STOPWORDS = {
    "CSV",
    "DATA",
    "EDGAR",
    "FACT",
    "FACTS",
    "COMPANY",
    "FISCAL",
    "PUBLIC",
    "SEC",
}
_COMPANY_NAME_ALIASES = {
    "AAPL": ("apple",),
    "MSFT": ("microsoft",),
    "NVDA": ("nvidia",),
    "GOOGL": ("alphabet", "google"),
    "GOOG": ("alphabet", "google"),
    "AMZN": ("amazon",),
    "META": ("meta", "facebook"),
    "TSLA": ("tesla",),
}
_matching_key = partial(find_data_file_key, allow_prefix=True)


def summarize_sec_company_facts(
    data: pd.DataFrame | str | Path,
    *,
    periods: int = 5,
    scale: float = 1_000_000_000,
) -> dict[str, Any]:
    """Summarize SEC EDGAR company-facts CSVs using named financial columns."""

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
        "cash_and_equivalents",
        "marketable_securities_current",
        "stockholders_equity",
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

    def ratio_pct(
        numerator: str,
        denominator: str,
        row: pd.Series = latest,
    ) -> float | None:
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
        "cash_and_equivalents_latest": scaled("cash_and_equivalents"),
        "marketable_securities_current_latest": scaled(
            "marketable_securities_current"
        ),
        "cash_and_securities_latest": (
            None
            if value("cash_and_equivalents") is None
            and value("marketable_securities_current") is None
            else (
                (value("cash_and_equivalents") or 0.0)
                + (value("marketable_securities_current") or 0.0)
            )
            / scale
        ),
        "research_and_development_pct_revenue": ratio_pct(
            "research_and_development", "revenue"
        ),
        "selling_general_and_admin_pct_revenue": ratio_pct(
            "selling_general_and_admin", "revenue"
        ),
        "assets_latest": scaled("assets"),
        "liabilities_latest": scaled("liabilities"),
        "stockholders_equity_latest": scaled("stockholders_equity"),
        "debt_to_assets_pct": ratio_pct("long_term_debt", "assets"),
        "equity_to_assets_pct": ratio_pct("stockholders_equity", "assets"),
        "methods_used": [METHOD_SEC_COMPANY_FACTS_SUMMARY],
        "method_notes": [
            "SEC EDGAR company facts are summarized from named columns such as revenue and net_income, never numeric column position.",
            f"Monetary latest values are scaled by {scale:g}. Growth metrics compare the first and latest fiscal-year rows in the selected window.",
        ],
    }


def is_sec_company_facts_file(key: str, path: str) -> bool:
    key_upper = str(key).upper()
    path_name = Path(str(path)).name.lower()
    return key_upper.endswith("_SEC") or "sec_edgar_company_facts" in path_name


def sec_ticker_from_source(
    key: str,
    path: str,
    *,
    preferred_tickers: set[str] | None = None,
) -> str | None:
    """Infer an SEC company ticker from either a data-file key or filename."""

    candidates = [str(key), Path(path).stem]
    preferred = {ticker.upper() for ticker in preferred_tickers or set()}
    parsed_tokens: list[str] = []
    for candidate in candidates:
        tokens = [
            token
            for token in re.split(r"[^A-Za-z0-9]+", candidate.upper())
            if token and token not in _SEC_TICKER_STOPWORDS
        ]
        parsed_tokens.extend(tokens)
        for token in tokens:
            if token in preferred:
                return token
    for token in parsed_tokens:
        if 1 <= len(token) <= 5 and token.isalpha():
            return token
    return None


def requested_company_tickers(
    query: str | None,
    *,
    available_tickers: Iterable[str] | None = None,
) -> set[str]:
    lowered = str(query or "").lower()
    requested: set[str] = set()
    candidates = {ticker.upper() for ticker in available_tickers or set()}
    candidates.update(_COMPANY_NAME_ALIASES)
    for ticker in candidates:
        markers = (ticker.lower(), *_COMPANY_NAME_ALIASES.get(ticker, ()))
        if any(marker in lowered for marker in markers):
            requested.add(ticker)
    return requested


def resolve_company_fact_sources(
    data_files: dict[str, str],
    query: str | None = None,
    tickers: Iterable[str] | None = None,
) -> list[dict[str, str]]:
    """Return normalized SEC company-facts sources from a data_files mapping."""

    allowed_tickers = {ticker.upper() for ticker in tickers or ()}
    preferred = allowed_tickers | requested_company_tickers(query)
    sources: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for key, path in data_files.items():
        if not is_sec_company_facts_file(str(key), str(path)):
            continue
        ticker = sec_ticker_from_source(
            str(key),
            str(path),
            preferred_tickers=preferred or None,
        )
        if not ticker or (allowed_tickers and ticker not in allowed_tickers):
            continue
        identity = (ticker, str(path))
        if identity in seen:
            continue
        seen.add(identity)
        sources.append({"ticker": ticker, "source_key": str(key), "path": str(path)})
    return sorted(sources, key=lambda item: (item["ticker"], item["source_key"]))


def _read_company_frame(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if "fiscal_year" not in frame.columns:
        raise ValueError("SEC company facts CSV requires fiscal_year")
    frame = frame.copy()
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
        "cash_and_equivalents",
        "marketable_securities_current",
        "long_term_debt",
        "stockholders_equity",
        "assets",
        "liabilities",
        "shares",
    ):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["fiscal_year"]).sort_values("fiscal_year")
    if frame.empty:
        raise ValueError("SEC company facts CSV has no fiscal-year rows")
    return frame.reset_index(drop=True)


def _value(row: pd.Series, column: str) -> float | None:
    return _finite(row.get(column)) if column in row.index else None


def _billions(row: pd.Series, column: str) -> float | None:
    value = _value(row, column)
    return None if value is None else value / 1_000_000_000


def _ratio_pct(row: pd.Series, numerator: str, denominator: str) -> float | None:
    num = _value(row, numerator)
    den = _value(row, denominator)
    if num is None or den in (None, 0):
        return None
    return num / den * 100.0


def _company_history_rows(ticker: str, frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prior_revenue: float | None = None
    prior_net_income: float | None = None
    for _, row in frame.iterrows():
        revenue_b = _billions(row, "revenue")
        net_income_b = _billions(row, "net_income")
        ocf_b = _billions(row, "operating_cash_flow")
        capex_b = _billions(row, "capital_expenditures")
        fcf_b = None
        if ocf_b is not None and capex_b is not None:
            fcf_b = ocf_b - capex_b
        cash_b = _billions(row, "cash_and_equivalents")
        securities_b = _billions(row, "marketable_securities_current")
        cash_and_securities_b = (
            None
            if cash_b is None and securities_b is None
            else (cash_b or 0.0) + (securities_b or 0.0)
        )
        revenue_growth_pct = None
        if prior_revenue not in (None, 0) and revenue_b is not None:
            revenue_growth_pct = (revenue_b / prior_revenue - 1.0) * 100.0
        if revenue_b is not None:
            prior_revenue = revenue_b
        net_income_growth_pct = None
        if prior_net_income not in (None, 0) and net_income_b is not None:
            net_income_growth_pct = (net_income_b / prior_net_income - 1.0) * 100.0
        if net_income_b is not None:
            prior_net_income = net_income_b
        fiscal_year = int(row["fiscal_year"])
        rows.append(
            {
                "ticker": ticker,
                "period": f"{ticker} FY{fiscal_year}",
                "fiscal_year": fiscal_year,
                "fiscal_period_end": str(row.get("revenue_end") or row.get("net_income_end") or ""),
                "revenue_b": _round(revenue_b, 3),
                "revenue_growth_pct": _round(revenue_growth_pct, 2),
                "net_income_growth_pct": _round(net_income_growth_pct, 2),
                "gross_profit_b": _round(_billions(row, "gross_profit"), 3),
                "operating_income_b": _round(_billions(row, "operating_income"), 3),
                "net_income_b": _round(net_income_b, 3),
                "gross_margin_pct": _round(_ratio_pct(row, "gross_profit", "revenue"), 2),
                "operating_margin_pct": _round(_ratio_pct(row, "operating_income", "revenue"), 2),
                "net_margin_pct": _round(_ratio_pct(row, "net_income", "revenue"), 2),
                "operating_cash_flow_b": _round(ocf_b, 3),
                "capital_expenditures_b": _round(capex_b, 3),
                "free_cash_flow_b": _round(fcf_b, 3),
                "free_cash_flow_margin_pct": _round(
                    None if fcf_b is None or revenue_b in (None, 0) else fcf_b / revenue_b * 100.0,
                    2,
                ),
                "cash_and_securities_b": _round(cash_and_securities_b, 3),
                "long_term_debt_b": _round(_billions(row, "long_term_debt"), 3),
                "stockholders_equity_b": _round(_billions(row, "stockholders_equity"), 3),
                "assets_b": _round(_billions(row, "assets"), 3),
                "liabilities_b": _round(_billions(row, "liabilities"), 3),
                "diluted_eps": _round(_value(row, "diluted_eps"), 3),
                "shares_b": _round(_billions(row, "shares"), 3),
                "research_and_development_pct_revenue": _round(
                    _ratio_pct(row, "research_and_development", "revenue"), 2
                ),
                "selling_general_and_admin_pct_revenue": _round(
                    _ratio_pct(row, "selling_general_and_admin", "revenue"), 2
                ),
            }
        )
    return rows


def _latest_fundamentals(
    ticker: str,
    summary: dict[str, Any],
    history_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    latest = history_rows[-1]
    fields = {
        "ticker": ticker,
        "fiscal_year": latest.get("fiscal_year"),
        "fiscal_period_end": latest.get("fiscal_period_end"),
        "revenue_b": _round(summary.get("revenue_latest"), 3),
        "net_income_b": _round(summary.get("net_income_latest"), 3),
        "gross_margin_pct": _round(summary.get("gross_margin_pct"), 2),
        "operating_margin_pct": _round(summary.get("operating_margin_pct"), 2),
        "net_margin_pct": _round(summary.get("net_margin_pct"), 2),
        "operating_cash_flow_b": _round(summary.get("operating_cash_flow_latest"), 3),
        "capital_expenditures_b": _round(summary.get("capital_expenditures_latest"), 3),
        "free_cash_flow_b": _round(summary.get("free_cash_flow_latest"), 3),
        "cash_and_securities_b": _round(summary.get("cash_and_securities_latest"), 3),
        "long_term_debt_b": latest.get("long_term_debt_b"),
        "stockholders_equity_b": _round(summary.get("stockholders_equity_latest"), 3),
        "assets_b": _round(summary.get("assets_latest"), 3),
        "liabilities_b": _round(summary.get("liabilities_latest"), 3),
        "diluted_eps": _round(summary.get("diluted_eps_latest"), 3),
        "revenue_growth_pct": latest.get("revenue_growth_pct"),
        "net_income_growth_pct": latest.get("net_income_growth_pct"),
        "period_revenue_growth_pct": _round(summary.get("revenue_growth_pct"), 2),
        "period_net_income_growth_pct": _round(summary.get("net_income_growth_pct"), 2),
        "revenue_cagr_pct": _round(summary.get("revenue_cagr_pct"), 2),
        "net_income_cagr_pct": _round(summary.get("net_income_cagr_pct"), 2),
        "debt_to_assets_pct": _round(summary.get("debt_to_assets_pct"), 2),
        "equity_to_assets_pct": _round(summary.get("equity_to_assets_pct"), 2),
    }
    return {key: value for key, value in fields.items() if value is not None}


def _trend_diagnostics(
    ticker: str,
    latest: dict[str, Any],
    history_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    last_three = history_rows[-3:]
    revenue_growth = [
        row.get("revenue_growth_pct")
        for row in last_three
        if row.get("revenue_growth_pct") is not None
    ]
    margin_rows = [row for row in last_three if row.get("net_margin_pct") is not None]
    fcf_rows = [row for row in last_three if row.get("free_cash_flow_margin_pct") is not None]
    return {
        "ticker": ticker,
        "latest_fiscal_year": latest.get("fiscal_year"),
        "revenue_cagr_pct": latest.get("revenue_cagr_pct"),
        "latest_revenue_growth_pct": latest.get("revenue_growth_pct"),
        "latest_net_margin_pct": latest.get("net_margin_pct"),
        "latest_free_cash_flow_margin_pct": history_rows[-1].get("free_cash_flow_margin_pct"),
        "average_recent_revenue_growth_pct": _round(np.nanmean(revenue_growth), 2)
        if revenue_growth
        else None,
        "net_margin_change_last_3y_pp": _round(
            margin_rows[-1]["net_margin_pct"] - margin_rows[0]["net_margin_pct"],
            2,
        )
        if len(margin_rows) >= 2
        else None,
        "fcf_margin_change_last_3y_pp": _round(
            fcf_rows[-1]["free_cash_flow_margin_pct"]
            - fcf_rows[0]["free_cash_flow_margin_pct"],
            2,
        )
        if len(fcf_rows) >= 2
        else None,
    }


def _fiscal_window(row: dict[str, Any]) -> tuple[pd.Timestamp, pd.Timestamp]:
    period_end = pd.to_datetime(row.get("fiscal_period_end"), errors="coerce")
    if pd.isna(period_end):
        period_end = pd.Timestamp(year=int(row["fiscal_year"]), month=12, day=31)
    period_start = period_end - pd.DateOffset(years=1) + pd.DateOffset(days=1)
    return pd.Timestamp(period_start), pd.Timestamp(period_end)


def _macro_overlay(
    data_files: dict[str, str],
    history_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    fed_key = _matching_key(data_files, ("FEDFUNDS",))
    recession_key = _matching_key(data_files, ("USREC",))
    fed = _read_monthly_series(data_files[fed_key], "fedfunds") if fed_key else pd.DataFrame()
    recession = (
        _read_monthly_series(data_files[recession_key], "usrec") if recession_key else pd.DataFrame()
    )
    rows: list[dict[str, Any]] = []
    for row in history_rows:
        start, end = _fiscal_window(row)
        overlay = {
            "ticker": row["ticker"],
            "period": row["period"],
            "fiscal_year": row["fiscal_year"],
            "revenue_growth_pct": row.get("revenue_growth_pct"),
            "net_margin_pct": row.get("net_margin_pct"),
        }
        if not fed.empty:
            mask = (fed["date"] >= start) & (fed["date"] <= end)
            avg_fed = fed.loc[mask, "fedfunds"].mean()
            overlay["avg_fedfunds_pct"] = _round(avg_fed, 2)
        if not recession.empty:
            mask = (recession["date"] >= start) & (recession["date"] <= end)
            overlay["recession_months"] = int((recession.loc[mask, "usrec"].fillna(0) > 0).sum())
        rows.append(overlay)
    status = "covered" if fed_key or recession_key else "not_available"
    return {
        "status": status,
        "source_keys": [key for key in (fed_key, recession_key) if key],
        "rows": rows,
        "method": "fiscal_year_macro_overlay",
        "limitations": [
            "Fiscal-year macro overlay uses monthly FRED data within each company's approximate fiscal-year window.",
            "Overlay rows are contextual sensitivity evidence, not a causal estimate of company revenue or margin response.",
        ],
    }


def _source_coverage(company_count: int, macro_overlay: dict[str, Any]) -> dict[str, Any]:
    return {
        "sec_company_facts": {
            "status": "covered" if company_count else "not_available",
            "evidence_keys": ["history_rows", "latest_fundamentals"] if company_count else [],
        },
        "macro_rate_recession_overlay": {
            "status": macro_overlay.get("status", "not_available"),
            "evidence_keys": ["macro_overlay.rows"] if macro_overlay.get("status") == "covered" else [],
        },
        "segment_detail": {
            "status": "not_available",
            "limitation": "SEC company-facts CSVs do not provide segment/product/customer detail.",
        },
        "valuation_market_data": {
            "status": "not_available",
            "limitation": "No paid/keyed market data, analyst estimates, or valuation multiples were used.",
        },
        "management_guidance": {
            "status": "not_available",
            "limitation": "Management guidance and forward backlog commentary are outside SEC company-facts evidence.",
        },
    }


def _numeric_facts(latest_by_ticker: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    fact_specs = [
        ("revenue_b", "revenue", "usd_b", 3, 0.005),
        ("net_income_b", "net income", "usd_b", 3, 0.005),
        ("gross_margin_pct", "gross margin", "percent", 2, 0.005),
        ("operating_margin_pct", "operating margin", "percent", 2, 0.005),
        ("net_margin_pct", "net margin", "percent", 2, 0.005),
        ("operating_cash_flow_b", "operating cash flow", "usd_b", 3, 0.005),
        ("free_cash_flow_b", "free cash flow", "usd_b", 3, 0.005),
        ("cash_and_securities_b", "cash and marketable securities", "usd_b", 3, 0.005),
        ("long_term_debt_b", "long-term debt", "usd_b", 3, 0.005),
        ("assets_b", "assets", "usd_b", 3, 0.005),
        ("liabilities_b", "liabilities", "usd_b", 3, 0.005),
        ("diluted_eps", "diluted EPS", "usd", 3, 0.001),
        ("revenue_growth_pct", "revenue growth", "percent", 2, 0.005),
        ("revenue_cagr_pct", "revenue CAGR", "percent", 2, 0.005),
    ]
    for ticker, latest in latest_by_ticker.items():
        for metric, label, unit, precision, tolerance in fact_specs:
            fact = numeric_fact(
                fact_id=f"sec_company_facts.{ticker}.{metric}",
                label=f"{ticker} latest {label}",
                raw_value=latest.get(metric),
                unit=unit,
                precision=precision,
                tolerance=tolerance,
                source_key=f"sec_company_facts.latest_fundamentals.{ticker}.{metric}",
                subject=ticker,
                metric=metric,
                as_of_date=latest.get("fiscal_period_end") or latest.get("fiscal_year"),
            )
            if fact:
                facts.append(fact)
    return facts


def _macro_sensitivity_rows(
    latest_by_ticker: dict[str, dict[str, Any]],
    overlay: dict[str, Any],
) -> list[dict[str, Any]]:
    overlay_rows = overlay.get("rows") if isinstance(overlay, dict) else []
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    if isinstance(overlay_rows, list):
        for row in overlay_rows:
            if isinstance(row, dict) and row.get("ticker"):
                by_ticker.setdefault(str(row["ticker"]), []).append(row)
    rows: list[dict[str, Any]] = []
    for ticker, latest in latest_by_ticker.items():
        ticker_rows = by_ticker.get(ticker, [])
        latest_overlay = ticker_rows[-1] if ticker_rows else {}
        recession_years = [
            row.get("fiscal_year")
            for row in ticker_rows
            if _finite(row.get("recession_months")) and float(row["recession_months"]) > 0
        ]
        high_rate_rows = [
            row
            for row in ticker_rows
            if _finite(row.get("avg_fedfunds_pct")) is not None
            and float(row["avg_fedfunds_pct"]) >= 4.0
        ]
        rows.append(
            {
                "ticker": ticker,
                "latest_fiscal_year": latest.get("fiscal_year"),
                "latest_avg_fedfunds_pct": latest_overlay.get("avg_fedfunds_pct"),
                "latest_recession_months": latest_overlay.get("recession_months"),
                "recession_fiscal_years_in_history": recession_years,
                "high_rate_fiscal_year_count": len(high_rate_rows),
            }
        )
    return rows


def _company_context_status(
    *,
    query: str | None,
    covered_tickers: Iterable[str],
    source_keys: Iterable[str],
) -> dict[str, Any]:
    covered = sorted({ticker.upper() for ticker in covered_tickers})
    requested = sorted(requested_company_tickers(query, available_tickers=covered))
    if not requested and covered:
        requested = covered
    missing = sorted(set(requested) - set(covered))
    source_key_list = sorted(str(key) for key in source_keys)
    if covered and not missing:
        status = "covered"
    elif covered:
        status = "partial"
    elif requested or source_key_list:
        status = "not_available"
    else:
        status = "not_requested"
    return {
        "status": status,
        "requested_tickers": requested,
        "covered_tickers": covered,
        "missing_requested_tickers": missing,
        "sec_source_keys": source_key_list,
    }


def sec_company_facts_evidence(
    data_files: dict[str, str],
    query: str | None = None,
    tickers: Iterable[str] | None = None,
    *,
    include_macro_overlay: bool = True,
) -> dict[str, Any]:
    """Return reusable SEC company-facts evidence for quant scripts."""

    sources = resolve_company_fact_sources(data_files, query=query, tickers=tickers)
    history_rows: list[dict[str, Any]] = []
    latest_by_ticker: dict[str, dict[str, Any]] = {}
    source_files: dict[str, str] = {}
    source_keys: dict[str, str] = {}
    fiscal_coverage: dict[str, Any] = {}
    trend_rows: list[dict[str, Any]] = []
    source_errors: list[dict[str, str]] = []

    for source in sources:
        ticker = source["ticker"]
        try:
            frame = _read_company_frame(source["path"])
            summary = summarize_sec_company_facts(frame)
        except (OSError, ValueError) as exc:
            source_errors.append(
                {
                    "ticker": ticker,
                    "source_key": source["source_key"],
                    "path": source["path"],
                    "error": str(exc),
                }
            )
            continue
        rows = _company_history_rows(ticker, frame)
        latest = _latest_fundamentals(ticker, summary, rows)
        latest_by_ticker[ticker] = latest
        history_rows.extend(rows)
        source_files[ticker] = source["path"]
        source_keys[ticker] = source["source_key"]
        fiscal_coverage[ticker] = {
            "fiscal_year_start": summary.get("fiscal_year_start"),
            "fiscal_year_latest": summary.get("fiscal_year_latest"),
            "periods": summary.get("periods"),
            "source_key": source["source_key"],
            "path": source["path"],
        }
        trend_rows.append(_trend_diagnostics(ticker, latest, rows))

    history_rows = sorted(history_rows, key=lambda row: (str(row["ticker"]), int(row["fiscal_year"])))
    if include_macro_overlay and history_rows:
        macro_overlay = _macro_overlay(data_files, history_rows)
    else:
        macro_overlay = {
            "status": "not_available",
            "source_keys": [],
            "rows": [],
            "method": "fiscal_year_macro_overlay",
            "limitations": [
                "No FRED rate or recession context was requested for this SEC company-facts evidence."
            ],
        }
    company_status = _company_context_status(
        query=query,
        covered_tickers=latest_by_ticker,
        source_keys=[source["source_key"] for source in sources],
    )
    macro_sensitivity = _macro_sensitivity_rows(latest_by_ticker, macro_overlay)
    numeric_facts = _numeric_facts(latest_by_ticker)
    source_coverage = _source_coverage(len(latest_by_ticker), macro_overlay)
    if source_errors:
        source_coverage["sec_company_facts"]["fetch_errors"] = source_errors
    unavailable_claim_categories = [
        key
        for key, payload in source_coverage.items()
        if isinstance(payload, dict) and payload.get("status") == "not_available"
    ]

    return {
        "schema_version": 1,
        "evidence_type": "sec_company_facts",
        "source_kind": "sec_company_facts",
        "status": company_status["status"],
        "query": query,
        "tickers": sorted(latest_by_ticker),
        "requested_tickers": company_status["requested_tickers"],
        "missing_requested_tickers": company_status["missing_requested_tickers"],
        "source_files": source_files,
        "source_keys": source_keys,
        "source_errors": source_errors,
        "fiscal_coverage": fiscal_coverage,
        "history_rows": history_rows,
        "latest_fundamentals": latest_by_ticker,
        "trend_diagnostics": trend_rows,
        "macro_overlay": macro_overlay,
        "company_macro_sensitivity": macro_sensitivity,
        "company_context_status": company_status,
        "source_coverage": source_coverage,
        "unavailable_claim_categories": unavailable_claim_categories,
        "numeric_facts": numeric_facts,
        "methods_used": [_METHOD, _SEC_SUMMARY_METHOD],
        "limitations": [
            "SEC company-facts evidence is annual standardized fundamentals; segment, customer, backlog, valuation, and management-guidance data are not included.",
            "Fiscal-year macro overlay rows are contextual FRED evidence and are not a causal estimate or forecast of company performance.",
        ],
    }
