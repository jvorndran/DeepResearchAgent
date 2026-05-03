import os

import pytest

from mcp_clients.worldbank_client import WorldBankDataError, WorldBankIndicatorsClient


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_INTEGRATION_TESTS") != "1",
    reason="live World Bank smoke tests are opt-in",
)


def test_worldbank_live_smoke_fetches_one_indicator_shape():
    try:
        result = WorldBankIndicatorsClient(timeout=10).get_indicator(
            country_codes=["USA"],
            indicator="gdp_growth",
            start_year=2022,
            end_year=2023,
        )
    except WorldBankDataError as exc:
        pytest.fail(f"World Bank live smoke unavailable: {exc}")

    assert result["status"] == "success"
    assert result["requires_api_key"] is False
    assert result["indicator"]["indicator_id"] == "NY.GDP.MKTP.KD.ZG"
    assert result["observations"]
    assert result["observations"][0]["source"] == "World Bank Indicators API"
