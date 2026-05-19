import pytest
from pydantic import ValidationError

from mcp_clients.market_data_provider import (
    DEFAULT_MARKET_DATA_CAPABILITIES,
    DisabledMarketDataProvider,
    MarketDataSourceDescriptor,
    normalize_market_data_capabilities,
)


def test_disabled_market_data_provider_returns_typed_unavailable_coverage():
    response = DisabledMarketDataProvider().get_valuation_availability(
        identifier="msft",
        requested_capabilities=["price", "market_cap"],
    )

    assert response.status == "not_available"
    assert response.identifier == "MSFT"
    assert response.requested_capabilities == ["price", "market_cap"]
    coverage = response.source_coverage["valuation_market_data"]
    assert coverage["status"] == "not_available"
    assert coverage["reason"]
    assert coverage["limitation"]
    assert coverage["capability_list"] == ["price", "market_cap"]
    assert [capability["name"] for capability in coverage["capabilities"]] == [
        "price",
        "market_cap",
    ]


def test_market_data_capabilities_default_when_unknown_or_empty():
    assert normalize_market_data_capabilities([]) == DEFAULT_MARKET_DATA_CAPABILITIES
    assert normalize_market_data_capabilities(["unknown"]) == DEFAULT_MARKET_DATA_CAPABILITIES


def test_market_data_source_descriptor_requires_capabilities():
    with pytest.raises(ValidationError):
        MarketDataSourceDescriptor(
            reason="disabled",
            limitation="disabled",
            capabilities=[],
            capability_list=[],
        )
