"""Small no-key SEC EDGAR client for company fundamentals."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

import requests


SEC_BASE_URL = "https://data.sec.gov"
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
DEFAULT_SEC_USER_AGENT = "DeepResearchAgent/0.1 contact: research@example.invalid"

_CIK_RE = re.compile(r"^\d{1,10}$")
_TICKER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9.-]{0,9}$")


class SECEdgarError(Exception):
    """Recoverable SEC EDGAR client error surfaced to the data-engineer agent."""


@dataclass(frozen=True)
class SECMetricSpec:
    output_name: str
    concepts: tuple[str, ...]
    unit: str


_METRICS = (
    SECMetricSpec(
        "revenue",
        ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
        "USD",
    ),
    SECMetricSpec("net_income", ("NetIncomeLoss",), "USD"),
    SECMetricSpec("gross_profit", ("GrossProfit",), "USD"),
    SECMetricSpec(
        "operating_income",
        (
            "OperatingIncomeLoss",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        ),
        "USD",
    ),
    SECMetricSpec(
        "operating_cash_flow",
        ("NetCashProvidedByUsedInOperatingActivities",),
        "USD",
    ),
    SECMetricSpec(
        "capital_expenditures",
        ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
        "USD",
    ),
    SECMetricSpec("research_and_development", ("ResearchAndDevelopmentExpense",), "USD"),
    SECMetricSpec(
        "selling_general_and_admin",
        ("SellingGeneralAndAdministrativeExpense",),
        "USD",
    ),
    SECMetricSpec("diluted_eps", ("EarningsPerShareDiluted",), "USD/shares"),
    SECMetricSpec(
        "cash_and_equivalents",
        (
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ),
        "USD",
    ),
    SECMetricSpec(
        "marketable_securities_current",
        ("MarketableSecuritiesCurrent", "ShortTermInvestments"),
        "USD",
    ),
    SECMetricSpec("debt_current", ("ShortTermBorrowings", "ShortTermDebtCurrent"), "USD"),
    SECMetricSpec(
        "long_term_debt",
        ("LongTermDebtNoncurrent", "LongTermDebtAndFinanceLeaseObligationsNoncurrent"),
        "USD",
    ),
    SECMetricSpec("stockholders_equity", ("StockholdersEquity",), "USD"),
    SECMetricSpec("assets", ("Assets",), "USD"),
    SECMetricSpec("liabilities", ("Liabilities",), "USD"),
    SECMetricSpec(
        "shares",
        (
            "CommonStocksSharesOutstanding",
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageNumberOfSharesOutstandingBasic",
        ),
        "shares",
    ),
)


class SECEdgarClient:
    """Fetch compact company facts from SEC public no-auth endpoints."""

    def __init__(
        self,
        *,
        timeout: float = 20,
        user_agent: str | None = None,
        enabled: bool | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent or os.getenv("SEC_EDGAR_USER_AGENT", DEFAULT_SEC_USER_AGENT)
        self.enabled = (
            enabled
            if enabled is not None
            else os.getenv("SEC_EDGAR_ENABLED", "true").strip().lower()
            not in {"0", "false", "no", "off"}
        )
        self.session = session or requests.Session()

    def get_company_facts(self, identifier: str, periods: int = 5) -> dict[str, Any]:
        """Return compact SEC fundamentals for a ticker or CIK."""
        if not self.enabled:
            return {
                "status": "disabled",
                "provider": "SEC EDGAR",
                "message": "SEC EDGAR company facts are disabled by SEC_EDGAR_ENABLED=false.",
            }

        cik, ticker = self._resolve_cik(identifier)
        facts = self._get_json(f"{SEC_BASE_URL}/api/xbrl/companyfacts/CIK{cik}.json")
        submissions = self._get_json(f"{SEC_BASE_URL}/submissions/CIK{cik}.json")

        rows_by_year: dict[int, dict[str, Any]] = {}
        for metric in _METRICS:
            observations = self._extract_metric_observations(facts, metric, periods)
            for obs in observations:
                year = obs["fiscal_year"]
                row = rows_by_year.setdefault(year, {"fiscal_year": year})
                row[metric.output_name] = obs["value"]
                row[f"{metric.output_name}_end"] = obs.get("end")
                row[f"{metric.output_name}_filed"] = obs.get("filed")
                row[f"{metric.output_name}_form"] = obs.get("form")
                row[f"{metric.output_name}_concept"] = obs.get("concept")

        fundamentals = [
            rows_by_year[year] for year in sorted(rows_by_year.keys(), reverse=True)[:periods]
        ]

        return {
            "status": "success",
            "provider": "SEC EDGAR",
            "source": "SEC data.sec.gov submissions and XBRL companyfacts APIs",
            "identifier": identifier,
            "ticker": ticker,
            "cik": cik,
            "company_name": facts.get("entityName") or submissions.get("name"),
            "fundamentals": fundamentals,
            "filings": self._extract_recent_filings(submissions, limit=periods),
            "metadata": {
                "authentication": "none",
                "requires_api_key": False,
                "endpoints": [
                    f"{SEC_BASE_URL}/api/xbrl/companyfacts/CIK{cik}.json",
                    f"{SEC_BASE_URL}/submissions/CIK{cik}.json",
                ],
            },
        }

    def _resolve_cik(self, identifier: str) -> tuple[str, str | None]:
        cleaned = str(identifier or "").strip()
        if not cleaned:
            raise SECEdgarError("Provide a ticker like AAPL or a numeric CIK.")

        normalized_cik = cleaned.lstrip("0") or "0"
        if _CIK_RE.fullmatch(cleaned) and int(normalized_cik) > 0:
            return normalized_cik.zfill(10), None

        ticker = cleaned.upper()
        if not _TICKER_RE.fullmatch(ticker):
            raise SECEdgarError(
                "Malformed ticker/CIK. Use 1-10 CIK digits or a ticker with letters, digits, dots, or hyphens."
            )

        ticker_map = self._get_json(SEC_TICKER_URL, sec_data_host=False)
        if not isinstance(ticker_map, dict):
            raise SECEdgarError("SEC ticker mapping response was malformed.")

        for entry in ticker_map.values():
            if isinstance(entry, dict) and str(entry.get("ticker", "")).upper() == ticker:
                cik = entry.get("cik_str")
                if isinstance(cik, int) or (isinstance(cik, str) and str(cik).isdigit()):
                    return str(cik).zfill(10), ticker

        raise SECEdgarError(f"Ticker '{ticker}' was not found in SEC company_tickers.json.")

    def _get_json(self, url: str, *, sec_data_host: bool = True) -> Any:
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
        }
        try:
            response = self.session.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.Timeout as exc:
            raise SECEdgarError(f"SEC request timed out for {url}.") from exc
        except requests.RequestException as exc:
            raise SECEdgarError(f"SEC request failed for {url}: {exc}") from exc
        except ValueError as exc:
            host_hint = "data.sec.gov" if sec_data_host else "www.sec.gov"
            raise SECEdgarError(f"SEC {host_hint} response was not valid JSON.") from exc

    def _extract_metric_observations(
        self, facts: dict[str, Any], metric: SECMetricSpec, periods: int
    ) -> list[dict[str, Any]]:
        facts_payload = facts.get("facts")
        us_gaap = facts_payload.get("us-gaap") if isinstance(facts_payload, dict) else None
        if not isinstance(us_gaap, dict):
            raise SECEdgarError("SEC companyfacts response is missing facts.us-gaap.")

        observations_by_year: dict[int, dict[str, Any]] = {}
        for concept_priority, concept in enumerate(metric.concepts):
            concept_payload = us_gaap.get(concept)
            if not isinstance(concept_payload, dict):
                continue
            units = concept_payload.get("units", {})
            unit_rows = units.get(metric.unit) if isinstance(units, dict) else None
            if not isinstance(unit_rows, list):
                continue

            candidates_by_fy: dict[int, dict[str, Any]] = {}
            for item in unit_rows:
                if not isinstance(item, dict):
                    continue
                form = str(item.get("form", ""))
                fiscal_period = str(item.get("fp", ""))
                fiscal_year = item.get("fy")
                if form != "10-K" or fiscal_period != "FY" or not isinstance(fiscal_year, int):
                    continue
                if "val" not in item:
                    continue
                start = _parse_iso_date(item.get("start"))
                end = _parse_iso_date(item.get("end"))
                if start and end and (end - start).days < 250:
                    continue

                candidate = {
                    "fiscal_year": fiscal_year,
                    "value": item["val"],
                    "end": item.get("end"),
                    "filed": item.get("filed"),
                    "form": form,
                    "concept": concept,
                    "_concept_priority": concept_priority,
                }
                current = candidates_by_fy.get(fiscal_year)
                if current is None or _annual_observation_key(candidate) > _annual_observation_key(
                    current
                ):
                    candidates_by_fy[fiscal_year] = candidate

            for fiscal_year, observation in candidates_by_fy.items():
                current = observations_by_year.get(fiscal_year)
                if current is None or observation["_concept_priority"] < current["_concept_priority"]:
                    observations_by_year[fiscal_year] = observation

        observations = []
        for observation in observations_by_year.values():
            observation.pop("_concept_priority", None)
            observations.append(observation)

        return sorted(
            observations,
            key=lambda row: (row["fiscal_year"], row.get("end") or "", row.get("filed") or ""),
            reverse=True,
        )[:periods]

    def _extract_recent_filings(self, submissions: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        recent = submissions.get("filings", {}).get("recent", {})
        if not isinstance(recent, dict):
            return []

        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        primary_documents = recent.get("primaryDocument", [])

        filings = []
        for idx, form in enumerate(forms):
            if form not in {"10-K", "10-Q"}:
                continue
            filings.append(
                {
                    "form": form,
                    "accession_number": _list_get(accession_numbers, idx),
                    "filing_date": _list_get(filing_dates, idx),
                    "report_date": _list_get(report_dates, idx),
                    "primary_document": _list_get(primary_documents, idx),
                }
            )
            if len(filings) >= limit:
                break
        return filings


def _list_get(values: Any, index: int) -> Any:
    if isinstance(values, list) and index < len(values):
        return values[index]
    return None


def _parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _annual_observation_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("end") or ""), str(row.get("filed") or ""))
