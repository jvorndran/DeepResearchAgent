import json

from agents.data_engineer import tools


def test_market_get_valuation_availability_returns_source_coverage_contract():
    payload = tools.market_get_valuation_availability.func(
        identifier="NVDA",
        requested_capabilities='["price", "valuation_multiples"]',
    )
    result = json.loads(payload)

    assert result["status"] == "not_available"
    assert result["identifier"] == "NVDA"
    assert result["requested_capabilities"] == ["price", "valuation_multiples"]
    assert result["metadata"]["data_type"] == "market_valuation_availability"
    assert result["metadata"]["provider_configured"] is False
    coverage = result["source_coverage"]["valuation_market_data"]
    assert coverage["status"] == "not_available"
    assert coverage["limitation"]
    assert coverage["reason"]
    assert coverage["capability_list"] == ["price", "valuation_multiples"]
    assert "data_files" not in result
    assert "save_data" in result["metadata"]["handoff_guidance"]
