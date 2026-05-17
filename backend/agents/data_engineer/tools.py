"""LangChain tools for save_data and extract_schema."""

from typing import Any, Dict, Optional
import json
from pathlib import Path

import pandas as pd
from langchain_core.tools import tool
from langchain.tools import ToolRuntime

from core.context import ResearchContext
from mcp_clients.bls_client import (
    BLSPublicDataClient,
    BLSPublicDataError,
    search_known_bls_series,
)
from mcp_clients.census_client import CensusDataError, CensusPublicDataClient
from mcp_clients.sec_edgar_client import SECEdgarClient, SECEdgarError
from mcp_clients.worldbank_client import WorldBankDataError, WorldBankIndicatorsClient

from .provider_retry import (
    bls_error_response,
    census_error_response,
    normalize_bls_no_key_year_window,
)
from .storage import _run_async, _save_data_to_storage
from .paths import DATA_STORAGE_DIR


def _summarize_existing_csv_pointers(
    data: str,
    job_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> dict[str, Any] | None:
    """Return metadata for already-persisted CSV pointers without re-saving them."""
    if not isinstance(data, str) or not any(key in data for key in ('"file_path"', '"data_files"')):
        return None
    try:
        pointer = json.loads(data)
    except Exception:
        return None

    pointer_paths: dict[str, str] = {}
    file_path = pointer.get("file_path")
    if isinstance(file_path, str):
        pointer_paths["file_path"] = file_path

    data_files = pointer.get("data_files")
    if isinstance(data_files, dict):
        pointer_paths.update(
            {
                str(name): path
                for name, path in data_files.items()
                if isinstance(name, str) and isinstance(path, str)
            }
        )

    if not pointer_paths:
        return None

    storage_root = DATA_STORAGE_DIR.resolve()
    summaries: dict[str, dict[str, Any]] = {}
    for name, pointer_path in pointer_paths.items():
        candidate_path = Path(pointer_path)
        if not candidate_path.is_absolute():
            candidate_path = DATA_STORAGE_DIR / job_id / candidate_path
        candidate_path = candidate_path.resolve()

        try:
            if not candidate_path.is_relative_to(storage_root):
                return None
        except ValueError:
            return None
        if not candidate_path.exists() or candidate_path.suffix.lower() != ".csv":
            return None

        df = pd.read_csv(candidate_path)
        summaries[name] = {
            "storage_path": candidate_path.as_posix(),
            "row_count": len(df),
            "columns": df.columns.tolist(),
            "size_bytes": candidate_path.stat().st_size,
        }

    if not summaries:
        return None

    if set(summaries) == {"file_path"}:
        result = {
            **summaries["file_path"],
            "note": "Input file was already persisted; returned canonical path without re-saving.",
        }
    else:
        result = {
            "data_files": {
                name: summary["storage_path"] for name, summary in summaries.items()
            },
            "row_counts": {name: summary["row_count"] for name, summary in summaries.items()},
            "schema_summary": {name: summary["columns"] for name, summary in summaries.items()},
            "size_bytes": {name: summary["size_bytes"] for name, summary in summaries.items()},
            "note": "Input data_files were already persisted; returned canonical paths without re-saving.",
        }
    if metadata:
        result.update(metadata)
    return result


@tool
def save_data(
    data: str,
    ticker: str,
    data_type: str,
    runtime: ToolRuntime[ResearchContext],
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Save unsaved tool output to managed CSV storage.

    Use this only when a successful fetch did not already return a saved
    `file_path` or `data_files` pointer. This tool writes managed CSV files only;
    it does not create arbitrary output paths, JSON exports, or renamed copies.
    Never call it after FRED `status:auto_saved`, BLS, Census, World Bank, or
    SEC EDGAR tool results that already include canonical saved paths.

    The job_id is automatically read from runtime context — do NOT pass it as an argument.

    Args:
        data: JSON string returned by any MCP tool, or a pointer JSON string
        ticker: Stock ticker, FRED series ID, or other identifier (e.g., "AAPL", "UNRATE", "SP500")
        data_type: Descriptive type of data (e.g., "income_statement", "unemployment_rate", "cpi_monthly")
        metadata: Optional metadata to include (date ranges, source, units, etc.)

    Returns:
        JSON string with storage path and metadata (NOT the raw data)
    """
    job_id = runtime.context.job_id

    async def _save():
        already_saved = _summarize_existing_csv_pointers(data, job_id, metadata)
        if already_saved:
            return already_saved

        # Create file path
        file_name = f"{ticker}_{data_type}_{job_id}.csv"
        file_path = DATA_STORAGE_DIR / job_id / file_name

        # Save data
        meta = await _save_data_to_storage(data, file_path)

        # Add additional metadata if provided
        if metadata:
            meta.update(metadata)

        return meta

    try:
        result = _run_async(_save())

        return json.dumps({"status": "success", "ticker": ticker, "data_type": data_type, **result})
    except Exception as e:
        return json.dumps(
            {"status": "error", "error": str(e), "message": f"Failed to save data for {ticker}"}
        )


@tool
def extract_schema(file_paths: str | list[str]) -> str:
    """
    Extract compact schemas from saved data files.

    This is DETERMINISTIC - uses pure pandas to extract column names, types,
    row counts, date ranges, and short source metadata. No LLM guessing.

    Use this tool after fetching data to understand the structure of the data
    files before passing them to the code generation agent.

    Args:
        file_paths: List of paths to CSV or JSON data files

    Returns:
        JSON string with schemas for each file. Each schema contains:
        - file_path: Original storage path
        - columns: List of exact column names
        - dtypes: Dictionary mapping column names to data types
        - row_count: Number of rows
        - shape: Tuple of (num_rows, num_columns)
        - date_min/date_max when a date column exists
        - metadata: Compact non-row metadata useful for downstream handoffs
    """
    if isinstance(file_paths, str):
        try:
            import json as _json

            file_paths = _json.loads(file_paths)
            if not isinstance(file_paths, list):
                file_paths = [str(file_paths)]
        except Exception:
            file_paths = [file_paths]
    if not isinstance(file_paths, list):
        file_paths = [str(file_paths)]

    schemas = {}

    for file_path in file_paths:
        try:
            df = pd.read_csv(file_path)
            metadata: dict[str, str] = {}
            for col in (
                "series_id",
                "title",
                "units",
                "frequency",
                "seasonal_adjustment",
                "source",
            ):
                if col not in df.columns:
                    continue
                value = df[col].dropna().astype(str)
                if value.empty:
                    continue
                text = value.iloc[0]
                metadata[col] = text[:240] + "..." if len(text) > 240 else text

            schema = {
                "file_path": file_path,
                "columns": df.columns.tolist(),
                "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
                "row_count": int(len(df)),
                "shape": list(df.shape),
                "metadata": metadata,
            }
            if "date" in df.columns:
                dates = pd.to_datetime(df["date"], errors="coerce").dropna()
                if not dates.empty:
                    schema["date_min"] = dates.min().date().isoformat()
                    schema["date_max"] = dates.max().date().isoformat()
            schemas[file_path] = schema

        except Exception as e:
            schemas[file_path] = {"status": "error", "error": str(e)}

    return json.dumps({"status": "success", "schemas": schemas})


def _parse_bls_series_ids(series_ids: str | list[str]) -> list[str]:
    if isinstance(series_ids, str):
        stripped = series_ids.strip()
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except Exception:
                pass
        return [part.strip() for part in stripped.split(",") if part.strip()]
    return [str(item) for item in series_ids]


@tool
def bls_search_known_series(query: str, limit: int = 8) -> str:
    """
    Search a tiny curated map of useful BLS public series.

    This is an offline helper for common labor, wage, CPI/PPI, employment, and
    productivity series. Use it before `bls_get_series` when the direct BLS ID is
    unknown. It does not call paid providers and requires no key.

    Args:
        query: Search terms such as "unemployment", "payrolls", "CPI", or "wages".
        limit: Maximum number of candidates to return.

    Returns:
        JSON string with candidate BLS series metadata.
    """
    try:
        candidates = search_known_bls_series(query, limit=limit)
        return json.dumps(
            {
                "status": "success",
                "provider": "BLS Public Data",
                "query": query,
                "candidates": candidates,
                "metadata": {"source": "curated local BLS series map", "requires_api_key": False},
            }
        )
    except Exception as e:
        return json.dumps(
            {
                "status": "error",
                "provider": "BLS Public Data",
                "error": f"BLS curated-series search failed: {e}",
                "hint": "Use a known BLS series ID or fall back to FRED for macro coverage.",
            }
        )


@tool
def bls_get_series(
    series_ids: str | list[str],
    runtime: ToolRuntime[ResearchContext],
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
) -> str:
    """
    Fetch and save BLS Public Data API v1 series with no API key.

    Use for direct BLS source checks on labor, wages, CPI/PPI, employment, and
    productivity series. The no-key public endpoint has a bounded year window;
    use multiple focused calls rather than requesting long histories. Set
    BLS_PUBLIC_API_ENABLED=false to disable this optional integration gracefully.

    Args:
        series_ids: A BLS series ID, comma-separated IDs, or JSON list of IDs.
        start_year: Optional inclusive start year. Partial or over-wide windows
            are normalized to a 10-year-or-smaller no-key direct-source check.
        end_year: Optional inclusive end year. Partial or over-wide windows
            are normalized to a 10-year-or-smaller no-key direct-source check.

    Returns:
        JSON string with saved CSV paths, row counts, BLS metadata, or compact errors.
    """
    try:
        parsed_ids = _parse_bls_series_ids(series_ids)
        applied_start_year, applied_end_year, window_metadata = normalize_bls_no_key_year_window(
            start_year,
            end_year,
        )
        result = BLSPublicDataClient().get_series(
            parsed_ids,
            start_year=applied_start_year,
            end_year=applied_end_year,
        )
        if result.get("status") != "success":
            return json.dumps(result)

        job_id = runtime.context.job_id
        data_files: dict[str, str] = {}
        row_counts: dict[str, int] = {}
        metadata: dict[str, Any] = {
            "data_type": "bls_public_series",
            "source": "BLS Public Data API",
            "requires_api_key": False,
            "series": {},
        }
        if window_metadata:
            metadata.update(window_metadata)

        for series in result["series"]:
            series_id = series["series_id"]
            window_suffix = ""
            if applied_start_year is not None and applied_end_year is not None:
                window_suffix = f"_{int(applied_start_year)}_{int(applied_end_year)}"
            file_path = (
                DATA_STORAGE_DIR
                / job_id
                / f"{series_id}_bls_public{window_suffix}_{job_id}.csv"
            )
            rows = []
            series_metadata = series.get("metadata", {})
            for observation in series.get("observations", []):
                row = dict(observation)
                for key, value in series_metadata.items():
                    if not isinstance(value, (list, dict)):
                        row[key] = value
                rows.append(row)
            saved = _run_async(_save_data_to_storage(rows, file_path))
            data_files[series_id] = saved["storage_path"]
            row_counts[series_id] = int(saved["row_count"])
            metadata["series"][series_id] = series_metadata

        return json.dumps(
            {
                "status": "success",
                "provider": "BLS Public Data",
                "data_files": data_files,
                "row_counts": row_counts,
                "metadata": metadata,
            }
        )
    except BLSPublicDataError as e:
        return json.dumps(bls_error_response(str(e)))
    except Exception as e:
        return json.dumps(
            {
                "status": "error",
                "provider": "BLS Public Data",
                "error": f"Unexpected BLS client error: {e}",
                "retryable": False,
                "hint": "Report BLS unavailable instead of switching to paid providers.",
            }
        )


@tool
def census_get_table(
    dataset: str,
    variables: str | list[str],
    geography: str,
    runtime: ToolRuntime[ResearchContext],
    state: Optional[str] = None,
) -> str:
    """
    Fetch and save an allowlisted no-key Census Data API ACS table.

    Use for state/county demographic, income, population, or housing context in
    regional macro reports. This optional integration requires no key and is
    limited to allowlisted ACS profile variables/geographies. Set
    CENSUS_PUBLIC_API_ENABLED=false to disable it gracefully.

    Args:
        dataset: Allowlisted Census dataset path, currently "2023/acs/acs5/profile".
        variables: Census variables or aliases, e.g. population, median_income, housing_units.
        geography: "state" or "county".
        state: Optional two-digit state FIPS filter for county geography.

    Returns:
        JSON string with saved CSV path, row count, Census metadata, or compact errors.
    """
    try:
        result = CensusPublicDataClient().get_table(
            dataset=dataset,
            variables=variables,
            geography=geography,
            state=state,
        )
        if result.get("status") != "success":
            return json.dumps(result)

        job_id = runtime.context.job_id
        dataset_slug = dataset.replace("/", "_")
        geography_slug = str(result["geography"]).replace(" ", "_")
        file_path = (
            DATA_STORAGE_DIR / job_id / f"census_{dataset_slug}_{geography_slug}_{job_id}.csv"
        )
        saved = _run_async(_save_data_to_storage(result["rows"], file_path))

        return json.dumps(
            {
                "status": "success",
                "provider": "Census Data API",
                "data_files": {"census_table": saved["storage_path"]},
                "row_counts": {"census_table": int(saved["row_count"])},
                "metadata": {
                    "data_type": "census_public_table",
                    "source": "Census Data API",
                    "requires_api_key": False,
                    "dataset": result["dataset"],
                    "geography": result["geography"],
                    "variables": result["metadata"]["variables"],
                    "query_limits": result["metadata"]["query_limits"],
                },
            }
        )
    except CensusDataError as e:
        return json.dumps(census_error_response(str(e)))
    except Exception as e:
        return json.dumps(
            {
                "status": "error",
                "provider": "Census Data API",
                "error": f"Unexpected Census client error: {e}",
                "retryable": False,
                "hint": "Report Census unavailable instead of switching to paid providers.",
            }
        )


def _parse_worldbank_country_codes(country_codes: str | list[str]) -> list[str]:
    if isinstance(country_codes, str):
        stripped = country_codes.strip()
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except Exception:
                pass
        return [part.strip() for part in stripped.replace(";", ",").split(",") if part.strip()]
    return [str(item) for item in list(country_codes or [])]


@tool
def worldbank_get_indicator(
    country_codes: str | list[str],
    indicator: str,
    runtime: ToolRuntime[ResearchContext],
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
) -> str:
    """
    Fetch and save a no-key World Bank annual macro indicator.

    Use for cross-country annual inflation or GDP-growth comparisons, especially
    when pairing non-US countries with FRED US monthly/quarterly context. Scope is
    intentionally narrow: allowlisted countries are USA, CAN, DEU, JPN, and MEX;
    allowlisted indicators are inflation (`FP.CPI.TOTL.ZG`) and real GDP growth
    (`NY.GDP.MKTP.KD.ZG`). Set WORLD_BANK_API_ENABLED=false to disable gracefully.

    Args:
        country_codes: ISO2/ISO3 country codes, aliases, comma-separated list, or JSON list.
        indicator: World Bank indicator code or alias such as inflation or gdp_growth.
        start_year: Optional inclusive start year. Must be paired with end_year.
        end_year: Optional inclusive end year. Must be paired with start_year.

    Returns:
        JSON string with saved CSV path, row count, World Bank metadata, or compact errors.
    """
    try:
        parsed_countries = _parse_worldbank_country_codes(country_codes)
        result = WorldBankIndicatorsClient().get_indicator(
            country_codes=parsed_countries,
            indicator=indicator,
            start_year=start_year,
            end_year=end_year,
        )
        if result.get("status") != "success":
            return json.dumps(result)

        job_id = runtime.context.job_id
        indicator_id = result["indicator"]["indicator_id"]
        indicator_slug = indicator_id.lower().replace(".", "_")
        country_slug = "_".join(result["countries"].keys()).lower()
        file_path = (
            DATA_STORAGE_DIR / job_id / f"worldbank_{indicator_slug}_{country_slug}_{job_id}.csv"
        )
        saved = _run_async(_save_data_to_storage(result["observations"], file_path))

        return json.dumps(
            {
                "status": "success",
                "provider": "World Bank Indicators API",
                "data_files": {indicator_id: saved["storage_path"]},
                "row_counts": {indicator_id: int(saved["row_count"])},
                "metadata": {
                    "data_type": "worldbank_annual_indicator",
                    "source": "World Bank Indicators API",
                    "requires_api_key": False,
                    "indicator": result["indicator"],
                    "countries": result["countries"],
                    "year_window": result["metadata"]["year_window"],
                    "handoff_guidance": result["metadata"]["handoff_guidance"],
                },
            }
        )
    except WorldBankDataError as e:
        message = str(e)
        return json.dumps(
            {
                "status": "error",
                "provider": "World Bank Indicators API",
                "error": message,
                "retryable": any(
                    token in message.lower()
                    for token in ("timed out", "request failed", "rate", "limit", "too many")
                ),
                "hint": (
                    "Use countries USA, CAN, DEU, JPN, or MEX and indicators "
                    "inflation/FP.CPI.TOTL.ZG or gdp_growth/NY.GDP.MKTP.KD.ZG; "
                    "pair annual World Bank data with FRED US context carefully."
                ),
            }
        )
    except Exception as e:
        return json.dumps(
            {
                "status": "error",
                "provider": "World Bank Indicators API",
                "error": f"Unexpected World Bank client error: {e}",
                "retryable": False,
                "hint": "Report World Bank unavailable instead of switching to paid providers.",
            }
        )


@tool
def sec_fetch_company_facts(
    identifier: str,
    runtime: ToolRuntime[ResearchContext],
    periods: int = 5,
) -> str:
    """
    Fetch and save compact public-company fundamentals from SEC EDGAR.

    Uses only SEC no-key public endpoints (`data.sec.gov` companyfacts and submissions,
    plus SEC ticker mapping). Returns common annual company facts including revenue,
    net income, gross profit, operating income, operating cash flow, capital
    expenditures, R&D expense, SG&A expense, diluted EPS, cash, securities, debt,
    equity, assets, liabilities, shares, recent 10-K/10-Q filing metadata, SEC
    source metadata, and a parsed fundamentals CSV path. Missing concepts remain
    blank. Set SEC_EDGAR_ENABLED=false to disable this optional integration
    gracefully.

    Args:
        identifier: Stock ticker (for example "AAPL") or 1-10 digit CIK.
        periods: Number of fiscal years / recent filings to return, capped at 10.

    Returns:
        JSON string with saved CSV path, row count, metadata, and compact errors.
    """
    try:
        bounded_periods = max(1, min(int(periods), 10))
    except Exception:
        bounded_periods = 5

    try:
        result = SECEdgarClient().get_company_facts(identifier=identifier, periods=bounded_periods)
        if result.get("status") != "success":
            return json.dumps(result)

        job_id = runtime.context.job_id
        ticker = str(result.get("ticker") or identifier).upper()
        file_path = DATA_STORAGE_DIR / job_id / f"{ticker}_sec_edgar_company_facts_{job_id}.csv"
        saved = _run_async(_save_data_to_storage(result.get("fundamentals", []), file_path))

        schema_columns = [
            column
            for column in (
                "fiscal_year",
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
                "debt_current",
                "long_term_debt",
                "stockholders_equity",
                "assets",
                "liabilities",
                "shares",
                "period_end",
                "form",
            )
            if column in saved["columns"]
        ]

        return json.dumps(
            {
                "status": "success",
                "provider": "SEC EDGAR",
                "data_files": {"sec_company_facts": saved["storage_path"]},
                "row_counts": {"sec_company_facts": int(saved["row_count"])},
                "schema_summary": {"sec_company_facts": schema_columns},
                "metadata": {
                    "data_type": "sec_edgar_company_facts",
                    "source": "SEC data.sec.gov companyfacts and submissions APIs",
                    "requires_api_key": False,
                    "identifier": identifier,
                    "ticker": ticker,
                    "cik": result.get("cik"),
                    "company_name": result.get("company_name"),
                    "filings": result.get("filings", []),
                    "handoff_guidance": "Use data_files.sec_company_facts directly; do not call save_data or create JSON copies.",
                },
            }
        )
    except SECEdgarError as e:
        return json.dumps(
            {
                "status": "error",
                "provider": "SEC EDGAR",
                "identifier": identifier,
                "error": str(e),
                "retryable": "timed out" in str(e).lower() or "request failed" in str(e).lower(),
                "hint": "Use a valid ticker/CIK, reduce periods, or report SEC EDGAR unavailable.",
            }
        )
    except Exception as e:
        return json.dumps(
            {
                "status": "error",
                "provider": "SEC EDGAR",
                "identifier": identifier,
                "error": f"Unexpected SEC EDGAR client error: {e}",
                "retryable": False,
                "hint": "Report SEC EDGAR unavailable instead of switching to paid providers.",
            }
        )
