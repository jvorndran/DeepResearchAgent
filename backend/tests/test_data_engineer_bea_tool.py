import json
from types import SimpleNamespace

from agents.data_engineer import tools
from mcp_clients.bea_client import BEADataError


class FakeBEAClient:
    def get_nipa_table(self, *, table_name, frequency="Q", year="X", line_numbers=None):
        return {
            "status": "success",
            "provider": "BEA Data API",
            "table": {
                "table_name": "T10105",
                "title": "Table 1.1.5. Gross Domestic Product",
                "category": "gdp",
                "units": "current dollars",
                "allowed_frequencies": ["A", "Q"],
                "release_cadence": "quarterly GDP release cycle with annual NIPA updates",
                "revision_policy": "Latest available BEA NIPA estimates; subject to revisions.",
                "source_note": "BEA NIPA current-dollar GDP table.",
            },
            "request": {
                "dataset": "NIPA",
                "table_name": "T10105",
                "frequency": "Q",
                "year": "2025",
                "line_numbers": [1],
            },
            "rows": [
                {
                    "table_name": "T10105",
                    "table_title": "Table 1.1.5. Gross Domestic Product",
                    "series_id": "BEA.NIPA.T10105.A191RC.Q",
                    "concept_id": "A191RC",
                    "line_number": 1,
                    "title": "Gross domestic product",
                    "time_period": "2025Q4",
                    "date": "2025-10-01",
                    "frequency": "quarterly",
                    "frequency_code": "Q",
                    "units": "Current Dollars",
                    "unit_mult": 6,
                    "value": 29184.9,
                    "provider": "BEA",
                    "source": "BEA NIPA Data API",
                    "source_url": "https://apps.bea.gov/api/data",
                    "release_cadence": "quarterly GDP release cycle with annual NIPA updates",
                    "revision_policy": "Latest available BEA NIPA estimates; subject to revisions.",
                    "retrieved_at": "2026-05-19T00:00:00+00:00",
                    "response_hash": "a" * 64,
                }
            ],
            "raw_response": {"BEAAPI": {"Results": {"Data": [{"LineNumber": "1"}]}}},
            "metadata": {
                "endpoint": "https://apps.bea.gov/api/data",
                "method": "GET",
                "request_params": {
                    "method": "GetData",
                    "DataSetName": "NIPA",
                    "TableName": "T10105",
                    "Frequency": "Q",
                    "Year": "2025",
                    "ResultFormat": "JSON",
                },
                "line_numbers": [1],
                "retrieved_at": "2026-05-19T00:00:00+00:00",
                "response_hash": "a" * 64,
                "freshness_policy": "Latest available BEA NIPA estimates; subject to revisions.",
            },
        }


class FakeBEAParameterErrorClient:
    def get_nipa_table(self, *, table_name, frequency="Q", year="X", line_numbers=None):
        raise BEADataError("Unsupported BEA NIPA table. Allowed tables: T10105.")


def test_bea_get_nipa_table_saves_rows_and_returns_data_files_contract(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(tools, "BEANIPAClient", lambda: FakeBEAClient())
    monkeypatch.setattr(tools, "DATA_STORAGE_DIR", tmp_path)
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-bea"))

    payload = tools.bea_get_nipa_table.func(
        table_name="gdp",
        frequency="Q",
        year="2025",
        line_numbers="1",
        runtime=runtime,
    )
    result = json.loads(payload)

    assert result["status"] == "success"
    data_key = "BEA_NIPA_T10105_Q_lines_1"
    assert result["data_files"][data_key].endswith(
        "bea_nipa_t10105_q_2025_lines_1_job-bea.csv"
    )
    snapshot = result["source_snapshots"][data_key]
    assert snapshot["provider"] == "BEA"
    assert snapshot["source_keys"] == [data_key]
    assert snapshot["path"].endswith(".json")
    assert (tmp_path / "job-bea" / "source_snapshots").exists()
    assert result["row_counts"] == {data_key: 1}
    assert result["metadata"]["requires_api_key"] is True
    assert result["metadata"]["data_type"] == "bea_nipa_table"
    assert result["metadata"]["source_descriptor"]["revision_policy"]
    csv_text = (tmp_path / "job-bea" / "bea_nipa_t10105_q_2025_lines_1_job-bea.csv").read_text(
        encoding="utf-8"
    )
    assert "BEA.NIPA.T10105.A191RC.Q" in csv_text
    assert "quarterly GDP release cycle" in csv_text
    assert "Latest available BEA NIPA estimates" in csv_text


def test_bea_get_nipa_table_marks_parameter_errors_correctable(monkeypatch):
    monkeypatch.setattr(tools, "BEANIPAClient", lambda: FakeBEAParameterErrorClient())
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-bea"))

    payload = tools.bea_get_nipa_table.func(
        table_name="T99999",
        frequency="Q",
        runtime=runtime,
    )
    result = json.loads(payload)

    assert result["status"] == "error"
    assert result["provider"] == "BEA Data API"
    assert result["retryable"] is True
    assert result["error_type"] == "correctable_parameters"
    assert result["retry_scope"] == "corrected_parameters"
    assert "Retry at most once" in result["hint"]
