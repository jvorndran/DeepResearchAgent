"""Shared SEC EDGAR company-facts provenance contract."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping


SEC_COMPANY_FACT_PROVENANCE_SCHEMA_COLUMN: Final = "sec_provenance_schema_version"
SEC_COMPANY_FACT_PROVENANCE_SCHEMA_NAME: Final = "sec_company_facts_v1"
SEC_COMPANY_FACT_PROVENANCE_SCHEMA_VERSION: Final = 1
SEC_COMPANY_FACT_SOURCE_PREFIX: Final = "sec_company_facts.latest_fundamentals."

SEC_COMPANY_FACT_PROVENANCE_FIELDS: Final = (
    "taxonomy",
    "concept",
    "unit",
    "fiscal_period",
    "form",
    "filed",
    "accession_number",
    "start",
    "end",
)

SEC_COMPANY_FACT_REQUIRED_PROVENANCE_FIELDS: Final = (
    "taxonomy",
    "concept",
    "unit",
    "fiscal_period",
    "form",
    "filed",
    "accession_number",
    "end",
)

SEC_COMPANY_FACT_RAW_METRIC_COLUMNS: Final = (
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
)

SEC_COMPANY_FACT_METRIC_COMPONENTS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "revenue_b": ("revenue",),
        "net_income_b": ("net_income",),
        "gross_margin_pct": ("gross_profit", "revenue"),
        "operating_margin_pct": ("operating_income", "revenue"),
        "net_margin_pct": ("net_income", "revenue"),
        "operating_cash_flow_b": ("operating_cash_flow",),
        "free_cash_flow_b": ("operating_cash_flow", "capital_expenditures"),
        "cash_and_securities_b": (
            "cash_and_equivalents",
            "marketable_securities_current",
        ),
        "long_term_debt_b": ("long_term_debt",),
        "assets_b": ("assets",),
        "liabilities_b": ("liabilities",),
        "diluted_eps": ("diluted_eps",),
        "revenue_growth_pct": ("revenue_start", "revenue_end"),
        "revenue_cagr_pct": ("revenue_start", "revenue_end"),
    }
)


@dataclass(frozen=True)
class SECCompanyFactProvenanceContract:
    schema_name: str
    schema_version: int
    schema_version_column: str
    source_prefix: str
    fields: tuple[str, ...]
    required_fields: tuple[str, ...]
    raw_metric_columns: tuple[str, ...]
    metric_components: Mapping[str, tuple[str, ...]]

    def components_for_metric(self, metric: str | None) -> tuple[str, ...]:
        cleaned = str(metric or "").strip()
        if not cleaned:
            return ()
        return self.metric_components.get(cleaned, (cleaned,))


SEC_COMPANY_FACT_PROVENANCE_CONTRACT: Final = SECCompanyFactProvenanceContract(
    schema_name=SEC_COMPANY_FACT_PROVENANCE_SCHEMA_NAME,
    schema_version=SEC_COMPANY_FACT_PROVENANCE_SCHEMA_VERSION,
    schema_version_column=SEC_COMPANY_FACT_PROVENANCE_SCHEMA_COLUMN,
    source_prefix=SEC_COMPANY_FACT_SOURCE_PREFIX,
    fields=SEC_COMPANY_FACT_PROVENANCE_FIELDS,
    required_fields=SEC_COMPANY_FACT_REQUIRED_PROVENANCE_FIELDS,
    raw_metric_columns=SEC_COMPANY_FACT_RAW_METRIC_COLUMNS,
    metric_components=SEC_COMPANY_FACT_METRIC_COMPONENTS,
)
