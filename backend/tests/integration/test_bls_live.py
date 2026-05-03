import os

import pytest

from mcp_clients.bls_client import BLSPublicDataClient, BLSPublicDataError, BLS_V1_URL


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_INTEGRATION_TESTS") != "1",
    reason="live no-key BLS smoke tests require RUN_LIVE_INTEGRATION_TESTS=1",
)


def test_bls_live_unemployment_rate_shape():
    client = BLSPublicDataClient()

    try:
        result = client.get_series("LNS14000000", start_year=2025, end_year=2025)
    except BLSPublicDataError as exc:
        pytest.fail(f"BLS live smoke failed separately from mocked contract tests: {exc}")

    assert result["status"] == "success"
    assert result["provider"] == "BLS Public Data"
    assert result["requires_api_key"] is False
    assert result["metadata"]["authentication"] == "none"
    assert result["metadata"]["endpoint"] == BLS_V1_URL

    series = result["series"][0]
    assert series["series_id"] == "LNS14000000"
    assert series["metadata"]["title"] == "Unemployment Rate"
    assert series["metadata"]["source"] == "BLS Public Data API"
    assert series["row_count"] >= 1
    assert {"year", "period", "value", "series_id"}.issubset(series["observations"][0])
