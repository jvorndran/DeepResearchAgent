"""Small no-key Census Data API client for regional context tables."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import requests


CENSUS_API_BASE_URL = "https://api.census.gov/data"
CENSUS_QUERY_LIMIT_PER_IP_PER_DAY = 500
CENSUS_MAX_VARIABLES_PER_QUERY = 50
DEFAULT_TIMEOUT = 20

_DATASET_RE = re.compile(r"^[0-9]{4}/[A-Za-z0-9_/.-]+$")
_VARIABLE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_STATE_RE = re.compile(r"^\d{2}$")


class CensusDataError(Exception):
    """Recoverable Census Data API error surfaced to data-engineer."""


@dataclass(frozen=True)
class CensusVariableInfo:
    variable: str
    label: str
    concept: str
    units: str


ALLOWED_CENSUS_DATASETS: dict[str, dict[str, str]] = {
    "2023/acs/acs5/profile": {
        "title": "ACS 5-Year Data Profile 2023",
        "source_url": f"{CENSUS_API_BASE_URL}/2023/acs/acs5/profile",
    }
}

ALLOWED_CENSUS_VARIABLES: dict[str, CensusVariableInfo] = {
    "DP05_0001E": CensusVariableInfo(
        variable="DP05_0001E",
        label="Total population",
        concept="demographics",
        units="count",
    ),
    "DP03_0062E": CensusVariableInfo(
        variable="DP03_0062E",
        label="Median household income in the past 12 months",
        concept="income",
        units="dollars",
    ),
    "DP04_0001E": CensusVariableInfo(
        variable="DP04_0001E",
        label="Housing units",
        concept="housing",
        units="count",
    ),
    "DP04_0089E": CensusVariableInfo(
        variable="DP04_0089E",
        label="Median value of owner-occupied housing units",
        concept="housing",
        units="dollars",
    ),
}

VARIABLE_ALIASES = {
    "population": "DP05_0001E",
    "total_population": "DP05_0001E",
    "median_income": "DP03_0062E",
    "median_household_income": "DP03_0062E",
    "housing_units": "DP04_0001E",
    "median_home_value": "DP04_0089E",
}


class CensusPublicDataClient:
    """Fetch strictly allowlisted Census state/county ACS tables without an API key."""

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
            else os.getenv("CENSUS_PUBLIC_API_ENABLED", "true").strip().lower()
            not in {"0", "false", "no", "off"}
        )
        self.session = session or requests.Session()

    def get_table(
        self,
        *,
        dataset: str,
        variables: list[str] | str,
        geography: str,
        state: str | None = None,
    ) -> dict[str, Any]:
        """Return normalized Census rows for an allowlisted dataset/geography/variable set."""
        if not self.enabled:
            return {
                "status": "disabled",
                "provider": "Census Data API",
                "message": "Census Data API is disabled by CENSUS_PUBLIC_API_ENABLED=false.",
            }

        normalized_dataset = self._normalize_dataset(dataset)
        normalized_variables = self._normalize_variables(variables)
        params = self._build_params(normalized_variables, geography=geography, state=state)
        url = f"{CENSUS_API_BASE_URL}/{normalized_dataset}"

        payload = self._get_json(url, params)
        rows = self._parse_table(payload)

        return {
            "status": "success",
            "provider": "Census Data API",
            "source": "Census Data API no-key public endpoint",
            "requires_api_key": False,
            "dataset": normalized_dataset,
            "geography": self._normalized_geography_label(geography),
            "rows": rows,
            "row_count": len(rows),
            "metadata": {
                "authentication": "none",
                "endpoint": url,
                "dataset": ALLOWED_CENSUS_DATASETS[normalized_dataset],
                "variables": {
                    variable: variable_info_to_dict(ALLOWED_CENSUS_VARIABLES[variable])
                    for variable in normalized_variables
                },
                "query_limits": {
                    "max_variables_per_query": CENSUS_MAX_VARIABLES_PER_QUERY,
                    "no_key_queries_per_ip_per_day": CENSUS_QUERY_LIMIT_PER_IP_PER_DAY,
                    "warning": (
                        "No-key Census API use is limited to 500 queries per IP per day; "
                        "batch variables and geographies where possible."
                    ),
                },
            },
        }

    def _normalize_dataset(self, dataset: str) -> str:
        normalized = str(dataset or "").strip().lower()
        if not _DATASET_RE.fullmatch(normalized):
            raise CensusDataError("Census dataset must use an allowlisted year/path format.")
        if normalized not in ALLOWED_CENSUS_DATASETS:
            allowed = ", ".join(sorted(ALLOWED_CENSUS_DATASETS))
            raise CensusDataError(f"Unsupported Census dataset. Allowed datasets: {allowed}.")
        return normalized

    def _normalize_variables(self, variables: list[str] | str) -> list[str]:
        if isinstance(variables, str):
            raw_variables = [part.strip() for part in variables.split(",")]
        else:
            raw_variables = list(variables or [])

        normalized: list[str] = []
        seen = {"NAME"}
        for raw in raw_variables:
            variable = str(raw or "").strip()
            if not variable:
                continue
            variable = VARIABLE_ALIASES.get(variable.lower(), variable.upper())
            if variable == "NAME":
                continue
            if not _VARIABLE_RE.fullmatch(variable):
                raise CensusDataError("Malformed Census variable name.")
            if variable not in ALLOWED_CENSUS_VARIABLES:
                allowed = ", ".join(sorted(ALLOWED_CENSUS_VARIABLES))
                raise CensusDataError(f"Unsupported Census variable. Allowed variables: {allowed}.")
            if variable not in seen:
                seen.add(variable)
                normalized.append(variable)

        if not normalized:
            raise CensusDataError("Provide at least one Census data variable.")
        if len(normalized) + 1 > CENSUS_MAX_VARIABLES_PER_QUERY:
            raise CensusDataError(
                "Census API queries are limited to 50 variables including NAME; "
                "request at most 49 data variables per call."
            )
        return normalized

    def _build_params(
        self, variables: list[str], *, geography: str, state: str | None
    ) -> dict[str, str]:
        normalized_geo = self._normalized_geography_label(geography)
        params = {"get": ",".join(["NAME", *variables])}
        if normalized_geo == "state":
            if state not in (None, "", "*"):
                raise CensusDataError("State geography does not accept a state filter.")
            params["for"] = "state:*"
            return params
        if normalized_geo == "county":
            params["for"] = "county:*"
            if state not in (None, "", "*"):
                state_code = str(state).strip()
                if not _STATE_RE.fullmatch(state_code):
                    raise CensusDataError("County geography state filter must be a two-digit FIPS code.")
                params["in"] = f"state:{state_code}"
            return params
        raise CensusDataError("Unsupported Census geography. Allowed geographies: state, county.")

    def _normalized_geography_label(self, geography: str) -> str:
        normalized = str(geography or "").strip().lower().replace("_", " ")
        if normalized in {"state", "states", "state:*"}:
            return "state"
        if normalized in {"county", "counties", "county:*"}:
            return "county"
        raise CensusDataError("Unsupported Census geography. Allowed geographies: state, county.")

    def _get_json(self, url: str, params: dict[str, str]) -> Any:
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as exc:
            raise CensusDataError("Census request timed out.") from exc
        except requests.RequestException as exc:
            raise CensusDataError(f"Census request failed: {exc}") from exc
        except ValueError as exc:
            raise CensusDataError("Census response was not valid JSON.") from exc
        return data

    def _parse_table(self, payload: Any) -> list[dict[str, str | int | None]]:
        if not isinstance(payload, list) or len(payload) < 2:
            raise CensusDataError("Census response was malformed: expected a two-dimensional table.")
        header = payload[0]
        if not isinstance(header, list) or not all(isinstance(item, str) for item in header):
            raise CensusDataError("Census response was malformed: invalid header row.")

        rows: list[dict[str, str | int | None]] = []
        for raw_row in payload[1:]:
            if not isinstance(raw_row, list) or len(raw_row) != len(header):
                raise CensusDataError("Census response was malformed: row width did not match header.")
            row = {
                header[index]: self._coerce_cell(value, column=header[index])
                for index, value in enumerate(raw_row)
            }
            rows.append(row)

        if not rows:
            raise CensusDataError("Census response did not include any data rows.")
        return rows

    def _coerce_cell(self, value: Any, *, column: str) -> str | int | None:
        if value is None:
            return None
        text = str(value).strip()
        if text in {"", "-666666666", "-999999999"}:
            return None
        if column in {"state", "county"}:
            return text
        if re.fullmatch(r"-?\d+", text):
            try:
                return int(text)
            except ValueError:
                return text
        return text


def variable_info_to_dict(info: CensusVariableInfo) -> dict[str, str]:
    return {
        "variable": info.variable,
        "label": info.label,
        "concept": info.concept,
        "units": info.units,
        "source": "Census Data API",
    }
