"""Small no-key BLS Public Data API client."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import requests


BLS_V1_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
DEFAULT_TIMEOUT = 20
MAX_NO_KEY_SERIES = 25
MAX_NO_KEY_YEAR_SPAN = 10

_SERIES_ID_RE = re.compile(r"^[A-Z0-9_#-]{3,32}$")


class BLSPublicDataError(Exception):
    """Recoverable BLS Public Data API error surfaced to data-engineer."""


@dataclass(frozen=True)
class BLSSeriesInfo:
    series_id: str
    title: str
    category: str
    frequency: str
    units: str
    seasonal_adjustment: str
    source_note: str


KNOWN_BLS_SERIES: dict[str, BLSSeriesInfo] = {
    "LNS14000000": BLSSeriesInfo(
        series_id="LNS14000000",
        title="Unemployment Rate",
        category="labor",
        frequency="monthly",
        units="percent",
        seasonal_adjustment="seasonally adjusted",
        source_note="Current Population Survey household unemployment rate.",
    ),
    "CES0000000001": BLSSeriesInfo(
        series_id="CES0000000001",
        title="All Employees, Total Nonfarm",
        category="employment",
        frequency="monthly",
        units="thousands of persons",
        seasonal_adjustment="seasonally adjusted",
        source_note="Current Employment Statistics payroll employment.",
    ),
    "CES0500000003": BLSSeriesInfo(
        series_id="CES0500000003",
        title="Average Hourly Earnings of All Employees, Total Private",
        category="wages",
        frequency="monthly",
        units="dollars per hour",
        seasonal_adjustment="seasonally adjusted",
        source_note="Current Employment Statistics nominal average hourly earnings.",
    ),
    "CUSR0000SA0": BLSSeriesInfo(
        series_id="CUSR0000SA0",
        title="Consumer Price Index for All Urban Consumers: All Items",
        category="prices",
        frequency="monthly",
        units="index 1982-84=100",
        seasonal_adjustment="seasonally adjusted",
        source_note="Consumer Price Index for All Urban Consumers.",
    ),
    "WPUFD4": BLSSeriesInfo(
        series_id="WPUFD4",
        title="Producer Price Index by Commodity: Final Demand",
        category="producer_prices",
        frequency="monthly",
        units="index 1982=100",
        seasonal_adjustment="not seasonally adjusted",
        source_note="Producer Price Index final demand.",
    ),
    "PRS85006092": BLSSeriesInfo(
        series_id="PRS85006092",
        title="Nonfarm Business Sector: Labor Productivity",
        category="productivity",
        frequency="quarterly",
        units="percent change from previous quarter at annual rate",
        seasonal_adjustment="seasonally adjusted",
        source_note="Labor productivity and costs, nonfarm business sector.",
    ),
}

_SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "LNS14000000": ("unemployment", "unrate", "labor market", "jobless"),
    "CES0000000001": ("payroll", "nonfarm", "employment", "jobs"),
    "CES0500000003": ("average hourly earnings", "wages", "earnings", "pay"),
    "CUSR0000SA0": ("cpi", "inflation", "consumer price", "prices"),
    "WPUFD4": ("ppi", "producer price", "final demand"),
    "PRS85006092": ("productivity", "labor productivity", "nonfarm business"),
}


def search_known_bls_series(query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Return curated BLS series candidates without network access."""
    normalized_query = " ".join(str(query or "").lower().split())
    if not normalized_query:
        return []

    results: list[dict[str, Any]] = []
    for series_id, info in KNOWN_BLS_SERIES.items():
        haystack = " ".join(
            (
                series_id.lower(),
                info.title.lower(),
                info.category.lower(),
                info.units.lower(),
                info.source_note.lower(),
                " ".join(_SEARCH_TERMS.get(series_id, ())),
            )
        )
        if normalized_query in haystack or any(
            token in haystack for token in normalized_query.split()
        ):
            results.append(series_info_to_dict(info))

    return results[: max(1, min(int(limit), len(KNOWN_BLS_SERIES)))]


def series_info_to_dict(info: BLSSeriesInfo) -> dict[str, Any]:
    return {
        "series_id": info.series_id,
        "title": info.title,
        "category": info.category,
        "frequency": info.frequency,
        "units": info.units,
        "seasonal_adjustment": info.seasonal_adjustment,
        "source_note": info.source_note,
        "source": "BLS Public Data API",
        "source_url": BLS_V1_URL,
    }


class BLSPublicDataClient:
    """Fetch BLS public time-series data through the no-registration v1 endpoint."""

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        enabled: bool | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.enabled = (
            enabled
            if enabled is not None
            else os.getenv("BLS_PUBLIC_API_ENABLED", "true").strip().lower()
            not in {"0", "false", "no", "off"}
        )
        self.session = session or requests.Session()

    def get_series(
        self,
        series_ids: str | list[str],
        *,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> dict[str, Any]:
        """Return normalized observations for one or more BLS series IDs."""
        if not self.enabled:
            return {
                "status": "disabled",
                "provider": "BLS Public Data",
                "message": "BLS Public Data API is disabled by BLS_PUBLIC_API_ENABLED=false.",
            }

        normalized_ids = self._normalize_series_ids(series_ids)
        years = self._validate_years(start_year, end_year)
        payload: dict[str, Any] = {"seriesid": normalized_ids}
        if years:
            payload.update({"startyear": str(years[0]), "endyear": str(years[1])})

        response_payload = self._post_json(payload)
        status = str(response_payload.get("status", ""))
        if status != "REQUEST_SUCCEEDED":
            raise BLSPublicDataError(self._provider_error_message(response_payload))

        results = response_payload.get("Results")
        series_payloads = results.get("series") if isinstance(results, dict) else None
        if not isinstance(series_payloads, list):
            raise BLSPublicDataError("BLS response was malformed: missing Results.series.")

        output_series = []
        for series in series_payloads:
            if not isinstance(series, dict):
                continue
            series_id = str(series.get("seriesID", "")).upper()
            if not series_id:
                continue
            observations = self._normalize_observations(series_id, series.get("data", []))
            if not observations:
                raise BLSPublicDataError(
                    f"BLS series {series_id} returned no observations for the requested window."
                )
            output_series.append(
                {
                    "series_id": series_id,
                    "metadata": series_info_to_dict(KNOWN_BLS_SERIES[series_id])
                    if series_id in KNOWN_BLS_SERIES
                    else {
                        "series_id": series_id,
                        "source": "BLS Public Data API",
                        "source_url": BLS_V1_URL,
                    },
                    "observations": observations,
                    "row_count": len(observations),
                }
            )

        if not output_series:
            raise BLSPublicDataError("BLS response did not include any usable series data.")

        return {
            "status": "success",
            "provider": "BLS Public Data",
            "source": "BLS Public Data API v1 no-registration endpoint",
            "requires_api_key": False,
            "series": output_series,
            "metadata": {
                "authentication": "none",
                "endpoint": BLS_V1_URL,
                "year_window": list(years) if years else None,
                "known_series_metadata": "curated local map; API v1 data payload has limited metadata",
            },
        }

    def _normalize_series_ids(self, series_ids: str | list[str]) -> list[str]:
        raw_ids = [series_ids] if isinstance(series_ids, str) else list(series_ids or [])
        normalized = []
        seen = set()
        for raw in raw_ids:
            series_id = str(raw or "").strip().upper()
            if not series_id:
                continue
            if not _SERIES_ID_RE.fullmatch(series_id):
                raise BLSPublicDataError(
                    "Malformed BLS series ID. Use uppercase letters, digits, underscore, dash, or #."
                )
            if series_id not in seen:
                seen.add(series_id)
                normalized.append(series_id)

        if not normalized:
            raise BLSPublicDataError("Provide at least one BLS series ID.")
        if len(normalized) > MAX_NO_KEY_SERIES:
            raise BLSPublicDataError(
                f"BLS no-key requests are limited to {MAX_NO_KEY_SERIES} series per call."
            )
        return normalized

    def _validate_years(
        self, start_year: int | None, end_year: int | None
    ) -> tuple[int, int] | None:
        if start_year is None and end_year is None:
            return None
        if start_year is None or end_year is None:
            raise BLSPublicDataError("Provide both start_year and end_year, or neither.")
        try:
            start = int(start_year)
            end = int(end_year)
        except Exception as exc:
            raise BLSPublicDataError("BLS start_year and end_year must be integers.") from exc
        if start < 1900 or end < 1900 or start > 2100 or end > 2100:
            raise BLSPublicDataError("BLS year window must be between 1900 and 2100.")
        if start > end:
            raise BLSPublicDataError("BLS start_year must be less than or equal to end_year.")
        if end - start + 1 > MAX_NO_KEY_YEAR_SPAN:
            raise BLSPublicDataError(
                f"BLS no-key requests are limited to {MAX_NO_KEY_YEAR_SPAN} years per call."
            )
        return start, end

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.session.post(BLS_V1_URL, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as exc:
            raise BLSPublicDataError("BLS request timed out.") from exc
        except requests.RequestException as exc:
            raise BLSPublicDataError(f"BLS request failed: {exc}") from exc
        except ValueError as exc:
            raise BLSPublicDataError("BLS response was not valid JSON.") from exc
        if not isinstance(data, dict):
            raise BLSPublicDataError("BLS response was malformed: expected a JSON object.")
        return data

    def _provider_error_message(self, payload: dict[str, Any]) -> str:
        messages = payload.get("message")
        if isinstance(messages, list) and messages:
            return "BLS API error: " + "; ".join(str(item) for item in messages[:3])
        if isinstance(messages, str) and messages:
            return f"BLS API error: {messages}"
        return f"BLS API request failed with status {payload.get('status', 'unknown')}."

    def _normalize_observations(
        self, series_id: str, rows: Any
    ) -> list[dict[str, str | int | float | None]]:
        if not isinstance(rows, list):
            raise BLSPublicDataError(f"BLS series {series_id} data payload was malformed.")

        observations = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            year = str(row.get("year", "")).strip()
            period = str(row.get("period", "")).strip()
            if not year or not period:
                continue
            observations.append(
                {
                    "series_id": series_id,
                    "year": int(year) if year.isdigit() else year,
                    "period": period,
                    "period_name": row.get("periodName"),
                    "value": row.get("value"),
                    "footnotes": self._footnotes_to_text(row.get("footnotes")),
                }
            )
        return observations

    def _footnotes_to_text(self, footnotes: Any) -> str:
        if not isinstance(footnotes, list):
            return ""
        texts = []
        for item in footnotes:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    texts.append(str(text))
        return "; ".join(texts)
