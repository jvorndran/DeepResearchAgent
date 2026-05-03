import pytest
import requests

from mcp_clients.worldbank_client import (
    WORLD_BANK_INDICATOR_URL,
    WorldBankDataError,
    WorldBankIndicatorsClient,
)


class FakeResponse:
    def __init__(self, payload, status_error=None):
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if self.error:
            raise self.error
        return self.responses.pop(0)


def _observation(country_code, country_name, year, value, indicator_id="FP.CPI.TOTL.ZG"):
    return {
        "indicator": {"id": indicator_id, "value": "Inflation, consumer prices (annual %)"},
        "country": {"id": country_code[:2], "value": country_name},
        "countryiso3code": country_code,
        "date": str(year),
        "value": value,
    }


def test_worldbank_client_fetches_paginated_indicator_no_key_payload():
    session = FakeSession(
        [
            FakeResponse(
                [
                    {"page": 1, "pages": 2, "per_page": 1, "total": 2},
                    [_observation("USA", "United States", 2023, "4.1")],
                ]
            ),
            FakeResponse(
                [
                    {"page": 2, "pages": 2, "per_page": 1, "total": 2},
                    [_observation("CAN", "Canada", 2023, "3.9")],
                ]
            ),
        ]
    )

    result = WorldBankIndicatorsClient(session=session).get_indicator(
        country_codes=["US", "Canada"],
        indicator="inflation",
        start_year=2022,
        end_year=2023,
    )

    assert result["status"] == "success"
    assert result["provider"] == "World Bank Indicators API"
    assert result["requires_api_key"] is False
    assert result["indicator"]["indicator_id"] == "FP.CPI.TOTL.ZG"
    assert result["countries"]["USA"]["name"] == "United States"
    assert result["observations"] == [
        {
            "country_code": "CAN",
            "country_name": "Canada",
            "indicator_id": "FP.CPI.TOTL.ZG",
            "indicator_name": "Inflation, consumer prices (annual %)",
            "year": 2023,
            "value": 3.9,
            "units": "annual percent change",
            "frequency": "annual",
            "source": "World Bank Indicators API",
        },
        {
            "country_code": "USA",
            "country_name": "United States",
            "indicator_id": "FP.CPI.TOTL.ZG",
            "indicator_name": "Inflation, consumer prices (annual %)",
            "year": 2023,
            "value": 4.1,
            "units": "annual percent change",
            "frequency": "annual",
            "source": "World Bank Indicators API",
        },
    ]
    assert "annual" in result["metadata"]["handoff_guidance"]
    assert "FRED" in result["metadata"]["handoff_guidance"]
    assert session.calls == [
        {
            "url": WORLD_BANK_INDICATOR_URL.format(
                countries="USA;CAN", indicator="FP.CPI.TOTL.ZG"
            ),
            "params": {"format": "json", "per_page": "1000", "page": "1", "date": "2022:2023"},
            "timeout": 20,
        },
        {
            "url": WORLD_BANK_INDICATOR_URL.format(
                countries="USA;CAN", indicator="FP.CPI.TOTL.ZG"
            ),
            "params": {"format": "json", "per_page": "1000", "page": "2", "date": "2022:2023"},
            "timeout": 20,
        },
    ]


def test_worldbank_client_rejects_missing_country_before_network_call():
    session = FakeSession()

    with pytest.raises(WorldBankDataError) as exc_info:
        WorldBankIndicatorsClient(session=session).get_indicator(
            country_codes=["France"],
            indicator="inflation",
        )

    assert "Unsupported World Bank country" in str(exc_info.value)
    assert "USA" in str(exc_info.value)
    assert session.calls == []


def test_worldbank_client_rejects_missing_indicator_before_network_call():
    session = FakeSession()

    with pytest.raises(WorldBankDataError) as exc_info:
        WorldBankIndicatorsClient(session=session).get_indicator(
            country_codes=["USA"],
            indicator="population",
        )

    assert "Unsupported World Bank indicator" in str(exc_info.value)
    assert "NY.GDP.MKTP.KD.ZG" in str(exc_info.value)
    assert session.calls == []


def test_worldbank_client_returns_disabled_payload_without_network_call():
    session = FakeSession()

    result = WorldBankIndicatorsClient(session=session, enabled=False).get_indicator(
        country_codes=["USA"],
        indicator="gdp_growth",
    )

    assert result["status"] == "disabled"
    assert result["provider"] == "World Bank Indicators API"
    assert session.calls == []


def test_worldbank_client_surfaces_malformed_provider_response():
    session = FakeSession([FakeResponse({"unexpected": "shape"})])

    with pytest.raises(WorldBankDataError) as exc_info:
        WorldBankIndicatorsClient(session=session).get_indicator(
            country_codes=["USA"],
            indicator="inflation",
        )

    assert "expected [metadata, observations]" in str(exc_info.value)


def test_worldbank_client_surfaces_network_timeout():
    session = FakeSession(error=requests.Timeout("connect timed out"))

    with pytest.raises(WorldBankDataError) as exc_info:
        WorldBankIndicatorsClient(session=session).get_indicator(
            country_codes=["USA"],
            indicator="inflation",
        )

    assert "timed out" in str(exc_info.value)
