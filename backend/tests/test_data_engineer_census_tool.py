import json
from types import SimpleNamespace

from agents.data_engineer import tools


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
