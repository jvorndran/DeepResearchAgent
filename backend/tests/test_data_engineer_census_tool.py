import json
from types import SimpleNamespace

from agents.data_engineer import tools
from mcp_clients.census_client import CensusDataError


class FakeCensusClient:
    def get_table(self, *, dataset, variables, geography, state=None):
        return {
            "status": "success",
            "provider": "Census Data API",
            "dataset": dataset,
            "geography": geography,
            "rows": [{"NAME": "California", "DP05_0001E": 39200000, "state": "06"}],
            "metadata": {
                "variables": {
                    "DP05_0001E": {
                        "variable": "DP05_0001E",
                        "label": "Total population",
                        "concept": "demographics",
                        "units": "count",
                    }
                },
                "query_limits": {
                    "max_variables_per_query": 50,
                    "no_key_queries_per_ip_per_day": 500,
                    "warning": "No-key Census API use is limited to 500 queries per IP per day.",
                },
            },
        }


class FakeCensusMalformedPayloadClient:
    def get_table(self, *, dataset, variables, geography, state=None):
        raise CensusDataError("Census response was not valid JSON.")


class FakeCensusParameterErrorClient:
    def get_table(self, *, dataset, variables, geography, state=None):
        raise CensusDataError("State geography does not accept a state filter.")


def test_census_get_table_saves_rows_and_returns_data_files_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "CensusPublicDataClient", lambda: FakeCensusClient())
    monkeypatch.setattr(tools, "DATA_STORAGE_DIR", tmp_path)
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-census"))

    payload = tools.census_get_table.func(
        dataset="2023/acs/acs5/profile",
        variables=["population"],
        geography="state",
        runtime=runtime,
    )
    result = json.loads(payload)

    assert result["status"] == "success"
    assert result["data_files"]["census_table"].endswith(
        "census_2023_acs_acs5_profile_state_job-census.csv"
    )
    assert result["row_counts"] == {"census_table": 1}
    assert result["metadata"]["requires_api_key"] is False
    assert result["metadata"]["query_limits"]["no_key_queries_per_ip_per_day"] == 500


def test_census_get_table_marks_malformed_provider_payload_terminal(monkeypatch):
    monkeypatch.setattr(
        tools,
        "CensusPublicDataClient",
        lambda: FakeCensusMalformedPayloadClient(),
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-census"))

    payload = tools.census_get_table.func(
        dataset="2023/acs/acs5/profile",
        variables=["population", "median_income"],
        geography="state",
        runtime=runtime,
    )
    result = json.loads(payload)

    assert result["status"] == "error"
    assert result["retryable"] is False
    assert result["error_type"] == "provider_payload_unusable"
    assert result["retry_scope"] == "none"
    assert "Do not retry Census by narrowing variables" in result["hint"]
    assert "metadata.fetch_errors" in result["hint"]


def test_census_get_table_marks_parameter_errors_correctable(monkeypatch):
    monkeypatch.setattr(
        tools,
        "CensusPublicDataClient",
        lambda: FakeCensusParameterErrorClient(),
    )
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-census"))

    payload = tools.census_get_table.func(
        dataset="2023/acs/acs5/profile",
        variables=["population"],
        geography="state",
        state="06",
        runtime=runtime,
    )
    result = json.loads(payload)

    assert result["status"] == "error"
    assert result["retryable"] is True
    assert result["error_type"] == "correctable_parameters"
    assert result["retry_scope"] == "corrected_parameters"
    assert "Retry at most once" in result["hint"]
