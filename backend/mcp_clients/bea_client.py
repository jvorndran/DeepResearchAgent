"""Typed BEA NIPA public data client."""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from typing import Any

import requests
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .provider_payload import provider_payload_sha256

BEA_API_URL = "https://apps.bea.gov/api/data"
DEFAULT_TIMEOUT = 20

_TABLE_NAME_RE = re.compile(r"^T[0-9]{5}[A-Z]?$")
_YEAR_RE = re.compile(r"^[0-9]{4}$")
_QUARTER_RE = re.compile(r"^([0-9]{4})Q([1-4])$")
_MONTH_RE = re.compile(r"^([0-9]{4})M(0[1-9]|1[0-2])$")
_SPECIAL_YEAR_VALUES = {"X", "ALL"}

_REVISION_POLICY = (
    "Latest available BEA NIPA estimates; observations are subject to regular annual "
    "updates and comprehensive revisions."
)


class BEADataError(Exception):
    """Recoverable BEA API error surfaced to data-engineer."""


class BEANIPATableDescriptor(BaseModel):
    """Allowlisted BEA NIPA table metadata used as a source descriptor."""

    model_config = ConfigDict(frozen=True)

    table_name: str
    title: str
    category: str
    units: str
    allowed_frequencies: tuple[str, ...] = ("A", "Q")
    release_cadence: str
    revision_policy: str = _REVISION_POLICY
    source_note: str


ALLOWED_NIPA_TABLES: dict[str, BEANIPATableDescriptor] = {
    "T10101": BEANIPATableDescriptor(
        table_name="T10101",
        title="Table 1.1.1. Percent Change From Preceding Period in Real Gross Domestic Product",
        category="gdp",
        units="percent change",
        release_cadence="quarterly GDP release cycle with annual NIPA updates",
        source_note="BEA NIPA table for real GDP and component growth rates.",
    ),
    "T10105": BEANIPATableDescriptor(
        table_name="T10105",
        title="Table 1.1.5. Gross Domestic Product",
        category="gdp",
        units="current dollars",
        release_cadence="quarterly GDP release cycle with annual NIPA updates",
        source_note="BEA NIPA table for current-dollar GDP and major components.",
    ),
    "T10106": BEANIPATableDescriptor(
        table_name="T10106",
        title="Table 1.1.6. Real Gross Domestic Product",
        category="gdp",
        units="chained dollars",
        release_cadence="quarterly GDP release cycle with annual NIPA updates",
        source_note="BEA NIPA table for real GDP and major components in chained dollars.",
    ),
    "T20100": BEANIPATableDescriptor(
        table_name="T20100",
        title="Table 2.1. Personal Income and Its Disposition",
        category="income",
        units="current dollars",
        release_cadence="quarterly personal income and outlays release cycle",
        source_note="BEA NIPA table for personal income, disposable personal income, and saving.",
    ),
    "T20305": BEANIPATableDescriptor(
        table_name="T20305",
        title="Table 2.3.5. Personal Consumption Expenditures by Major Type of Product",
        category="consumption",
        units="current dollars",
        release_cadence="quarterly personal income and outlays release cycle",
        source_note="BEA NIPA table for personal consumption expenditures by major product type.",
    ),
    "T61600D": BEANIPATableDescriptor(
        table_name="T61600D",
        title="Table 6.16D. Corporate Profits by Industry",
        category="profits",
        units="current dollars",
        release_cadence="quarterly corporate profits release cycle",
        source_note="BEA NIPA table for corporate profits by industry.",
    ),
}

TABLE_ALIASES = {
    "GDP": "T10105",
    "CURRENT_GDP": "T10105",
    "NOMINAL_GDP": "T10105",
    "REAL_GDP": "T10106",
    "REAL_GDP_GROWTH": "T10101",
    "GDP_GROWTH": "T10101",
    "PERSONAL_INCOME": "T20100",
    "DISPOSABLE_PERSONAL_INCOME": "T20100",
    "PCE": "T20305",
    "CONSUMPTION": "T20305",
    "PERSONAL_CONSUMPTION": "T20305",
    "CORPORATE_PROFITS": "T61600D",
    "PROFITS": "T61600D",
}


class BEANIPARequest(BaseModel):
    """Validated BEA NIPA GetData request."""

    model_config = ConfigDict(frozen=True)

    table_name: str = Field(description="Allowlisted BEA NIPA TableName value.")
    frequency: str = Field(description="BEA NIPA frequency code, currently A or Q.")
    year: str = Field(default="X", description="BEA NIPA Year value such as X, ALL, or 2024.")
    line_numbers: tuple[int, ...] | None = Field(
        default=None,
        description="Optional local filter for BEA LineNumber values.",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_input(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        normalized["table_name"] = normalize_table_name(normalized.get("table_name"))
        normalized["frequency"] = str(normalized.get("frequency") or "").strip().upper()
        normalized["year"] = normalize_year(normalized.get("year"))
        normalized["line_numbers"] = normalize_line_numbers(normalized.get("line_numbers"))
        return normalized

    @model_validator(mode="after")
    def _validate_request(self) -> "BEANIPARequest":
        if self.table_name not in ALLOWED_NIPA_TABLES:
            allowed = ", ".join(sorted(ALLOWED_NIPA_TABLES))
            raise BEADataError(f"Unsupported BEA NIPA table. Allowed tables: {allowed}.")
        descriptor = ALLOWED_NIPA_TABLES[self.table_name]
        if self.frequency not in descriptor.allowed_frequencies:
            allowed = ", ".join(descriptor.allowed_frequencies)
            raise BEADataError(
                f"Unsupported BEA NIPA frequency for {self.table_name}. Allowed: {allowed}."
            )
        return self


class BEANIPAObservation(BaseModel):
    """Normalized row returned by the BEA NIPA client and saved as CSV."""

    table_name: str
    table_title: str
    series_id: str
    concept_id: str
    line_number: int
    title: str
    time_period: str
    date: str | None
    frequency: str
    frequency_code: str
    units: str
    metric_name: str | None = None
    cl_unit: str | None = None
    unit_mult: int | None = None
    value: int | float | None
    note_ref: str | None = None
    provider: str = "BEA"
    source: str = "BEA NIPA Data API"
    source_url: str = BEA_API_URL
    release_cadence: str
    revision_policy: str
    retrieved_at: str
    response_hash: str


class BEANIPAClient:
    """Fetch allowlisted BEA NIPA tables through the BEA Data API."""

    def __init__(
        self,
        *,
        user_id: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        enabled: bool | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.user_id = (
            user_id
            if user_id is not None
            else os.getenv("BEA_API_KEY") or os.getenv("BEA_USER_ID")
        )
        self.enabled = (
            enabled
            if enabled is not None
            else os.getenv("BEA_API_ENABLED", "true").strip().lower()
            not in {"0", "false", "no", "off"}
        )
        self.session = session or requests.Session()

    def get_nipa_table(
        self,
        *,
        table_name: str,
        frequency: str = "Q",
        year: str | int | list[str | int] | tuple[str | int, ...] | None = "X",
        line_numbers: str | int | list[str | int] | tuple[str | int, ...] | None = None,
    ) -> dict[str, Any]:
        """Return normalized rows for one allowlisted BEA NIPA table."""
        if not self.enabled:
            return {
                "status": "disabled",
                "provider": "BEA Data API",
                "requires_api_key": True,
                "message": "BEA Data API is disabled by BEA_API_ENABLED=false.",
            }
        if not str(self.user_id or "").strip():
            return {
                "status": "disabled",
                "provider": "BEA Data API",
                "requires_api_key": True,
                "message": "BEA Data API requires BEA_API_KEY or BEA_USER_ID.",
            }

        request = BEANIPARequest(
            table_name=table_name,
            frequency=frequency,
            year=year,
            line_numbers=line_numbers,
        )
        descriptor = ALLOWED_NIPA_TABLES[request.table_name]
        params = self._request_params(request)
        payload = self._get_json(params={"UserID": str(self.user_id).strip(), **params})
        response_hash = _response_hash(payload)
        retrieved_at = datetime.now(UTC).isoformat()
        rows = self._normalize_payload(
            payload,
            request=request,
            descriptor=descriptor,
            retrieved_at=retrieved_at,
            response_hash=response_hash,
        )
        if not rows:
            line_suffix = f" and line filter {list(request.line_numbers)}" if request.line_numbers else ""
            raise BEADataError(
                f"BEA NIPA table {request.table_name} returned no observations{line_suffix}."
            )

        return {
            "status": "success",
            "provider": "BEA Data API",
            "source": "BEA NIPA Data API",
            "requires_api_key": True,
            "table": descriptor.model_dump(),
            "request": {
                "dataset": "NIPA",
                "table_name": request.table_name,
                "frequency": request.frequency,
                "year": request.year,
                "line_numbers": list(request.line_numbers or []),
            },
            "raw_response": payload,
            "rows": rows,
            "row_count": len(rows),
            "metadata": {
                "authentication": "BEA UserID",
                "endpoint": BEA_API_URL,
                "method": "GET",
                "request_params": params,
                "line_numbers": list(request.line_numbers or []),
                "retrieved_at": retrieved_at,
                "response_hash": response_hash,
                "freshness_policy": descriptor.revision_policy,
                "table": descriptor.model_dump(),
                "handoff_guidance": (
                    "BEA NIPA rows preserve table, line, frequency, units, release cadence, "
                    "and revision policy. Quant-developer must align frequencies explicitly."
                ),
            },
        }

    def _request_params(self, request: BEANIPARequest) -> dict[str, str]:
        return {
            "method": "GetData",
            "DataSetName": "NIPA",
            "TableName": request.table_name,
            "Frequency": request.frequency,
            "Year": request.year,
            "ResultFormat": "JSON",
        }

    def _get_json(self, *, params: dict[str, str]) -> dict[str, Any]:
        try:
            response = self.session.get(BEA_API_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as exc:
            raise BEADataError("BEA request timed out.") from exc
        except requests.RequestException as exc:
            raise BEADataError(f"BEA request failed: {exc}") from exc
        except ValueError as exc:
            raise BEADataError("BEA response was not valid JSON.") from exc
        if not isinstance(data, dict):
            raise BEADataError("BEA response was malformed: expected a JSON object.")
        return data

    def _normalize_payload(
        self,
        payload: dict[str, Any],
        *,
        request: BEANIPARequest,
        descriptor: BEANIPATableDescriptor,
        retrieved_at: str,
        response_hash: str,
    ) -> list[dict[str, Any]]:
        error_text = _bea_error_text(payload)
        if error_text:
            raise BEADataError(f"BEA API error: {error_text}")

        beaapi = payload.get("BEAAPI")
        results = beaapi.get("Results") if isinstance(beaapi, dict) else None
        data_rows = results.get("Data") if isinstance(results, dict) else None
        if isinstance(data_rows, dict):
            data_rows = [data_rows]
        if not isinstance(data_rows, list):
            raise BEADataError("BEA response was malformed: missing BEAAPI.Results.Data.")

        line_filter = set(request.line_numbers or ())
        rows: list[dict[str, Any]] = []
        for raw_row in data_rows:
            if not isinstance(raw_row, dict):
                raise BEADataError("BEA response was malformed: observation was not an object.")
            line_number = _parse_int(raw_row.get("LineNumber"))
            if line_number is None:
                raise BEADataError("BEA response was malformed: observation missing LineNumber.")
            if line_filter and line_number not in line_filter:
                continue

            time_period = str(raw_row.get("TimePeriod") or "").strip()
            if not time_period:
                raise BEADataError("BEA response was malformed: observation missing TimePeriod.")
            series_code = str(raw_row.get("SeriesCode") or f"LINE{line_number}").strip()
            title = str(raw_row.get("LineDescription") or descriptor.title).strip()
            metric_name = _clean_optional_text(raw_row.get("METRIC_NAME"))
            cl_unit = _clean_optional_text(raw_row.get("CL_UNIT"))
            observation = BEANIPAObservation(
                table_name=request.table_name,
                table_title=descriptor.title,
                series_id=f"BEA.NIPA.{request.table_name}.{series_code}.{request.frequency}",
                concept_id=series_code,
                line_number=line_number,
                title=title,
                time_period=time_period,
                date=_period_start_date(time_period),
                frequency=_frequency_label(request.frequency),
                frequency_code=request.frequency,
                units=_units(metric_name, cl_unit, descriptor.units),
                metric_name=metric_name,
                cl_unit=cl_unit,
                unit_mult=_parse_int(raw_row.get("UNIT_MULT")),
                value=_coerce_number(raw_row.get("DataValue")),
                note_ref=_clean_optional_text(raw_row.get("NoteRef")),
                release_cadence=descriptor.release_cadence,
                revision_policy=descriptor.revision_policy,
                retrieved_at=retrieved_at,
                response_hash=response_hash,
            )
            rows.append(observation.model_dump())

        rows.sort(key=lambda row: (str(row["time_period"]), int(row["line_number"])))
        return rows


def normalize_table_name(value: Any) -> str:
    text = str(value or "").strip()
    key = text.upper().replace("-", "_").replace(" ", "_")
    table_name = TABLE_ALIASES.get(key, text.upper())
    if not table_name:
        raise BEADataError("Provide a BEA NIPA table name or supported alias.")
    if not _TABLE_NAME_RE.fullmatch(table_name):
        raise BEADataError("Malformed BEA NIPA table name. Use values such as T10105.")
    return table_name


def normalize_year(value: Any) -> str:
    if value is None:
        return "X"
    if isinstance(value, (list, tuple, set)):
        parts = [str(item).strip().upper() for item in value if str(item).strip()]
    else:
        text = str(value).strip().upper()
        if not text:
            return "X"
        parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts:
        return "X"
    if len(parts) == 1 and parts[0] in _SPECIAL_YEAR_VALUES:
        return parts[0]
    if any(part in _SPECIAL_YEAR_VALUES for part in parts):
        raise BEADataError("BEA year shortcuts X and ALL cannot be mixed with years.")
    years: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not _YEAR_RE.fullmatch(part):
            raise BEADataError("BEA Year must be X, ALL, or comma-separated four-digit years.")
        year = int(part)
        if year < 1900 or year > 2100:
            raise BEADataError("BEA Year values must be between 1900 and 2100.")
        if part not in seen:
            seen.add(part)
            years.append(part)
    return ",".join(years)


def normalize_line_numbers(value: Any) -> tuple[int, ...] | None:
    if value is None:
        return None
    raw_values: list[Any]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                raw_values = parsed if isinstance(parsed, list) else [parsed]
            except Exception as exc:
                raise BEADataError("Malformed BEA line_numbers JSON list.") from exc
        else:
            raw_values = [part.strip() for part in re.split(r"[,;]", stripped) if part.strip()]
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        raw_values = [value]

    normalized: list[int] = []
    seen: set[int] = set()
    for raw in raw_values:
        line_number = _parse_int(raw)
        if line_number is None or line_number <= 0 or line_number > 999:
            raise BEADataError("BEA line_numbers must be positive integers.")
        if line_number not in seen:
            seen.add(line_number)
            normalized.append(line_number)
    return tuple(normalized) or None


def table_descriptor_to_dict(descriptor: BEANIPATableDescriptor) -> dict[str, Any]:
    return descriptor.model_dump()


def _bea_error_text(payload: dict[str, Any]) -> str | None:
    beaapi = payload.get("BEAAPI")
    if not isinstance(beaapi, dict):
        return "missing BEAAPI response object"
    for candidate in (
        beaapi.get("Error"),
        (beaapi.get("Results") or {}).get("Error") if isinstance(beaapi.get("Results"), dict) else None,
    ):
        text = _error_text(candidate)
        if text:
            return text
    return None


def _error_text(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        parts = [_error_text(item) for item in value]
        return "; ".join(part for part in parts if part) or None
    if isinstance(value, dict):
        for key in (
            "APIErrorDescription",
            "ErrorDescription",
            "Message",
            "message",
            "error",
        ):
            text = value.get(key)
            if text:
                return str(text).strip()
        return "; ".join(f"{key}={val}" for key, val in value.items() if val) or None
    return str(value).strip() or None


def _response_hash(payload: dict[str, Any]) -> str:
    return provider_payload_sha256(payload)


def _coerce_number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(",", "")
    if not text or text.upper() in {"(NA)", "(NM)", "(D)", "NA", "N/A", "--"}:
        return None
    try:
        numeric = float(text)
    except ValueError:
        return None
    if numeric.is_integer():
        return int(numeric)
    return numeric


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _clean_optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _units(metric_name: str | None, cl_unit: str | None, descriptor_units: str) -> str:
    metric = str(metric_name or "").strip()
    cl = str(cl_unit or "").strip()
    if metric and cl and cl.lower() not in {"level", metric.lower()}:
        return f"{metric}; {cl}"
    return metric or cl or descriptor_units


def _frequency_label(code: str) -> str:
    return {"A": "annual", "Q": "quarterly", "M": "monthly"}.get(code, code.lower())


def _period_start_date(time_period: str) -> str | None:
    if _YEAR_RE.fullmatch(time_period):
        return f"{time_period}-01-01"
    quarter_match = _QUARTER_RE.fullmatch(time_period)
    if quarter_match:
        year, quarter = quarter_match.groups()
        month = {"1": "01", "2": "04", "3": "07", "4": "10"}[quarter]
        return f"{year}-{month}-01"
    month_match = _MONTH_RE.fullmatch(time_period)
    if month_match:
        year, month = month_match.groups()
        return f"{year}-{month}-01"
    return None


__all__ = [
    "ALLOWED_NIPA_TABLES",
    "BEA_API_URL",
    "BEANIPAClient",
    "BEANIPAObservation",
    "BEANIPARequest",
    "BEANIPATableDescriptor",
    "BEADataError",
    "TABLE_ALIASES",
    "normalize_line_numbers",
    "normalize_table_name",
    "normalize_year",
    "table_descriptor_to_dict",
]
