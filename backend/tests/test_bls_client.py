import pytest
import requests

from mcp_clients.bls_client import (
    BLS_V1_URL,
    BLSPublicDataClient,
    BLSPublicDataError,
    search_known_bls_series,
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

    def post(self, url, json, timeout):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if self.error:
            raise self.error
        return self.response


def _series_payload(series_id, value="4.1"):
    return {
        "seriesID": series_id,
        "data": [
            {
                "year": "2025",
                "period": "M12",
                "periodName": "December",
                "value": value,
                "footnotes": [{}],
            }
        ],
    }


def test_bls_client_fetches_single_series_no_key_payload():
    session = FakeSession(
        FakeResponse(
            {
                "status": "REQUEST_SUCCEEDED",
                "Results": {"series": [_series_payload("LNS14000000")]},
            }
        )
    )

    result = BLSPublicDataClient(session=session).get_series(
        "LNS14000000", start_year=2024, end_year=2025
    )

    assert result["status"] == "success"
    assert result["provider"] == "BLS Public Data"
    assert result["requires_api_key"] is False
    assert result["series"][0]["series_id"] == "LNS14000000"
    assert result["series"][0]["metadata"]["title"] == "Unemployment Rate"
    assert result["series"][0]["observations"][0]["value"] == "4.1"
    assert session.calls == [
        {
            "url": BLS_V1_URL,
            "json": {
                "seriesid": ["LNS14000000"],
                "startyear": "2024",
                "endyear": "2025",
            },
            "timeout": 20,
        }
    ]


def test_bls_client_fetches_multi_series_response():
    session = FakeSession(
        FakeResponse(
            {
                "status": "REQUEST_SUCCEEDED",
                "Results": {
                    "series": [
                        _series_payload("LNS14000000", "4.1"),
                        _series_payload("CES0000000001", "159000"),
                    ]
                },
            }
        )
    )

    result = BLSPublicDataClient(session=session).get_series(
        ["LNS14000000", "CES0000000001"], start_year=2025, end_year=2025
    )

    assert [series["series_id"] for series in result["series"]] == [
        "LNS14000000",
        "CES0000000001",
    ]
    assert result["series"][1]["metadata"]["category"] == "employment"
    assert session.calls[0]["json"]["seriesid"] == ["LNS14000000", "CES0000000001"]


def test_bls_client_validates_no_key_year_window_before_network_call():
    session = FakeSession()

    with pytest.raises(BLSPublicDataError) as exc_info:
        BLSPublicDataClient(session=session).get_series(
            "LNS14000000", start_year=2010, end_year=2025
        )

    assert "limited to 10 years" in str(exc_info.value)
    assert session.calls == []


def test_bls_client_surfaces_rate_limit_or_provider_error_payload():
    session = FakeSession(
        FakeResponse(
            {
                "status": "REQUEST_NOT_PROCESSED",
                "message": ["Daily query limit exceeded. Please try again tomorrow."],
            }
        )
    )

    with pytest.raises(BLSPublicDataError) as exc_info:
        BLSPublicDataClient(session=session).get_series(
            "LNS14000000", start_year=2025, end_year=2025
        )

    assert "Daily query limit exceeded" in str(exc_info.value)


def test_bls_client_surfaces_malformed_provider_response():
    session = FakeSession(FakeResponse({"status": "REQUEST_SUCCEEDED", "Results": {}}))

    with pytest.raises(BLSPublicDataError) as exc_info:
        BLSPublicDataClient(session=session).get_series(
            "LNS14000000", start_year=2025, end_year=2025
        )

    assert "missing Results.series" in str(exc_info.value)


def test_bls_client_returns_disabled_payload_without_network_call():
    session = FakeSession()

    result = BLSPublicDataClient(session=session, enabled=False).get_series("LNS14000000")

    assert result["status"] == "disabled"
    assert result["provider"] == "BLS Public Data"
    assert session.calls == []


def test_bls_client_surfaces_network_timeout():
    session = FakeSession(error=requests.Timeout("connect timed out"))

    with pytest.raises(BLSPublicDataError) as exc_info:
        BLSPublicDataClient(session=session).get_series("LNS14000000")

    assert "timed out" in str(exc_info.value)


def test_search_known_bls_series_returns_curated_metadata_without_network():
    results = search_known_bls_series("payroll jobs")

    assert results[0]["series_id"] == "CES0000000001"
    assert results[0]["source"] == "BLS Public Data API"


def test_search_known_bls_series_distinguishes_hourly_and_weekly_wage_metadata():
    hourly = search_known_bls_series("production nonsupervisory hourly earnings")
    weekly = search_known_bls_series("production nonsupervisory weekly earnings")

    assert hourly[0]["series_id"] == "CES0500000008"
    assert hourly[0]["units"] == "dollars per hour"
    assert weekly[0]["series_id"] == "CES0500000030"
    assert weekly[0]["units"] == "dollars per week"


def test_bls_client_direct_fetch_preserves_known_weekly_wage_units():
    session = FakeSession(
        FakeResponse(
            {
                "status": "REQUEST_SUCCEEDED",
                "Results": {"series": [_series_payload("CES0500000030", "1072.67")]},
            }
        )
    )

    result = BLSPublicDataClient(session=session).get_series(
        "CES0500000030", start_year=2025, end_year=2025
    )

    metadata = result["series"][0]["metadata"]
    assert metadata["title"].startswith("Average Weekly Earnings")
    assert metadata["units"] == "dollars per week"
