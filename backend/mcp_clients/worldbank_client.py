"""Small no-key World Bank Indicators API client."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import requests


WORLD_BANK_API_BASE_URL = "https://api.worldbank.org/v2"
WORLD_BANK_INDICATOR_URL = f"{WORLD_BANK_API_BASE_URL}/country/{{countries}}/indicator/{{indicator}}"
DEFAULT_TIMEOUT = 20
DEFAULT_PER_PAGE = 1000
MAX_COUNTRIES_PER_REQUEST = 12

_COUNTRY_RE = re.compile(r"^[A-Z]{2,3}$")
_INDICATOR_RE = re.compile(r"^[A-Z0-9.]{3,64}$")


class WorldBankDataError(Exception):
    """Recoverable World Bank Indicators API error surfaced to data-engineer."""


@dataclass(frozen=True)
class WorldBankCountryInfo:
    code: str
    name: str


@dataclass(frozen=True)
class WorldBankIndicatorInfo:
    indicator_id: str
    title: str
    units: str
    frequency: str
    source_note: str


ALLOWED_WORLD_BANK_COUNTRIES: dict[str, WorldBankCountryInfo] = {
    "USA": WorldBankCountryInfo(code="USA", name="United States"),
    "CAN": WorldBankCountryInfo(code="CAN", name="Canada"),
    "DEU": WorldBankCountryInfo(code="DEU", name="Germany"),
    "JPN": WorldBankCountryInfo(code="JPN", name="Japan"),
    "MEX": WorldBankCountryInfo(code="MEX", name="Mexico"),
}

COUNTRY_ALIASES = {
    "US": "USA",
    "U.S.": "USA",
    "UNITED STATES": "USA",
    "UNITED STATES OF AMERICA": "USA",
    "CA": "CAN",
    "CANADA": "CAN",
    "DE": "DEU",
    "GERMANY": "DEU",
    "JP": "JPN",
    "JAPAN": "JPN",
    "MX": "MEX",
    "MEXICO": "MEX",
}

ALLOWED_WORLD_BANK_INDICATORS: dict[str, WorldBankIndicatorInfo] = {
    "FP.CPI.TOTL.ZG": WorldBankIndicatorInfo(
        indicator_id="FP.CPI.TOTL.ZG",
        title="Inflation, consumer prices (annual %)",
        units="annual percent change",
        frequency="annual",
        source_note="World Bank World Development Indicators consumer price inflation.",
    ),
    "NY.GDP.MKTP.KD.ZG": WorldBankIndicatorInfo(
        indicator_id="NY.GDP.MKTP.KD.ZG",
        title="GDP growth (annual %)",
        units="annual percent change",
        frequency="annual",
        source_note="World Bank World Development Indicators real GDP growth.",
    ),
}

INDICATOR_ALIASES = {
    "INFLATION": "FP.CPI.TOTL.ZG",
    "CPI_INFLATION": "FP.CPI.TOTL.ZG",
    "CONSUMER_INFLATION": "FP.CPI.TOTL.ZG",
    "GDP_GROWTH": "NY.GDP.MKTP.KD.ZG",
    "REAL_GDP_GROWTH": "NY.GDP.MKTP.KD.ZG",
    "GROWTH": "NY.GDP.MKTP.KD.ZG",
}


class WorldBankIndicatorsClient:
    """Fetch World Bank annual indicator observations from the no-key v2 API."""

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
            else os.getenv("WORLD_BANK_API_ENABLED", "true").strip().lower()
            not in {"0", "false", "no", "off"}
        )
        self.session = session or requests.Session()

    def get_indicator(
        self,
        *,
        country_codes: str | list[str],
        indicator: str,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> dict[str, Any]:
        """Return normalized annual observations for one allowlisted indicator."""
        if not self.enabled:
            return {
                "status": "disabled",
                "provider": "World Bank Indicators API",
                "message": "World Bank Indicators API is disabled by WORLD_BANK_API_ENABLED=false.",
            }

        countries = self._normalize_countries(country_codes)
        indicator_id = self._normalize_indicator(indicator)
        years = self._validate_years(start_year, end_year)
        rows = self._fetch_all_pages(countries=countries, indicator_id=indicator_id, years=years)

        if not rows:
            raise WorldBankDataError(
                f"World Bank indicator {indicator_id} returned no observations for the request."
            )

        return {
            "status": "success",
            "provider": "World Bank Indicators API",
            "source": "World Bank Indicators API v2 no-key endpoint",
            "requires_api_key": False,
            "indicator": indicator_info_to_dict(ALLOWED_WORLD_BANK_INDICATORS[indicator_id]),
            "countries": {
                code: country_info_to_dict(ALLOWED_WORLD_BANK_COUNTRIES[code])
                for code in countries
            },
            "observations": rows,
            "row_count": len(rows),
            "metadata": {
                "authentication": "none",
                "endpoint": WORLD_BANK_INDICATOR_URL.format(
                    countries=";".join(countries), indicator=indicator_id
                ),
                "year_window": list(years) if years else None,
                "handoff_guidance": (
                    "World Bank indicators are annual. For monthly or quarterly US context, "
                    "fetch FRED separately and have quant-developer align frequencies explicitly; "
                    "do not forward-fill annual World Bank values into monthly analysis without "
                    "stating the limitation."
                ),
            },
        }

    def _normalize_countries(self, country_codes: str | list[str]) -> list[str]:
        raw_codes = _parse_listish(country_codes)
        normalized: list[str] = []
        seen = set()
        for raw in raw_codes:
            text = str(raw or "").strip()
            if not text:
                continue
            key = " ".join(text.upper().replace("_", " ").split())
            code = COUNTRY_ALIASES.get(key, key)
            if not _COUNTRY_RE.fullmatch(code):
                if key.replace(" ", "").isalpha():
                    allowed = ", ".join(sorted(ALLOWED_WORLD_BANK_COUNTRIES))
                    raise WorldBankDataError(
                        f"Unsupported World Bank country. Allowed countries: {allowed}."
                    )
                raise WorldBankDataError(
                    "Malformed World Bank country code. Use ISO2/ISO3 codes or supported aliases."
                )
            if code not in ALLOWED_WORLD_BANK_COUNTRIES:
                allowed = ", ".join(sorted(ALLOWED_WORLD_BANK_COUNTRIES))
                raise WorldBankDataError(f"Unsupported World Bank country. Allowed countries: {allowed}.")
            if code not in seen:
                seen.add(code)
                normalized.append(code)

        if not normalized:
            raise WorldBankDataError("Provide at least one World Bank country code.")
        if len(normalized) > MAX_COUNTRIES_PER_REQUEST:
            raise WorldBankDataError(
                f"World Bank requests are limited to {MAX_COUNTRIES_PER_REQUEST} countries per call."
            )
        return normalized

    def _normalize_indicator(self, indicator: str) -> str:
        text = str(indicator or "").strip()
        key = text.upper().replace("-", "_").replace(" ", "_")
        indicator_id = INDICATOR_ALIASES.get(key, text.upper())
        if not _INDICATOR_RE.fullmatch(indicator_id):
            raise WorldBankDataError("Malformed World Bank indicator code.")
        if indicator_id not in ALLOWED_WORLD_BANK_INDICATORS:
            allowed = ", ".join(sorted(ALLOWED_WORLD_BANK_INDICATORS))
            raise WorldBankDataError(f"Unsupported World Bank indicator. Allowed indicators: {allowed}.")
        return indicator_id

    def _validate_years(
        self, start_year: int | None, end_year: int | None
    ) -> tuple[int, int] | None:
        if start_year is None and end_year is None:
            return None
        if start_year is None or end_year is None:
            raise WorldBankDataError("World Bank start_year and end_year must be provided together.")
        try:
            start = int(start_year)
            end = int(end_year)
        except Exception as exc:
            raise WorldBankDataError("World Bank years must be integers.") from exc
        if start < 1960 or end < 1960 or start > end:
            raise WorldBankDataError("World Bank year window must be valid and start no earlier than 1960.")
        return start, end

    def _fetch_all_pages(
        self,
        *,
        countries: list[str],
        indicator_id: str,
        years: tuple[int, int] | None,
    ) -> list[dict[str, Any]]:
        page = 1
        pages = 1
        rows: list[dict[str, Any]] = []
        while page <= pages:
            payload = self._get_json(
                WORLD_BANK_INDICATOR_URL.format(
                    countries=";".join(countries), indicator=indicator_id
                ),
                params=self._params(page=page, years=years),
            )
            metadata, page_rows = self._parse_page(payload)
            pages = metadata["pages"]
            rows.extend(self._normalize_rows(page_rows, indicator_id=indicator_id))
            page += 1

        rows.sort(key=lambda row: (row["country_code"], row["year"]))
        return rows

    def _params(self, *, page: int, years: tuple[int, int] | None) -> dict[str, str]:
        params = {"format": "json", "per_page": str(DEFAULT_PER_PAGE), "page": str(page)}
        if years:
            params["date"] = f"{years[0]}:{years[1]}"
        return params

    def _get_json(self, url: str, params: dict[str, str]) -> Any:
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as exc:
            raise WorldBankDataError("World Bank request timed out.") from exc
        except requests.RequestException as exc:
            raise WorldBankDataError(f"World Bank request failed: {exc}") from exc
        except ValueError as exc:
            raise WorldBankDataError("World Bank response was not valid JSON.") from exc
        return data

    def _parse_page(self, payload: Any) -> tuple[dict[str, int], list[Any]]:
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            if "message" in payload[0]:
                raise WorldBankDataError(self._provider_error_message(payload[0].get("message")))
            if len(payload) >= 2 and isinstance(payload[1], list):
                metadata = payload[0]
                try:
                    pages = max(1, int(metadata.get("pages", 1)))
                except Exception as exc:
                    raise WorldBankDataError("World Bank response metadata had invalid pages.") from exc
                return {"pages": pages}, payload[1]
        raise WorldBankDataError(
            "World Bank response was malformed: expected [metadata, observations]."
        )

    def _normalize_rows(self, rows: list[Any], *, indicator_id: str) -> list[dict[str, Any]]:
        normalized = []
        indicator_info = ALLOWED_WORLD_BANK_INDICATORS[indicator_id]
        for row in rows:
            if not isinstance(row, dict):
                raise WorldBankDataError("World Bank response was malformed: observation was not an object.")
            country = row.get("country")
            indicator = row.get("indicator")
            if not isinstance(country, dict) or not isinstance(indicator, dict):
                raise WorldBankDataError(
                    "World Bank response was malformed: missing country or indicator metadata."
                )
            country_code = str(row.get("countryiso3code") or country.get("id") or "").upper()
            date = str(row.get("date") or "").strip()
            if not country_code or not date:
                raise WorldBankDataError(
                    "World Bank response was malformed: missing country code or date."
                )
            try:
                year = int(date)
            except ValueError as exc:
                raise WorldBankDataError("World Bank response date was not an annual year.") from exc
            value = row.get("value")
            normalized.append(
                {
                    "country_code": country_code,
                    "country_name": str(country.get("value") or country.get("name") or ""),
                    "indicator_id": str(indicator.get("id") or indicator_id),
                    "indicator_name": str(indicator.get("value") or indicator_info.title),
                    "year": year,
                    "value": _coerce_number(value),
                    "units": indicator_info.units,
                    "frequency": indicator_info.frequency,
                    "source": "World Bank Indicators API",
                }
            )
        return normalized

    def _provider_error_message(self, message: Any) -> str:
        if isinstance(message, list):
            parts = []
            for item in message:
                if isinstance(item, dict):
                    value = item.get("value") or item.get("message") or item.get("id")
                    if value:
                        parts.append(str(value))
                elif item:
                    parts.append(str(item))
            if parts:
                return "World Bank API error: " + " | ".join(parts)
        return "World Bank API returned an error payload."


def _parse_listish(value: str | list[str]) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                import json

                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except Exception:
                pass
        return [part.strip() for part in re.split(r"[,;]", stripped) if part.strip()]
    return [str(item) for item in list(value or [])]


def _coerce_number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except ValueError:
        return None
    if numeric.is_integer():
        return int(numeric)
    return numeric


def country_info_to_dict(info: WorldBankCountryInfo) -> dict[str, str]:
    return {"code": info.code, "name": info.name, "source": "World Bank Indicators API"}


def indicator_info_to_dict(info: WorldBankIndicatorInfo) -> dict[str, str]:
    return {
        "indicator_id": info.indicator_id,
        "title": info.title,
        "units": info.units,
        "frequency": info.frequency,
        "source_note": info.source_note,
        "source": "World Bank Indicators API",
    }
