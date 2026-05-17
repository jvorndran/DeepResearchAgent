import pytest
import requests

from mcp_clients.census_client import (
    CENSUS_API_BASE_URL,
    CENSUS_QUERY_LIMIT_PER_IP_PER_DAY,
    CensusVariableInfo,
    CensusDataError,
    CensusPublicDataClient,
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
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if self.error:
            raise self.error
        return self.response


def test_census_client_parses_two_dimensional_state_table_no_key_payload():
    session = FakeSession(
        FakeResponse(
            [
                ["NAME", "DP05_0001E", "DP03_0062E", "state"],
                ["California", "39200000", "95521", "06"],
                ["Texas", "30500000", "76600", "48"],
            ]
        )
    )

    result = CensusPublicDataClient(session=session).get_table(
        dataset="2023/acs/acs5/profile",
        variables=["population", "median_income"],
        geography="state",
    )

    assert result["status"] == "success"
    assert result["provider"] == "Census Data API"
    assert result["requires_api_key"] is False
    assert result["rows"][0]["NAME"] == "California"
    assert result["rows"][0]["DP05_0001E"] == 39200000
    assert result["rows"][0]["DP03_0062E"] == 95521
    assert result["metadata"]["variables"]["DP03_0062E"]["concept"] == "income"
    assert result["metadata"]["query_limits"]["no_key_queries_per_ip_per_day"] == (
        CENSUS_QUERY_LIMIT_PER_IP_PER_DAY
    )
    assert "500 queries per IP per day" in result["metadata"]["query_limits"]["warning"]
    assert session.calls == [
        {
            "url": f"{CENSUS_API_BASE_URL}/2023/acs/acs5/profile",
            "params": {"get": "NAME,DP05_0001E,DP03_0062E", "for": "state:*"},
            "timeout": 20,
        }
    ]


def test_census_client_supports_county_geography_with_state_filter():
    session = FakeSession(
        FakeResponse(
            [
                ["NAME", "DP04_0001E", "state", "county"],
                ["Los Angeles County, California", "3510000", "06", "037"],
            ]
        )
    )

    result = CensusPublicDataClient(session=session).get_table(
        dataset="2023/acs/acs5/profile",
        variables="housing_units",
        geography="county",
        state="06",
    )

    assert result["rows"][0]["county"] == "037"
    assert session.calls[0]["params"] == {
        "get": "NAME,DP04_0001E",
        "for": "county:*",
        "in": "state:06",
    }


def test_census_client_rejects_queries_over_50_variables_including_name_before_network_call(
    monkeypatch,
):
    session = FakeSession()
    fake_variables = {
        f"DP99_{index:04d}E": CensusVariableInfo(
            variable=f"DP99_{index:04d}E",
            label=f"Fake variable {index}",
            concept="test",
            units="count",
        )
        for index in range(50)
    }
    monkeypatch.setattr("mcp_clients.census_client.ALLOWED_CENSUS_VARIABLES", fake_variables)

    with pytest.raises(CensusDataError) as exc_info:
        CensusPublicDataClient(session=session).get_table(
            dataset="2023/acs/acs5/profile",
            variables=list(fake_variables),
            geography="state",
        )

    assert "limited to 50 variables including NAME" in str(exc_info.value)
    assert session.calls == []


def test_census_client_rejects_bad_geography_before_network_call():
    session = FakeSession()

    with pytest.raises(CensusDataError) as exc_info:
        CensusPublicDataClient(session=session).get_table(
            dataset="2023/acs/acs5/profile",
            variables=["population"],
            geography="tract",
        )

    assert "Allowed geographies: state, county" in str(exc_info.value)
    assert session.calls == []


def test_census_client_surfaces_malformed_two_dimensional_table():
    session = FakeSession(FakeResponse([["NAME", "DP05_0001E"], ["California"]]))

    with pytest.raises(CensusDataError) as exc_info:
        CensusPublicDataClient(session=session).get_table(
            dataset="2023/acs/acs5/profile",
            variables=["population"],
            geography="state",
        )

    assert "row width did not match header" in str(exc_info.value)


def test_census_client_classifies_requests_json_decode_as_invalid_json():
    session = FakeSession(FakeResponse(requests.exceptions.JSONDecodeError("bad json", "", 0)))

    with pytest.raises(CensusDataError) as exc_info:
        CensusPublicDataClient(session=session).get_table(
            dataset="2023/acs/acs5/profile",
            variables=["population"],
            geography="state",
        )

    assert str(exc_info.value) == "Census response was not valid JSON."


def test_census_client_returns_disabled_payload_without_network_call():
    session = FakeSession()

    result = CensusPublicDataClient(session=session, enabled=False).get_table(
        dataset="2023/acs/acs5/profile",
        variables=["population"],
        geography="state",
    )

    assert result["status"] == "disabled"
    assert result["provider"] == "Census Data API"
    assert session.calls == []


def test_census_client_surfaces_network_timeout():
    session = FakeSession(error=requests.Timeout("connect timed out"))

    with pytest.raises(CensusDataError) as exc_info:
        CensusPublicDataClient(session=session).get_table(
            dataset="2023/acs/acs5/profile",
            variables=["population"],
            geography="state",
        )

    assert "timed out" in str(exc_info.value)
