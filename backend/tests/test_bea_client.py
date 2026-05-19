import pytest
import requests

from mcp_clients.bea_client import BEA_API_URL, BEANIPAClient, BEADataError


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


def _bea_payload():
    return {
        "BEAAPI": {
            "Results": {
                "Data": [
                    {
                        "TableName": "T10105",
                        "SeriesCode": "A191RC",
                        "LineNumber": "1",
                        "LineDescription": "Gross domestic product",
                        "TimePeriod": "2025Q4",
                        "METRIC_NAME": "Current Dollars",
                        "CL_UNIT": "Level",
                        "UNIT_MULT": "6",
                        "DataValue": "29,184.900",
                        "NoteRef": "T10105",
                    },
                    {
                        "TableName": "T10105",
                        "SeriesCode": "DPCERC",
                        "LineNumber": "2",
                        "LineDescription": "Personal consumption expenditures",
                        "TimePeriod": "2025Q4",
                        "METRIC_NAME": "Current Dollars",
                        "CL_UNIT": "Level",
                        "UNIT_MULT": "6",
                        "DataValue": "20,001.200",
                        "NoteRef": "T10105",
                    },
                ]
            }
        }
    }


def test_bea_client_fetches_allowlisted_nipa_table_and_filters_lines():
    session = FakeSession(FakeResponse(_bea_payload()))

    result = BEANIPAClient(user_id="test-key", session=session).get_nipa_table(
        table_name="gdp",
        frequency="Q",
        year="2025",
        line_numbers=[1],
    )

    assert result["status"] == "success"
    assert result["provider"] == "BEA Data API"
    assert result["requires_api_key"] is True
    assert result["raw_response"] == _bea_payload()
    assert result["request"] == {
        "dataset": "NIPA",
        "table_name": "T10105",
        "frequency": "Q",
        "year": "2025",
        "line_numbers": [1],
    }
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["series_id"] == "BEA.NIPA.T10105.A191RC.Q"
    assert row["concept_id"] == "A191RC"
    assert row["line_number"] == 1
    assert row["time_period"] == "2025Q4"
    assert row["date"] == "2025-10-01"
    assert row["value"] == 29184.9
    assert row["units"] == "Current Dollars"
    assert row["unit_mult"] == 6
    assert row["release_cadence"]
    assert row["revision_policy"]
    assert len(row["response_hash"]) == 64
    assert result["metadata"]["response_hash"] == row["response_hash"]
    assert result["metadata"]["method"] == "GET"
    assert result["metadata"]["freshness_policy"] == row["revision_policy"]
    assert session.calls == [
        {
            "url": BEA_API_URL,
            "params": {
                "UserID": "test-key",
                "method": "GetData",
                "DataSetName": "NIPA",
                "TableName": "T10105",
                "Frequency": "Q",
                "Year": "2025",
                "ResultFormat": "JSON",
            },
            "timeout": 20,
        }
    ]


def test_bea_client_returns_disabled_payload_without_api_key_or_network_call():
    session = FakeSession()

    result = BEANIPAClient(user_id="", session=session).get_nipa_table(table_name="T10105")

    assert result["status"] == "disabled"
    assert result["provider"] == "BEA Data API"
    assert result["requires_api_key"] is True
    assert session.calls == []


def test_bea_client_rejects_unsupported_table_before_network_call():
    session = FakeSession()

    with pytest.raises(BEADataError) as exc_info:
        BEANIPAClient(user_id="test-key", session=session).get_nipa_table(
            table_name="T99999",
            frequency="Q",
        )

    assert "Unsupported BEA NIPA table" in str(exc_info.value)
    assert "T10105" in str(exc_info.value)
    assert session.calls == []


def test_bea_client_surfaces_provider_error_payload():
    session = FakeSession(
        FakeResponse(
            {
                "BEAAPI": {
                    "Error": {
                        "APIErrorCode": "1",
                        "APIErrorDescription": "Invalid request parameters.",
                    }
                }
            }
        )
    )

    with pytest.raises(BEADataError) as exc_info:
        BEANIPAClient(user_id="test-key", session=session).get_nipa_table(table_name="T10105")

    assert "Invalid request parameters" in str(exc_info.value)


def test_bea_client_surfaces_malformed_provider_response():
    session = FakeSession(FakeResponse({"unexpected": "shape"}))

    with pytest.raises(BEADataError) as exc_info:
        BEANIPAClient(user_id="test-key", session=session).get_nipa_table(table_name="T10105")

    assert "missing BEAAPI" in str(exc_info.value)


def test_bea_client_surfaces_network_timeout():
    session = FakeSession(error=requests.Timeout("connect timed out"))

    with pytest.raises(BEADataError) as exc_info:
        BEANIPAClient(user_id="test-key", session=session).get_nipa_table(table_name="T10105")

    assert "timed out" in str(exc_info.value)
