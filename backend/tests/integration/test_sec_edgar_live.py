import os

import pytest

from mcp_clients.sec_edgar_client import SECEdgarClient, SECEdgarError


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_INTEGRATION_TESTS") != "1",
    reason="live no-key SEC EDGAR smoke tests require RUN_LIVE_INTEGRATION_TESTS=1",
)


def test_sec_edgar_live_aapl_company_facts_shape():
    client = SECEdgarClient(user_agent="DeepResearchAgent live-test contact@example.invalid")

    try:
        result = client.get_company_facts("AAPL", periods=3)
    except SECEdgarError as exc:
        pytest.fail(f"SEC EDGAR live smoke failed separately from mocked contract tests: {exc}")

    assert result["status"] == "success"
    assert result["provider"] == "SEC EDGAR"
    assert result["ticker"] == "AAPL"
    assert result["cik"] == "0000320193"
    assert result["metadata"]["requires_api_key"] is False
    assert len(result["fundamentals"]) >= 3

    required_fields = {
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
        "stockholders_equity",
        "assets",
        "liabilities",
        "shares",
    }
    for row in result["fundamentals"][:3]:
        assert required_fields.issubset(row)
        assert row["revenue_concept"]
        assert row["revenue_end"]
        assert row["net_income_end"] == row["revenue_end"]
