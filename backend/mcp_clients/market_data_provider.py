"""Typed market-data provider contract.

The first implementation is intentionally availability-only. It gives the
pipeline a durable contract for valuation coverage without implying that a live
market-data backend is configured.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MARKET_VALUATION_SOURCE_ID = "valuation_market_data"
MARKET_DATA_PROVIDER_LABEL = "Market Data Provider"
MARKET_DATA_PROVIDER_SOURCE = "disabled_market_data_provider"
MARKET_DATA_UNAVAILABLE_REASON = (
    "No live market-data provider is configured; FMP, OpenBB direct calls, "
    "paid/keyed quote feeds, analyst-estimate feeds, and revision feeds are disabled."
)

MarketDataCapabilityName = Literal[
    "price",
    "market_cap",
    "valuation_multiples",
    "analyst_estimates",
    "estimate_revisions",
]
MarketDataAvailabilityStatus = Literal["available", "not_available"]
MarketDataDiagnosticLevel = Literal["info", "warning", "error"]

DEFAULT_MARKET_DATA_CAPABILITIES: tuple[MarketDataCapabilityName, ...] = (
    "price",
    "market_cap",
    "valuation_multiples",
    "analyst_estimates",
    "estimate_revisions",
)

_CAPABILITY_LABELS: dict[MarketDataCapabilityName, str] = {
    "price": "stock price",
    "market_cap": "market capitalization",
    "valuation_multiples": "valuation multiples",
    "analyst_estimates": "analyst estimates",
    "estimate_revisions": "estimate revisions",
}


class MarketDataCapability(BaseModel):
    """Availability for one market/valuation data family."""

    model_config = ConfigDict(frozen=True)

    name: MarketDataCapabilityName
    label: str
    status: MarketDataAvailabilityStatus = "not_available"
    reason: str

    @field_validator("label", "reason")
    @classmethod
    def _text_required(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("market-data capability text fields must be non-empty")
        return text


class MarketDataDiagnostic(BaseModel):
    """Compact provider diagnostic preserved in tool metadata and source coverage."""

    model_config = ConfigDict(frozen=True)

    level: MarketDataDiagnosticLevel = "info"
    code: str
    message: str

    @field_validator("code", "message")
    @classmethod
    def _text_required(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("market-data diagnostics must include code and message")
        return text


class MarketDataSourceDescriptor(BaseModel):
    """Source-coverage descriptor for valuation market data."""

    model_config = ConfigDict(frozen=True)

    source_id: Literal["valuation_market_data"] = MARKET_VALUATION_SOURCE_ID
    provider: str = MARKET_DATA_PROVIDER_LABEL
    source: str = MARKET_DATA_PROVIDER_SOURCE
    status: MarketDataAvailabilityStatus = "not_available"
    reason: str
    limitation: str
    capabilities: list[MarketDataCapability] = Field(min_length=1)
    capability_list: list[MarketDataCapabilityName] = Field(min_length=1)
    requires_provider_config: bool = True
    provider_configured: bool = False

    @field_validator("provider", "source", "reason", "limitation")
    @classmethod
    def _text_required(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("market-data source descriptor text fields must be non-empty")
        return text

    @model_validator(mode="after")
    def _capability_list_matches_capabilities(self) -> "MarketDataSourceDescriptor":
        names = [capability.name for capability in self.capabilities]
        if sorted(names) != sorted(self.capability_list):
            raise ValueError("capability_list must match capabilities[].name")
        return self


class MarketDataAvailabilityResponse(BaseModel):
    """Availability response returned by market provider implementations."""

    model_config = ConfigDict(frozen=True)

    status: MarketDataAvailabilityStatus = "not_available"
    provider: str = MARKET_DATA_PROVIDER_LABEL
    identifier: str | None = None
    requested_capabilities: list[MarketDataCapabilityName] = Field(min_length=1)
    source_descriptor: MarketDataSourceDescriptor
    diagnostics: list[MarketDataDiagnostic] = Field(default_factory=list)

    @field_validator("provider")
    @classmethod
    def _provider_required(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("provider must be non-empty")
        return text

    @property
    def source_coverage(self) -> dict[str, Any]:
        """Return the execution_summary.source_coverage fragment."""

        return {
            MARKET_VALUATION_SOURCE_ID: self.source_descriptor.model_dump(
                mode="json",
                exclude_none=True,
            )
        }


class MarketDataProvider(Protocol):
    """Provider interface for market/valuation availability checks."""

    def get_valuation_availability(
        self,
        *,
        identifier: str | None = None,
        requested_capabilities: Iterable[Any] | None = None,
    ) -> MarketDataAvailabilityResponse:
        """Return availability metadata for market valuation data."""


class DisabledMarketDataProvider:
    """Deterministic availability-only market-data provider."""

    def get_valuation_availability(
        self,
        *,
        identifier: str | None = None,
        requested_capabilities: Iterable[Any] | None = None,
    ) -> MarketDataAvailabilityResponse:
        capabilities = normalize_market_data_capabilities(requested_capabilities)
        capability_models = [
            MarketDataCapability(
                name=capability,
                label=_CAPABILITY_LABELS[capability],
                reason=MARKET_DATA_UNAVAILABLE_REASON,
            )
            for capability in capabilities
        ]
        source_descriptor = MarketDataSourceDescriptor(
            reason=MARKET_DATA_UNAVAILABLE_REASON,
            limitation=(
                "Market price, market capitalization, valuation multiples, analyst "
                "estimates, and estimate revisions are unavailable from the current "
                "public-data toolset."
            ),
            capabilities=capability_models,
            capability_list=list(capabilities),
        )
        diagnostics = [
            MarketDataDiagnostic(
                code="market_data_provider_not_configured",
                message=MARKET_DATA_UNAVAILABLE_REASON,
            )
        ]
        cleaned_identifier = str(identifier).strip().upper() if identifier else None
        return MarketDataAvailabilityResponse(
            identifier=cleaned_identifier or None,
            requested_capabilities=list(capabilities),
            source_descriptor=source_descriptor,
            diagnostics=diagnostics,
        )


def normalize_market_data_capabilities(
    requested_capabilities: Iterable[Any] | None,
) -> tuple[MarketDataCapabilityName, ...]:
    """Return supported market-data capabilities in canonical order."""

    requested = {
        str(capability).strip().lower()
        for capability in requested_capabilities or []
        if str(capability).strip()
    }
    if not requested:
        return DEFAULT_MARKET_DATA_CAPABILITIES
    return tuple(
        capability
        for capability in DEFAULT_MARKET_DATA_CAPABILITIES
        if capability in requested
    ) or DEFAULT_MARKET_DATA_CAPABILITIES


__all__ = [
    "DEFAULT_MARKET_DATA_CAPABILITIES",
    "DisabledMarketDataProvider",
    "MARKET_DATA_PROVIDER_LABEL",
    "MARKET_DATA_PROVIDER_SOURCE",
    "MARKET_DATA_UNAVAILABLE_REASON",
    "MARKET_VALUATION_SOURCE_ID",
    "MarketDataAvailabilityResponse",
    "MarketDataAvailabilityStatus",
    "MarketDataCapability",
    "MarketDataCapabilityName",
    "MarketDataDiagnostic",
    "MarketDataProvider",
    "MarketDataSourceDescriptor",
    "normalize_market_data_capabilities",
]
