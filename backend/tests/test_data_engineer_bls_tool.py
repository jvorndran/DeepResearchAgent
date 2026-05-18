import json
from types import SimpleNamespace

from agents.data_engineer import tools
from agents.data_engineer.provider_retry import normalize_bls_no_key_year_window
from mcp_clients.bls_client import BLSPublicDataError


class FakeBLSClient:
    def get_series(self, series_ids, *, start_year=None, end_year=None):
        year = int(end_year or 2025)
        return {
            "status": "success",
            "provider": "BLS Public Data",
            "series": [
                {
                    "series_id": "LNS14000000",
                    "metadata": {
                        "series_id": "LNS14000000",
                        "title": "Unemployment Rate",
                        "source": "BLS Public Data API",
                    },
                    "observations": [
                        {
                            "date": f"{year}-12-01",
                            "year": year,
                            "period": "M12",
                            "value": "4.1",
                        }
                    ],
                }
            ],
        }


class FakeBLSDailyQuotaClient:
    def get_series(self, series_ids, *, start_year=None, end_year=None):
        raise BLSPublicDataError(
            "BLS API error: Request could not be serviced, as the daily threshold "
            "for total number of requests allocated to the user with registration key  "
            "has been reached."
        )


class FakeBLSWideWindowClient:
    def get_series(self, series_ids, *, start_year=None, end_year=None):
        raise BLSPublicDataError("BLS no-key requests are limited to 10 years per call.")


class FakeBLSRecordingClient:
    def __init__(self):
        self.calls = []

    def get_series(self, series_ids, *, start_year=None, end_year=None):
        self.calls.append(
            {"series_ids": series_ids, "start_year": start_year, "end_year": end_year}
        )
        return {
            "status": "success",
            "provider": "BLS Public Data",
            "series": [
                {
                    "series_id": "CUSR0000SA0",
                    "metadata": {
                        "series_id": "CUSR0000SA0",
                        "title": "Consumer Price Index for All Urban Consumers",
                        "source": "BLS Public Data API",
                    },
                    "observations": [
                        {
                            "date": f"{int(end_year)}-12-01",
                            "year": int(end_year),
                            "period": "M12",
                            "value": "315.0",
                        }
                    ],
                }
            ],
        }


def test_bls_year_window_infers_missing_end_then_bounds_to_no_key_window():
    start, end, metadata = normalize_bls_no_key_year_window(
        2000,
        None,
        current_year=2025,
    )

    assert (start, end) == (2016, 2025)
    assert metadata["requested_year_window"] == {"start_year": 2000, "end_year": None}
    assert metadata["applied_year_window"] == {"start_year": 2016, "end_year": 2025}
    assert metadata["window_adjustment"] == [
        "inferred_end_year",
        "bounded_to_no_key_window",
    ]


def test_bls_get_series_uses_distinct_paths_for_split_year_windows(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(tools, "BLSPublicDataClient", lambda: FakeBLSClient())
    monkeypatch.setattr(tools, "DATA_STORAGE_DIR", tmp_path)
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-bls"))

    first = json.loads(
        tools.bls_get_series.func(
            series_ids=["LNS14000000"],
            start_year=2000,
            end_year=2009,
            runtime=runtime,
        )
    )
    second = json.loads(
        tools.bls_get_series.func(
            series_ids=["LNS14000000"],
            start_year=2010,
            end_year=2019,
            runtime=runtime,
        )
    )

    first_path = first["data_files"]["LNS14000000"]
    second_path = second["data_files"]["LNS14000000"]
    assert first_path.endswith("LNS14000000_bls_public_2000_2009_job-bls.csv")
    assert second_path.endswith("LNS14000000_bls_public_2010_2019_job-bls.csv")
    assert first_path != second_path
    assert (tmp_path / "job-bls" / "LNS14000000_bls_public_2000_2009_job-bls.csv").exists()
    assert (tmp_path / "job-bls" / "LNS14000000_bls_public_2010_2019_job-bls.csv").exists()


def test_bls_get_series_normalizes_wide_no_key_window_before_client_call(
    tmp_path, monkeypatch
):
    fake_client = FakeBLSRecordingClient()
    monkeypatch.setattr(tools, "BLSPublicDataClient", lambda: fake_client)
    monkeypatch.setattr(tools, "DATA_STORAGE_DIR", tmp_path)
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-bls"))

    result = json.loads(
        tools.bls_get_series.func(
            series_ids=["CUSR0000SA0"],
            start_year=2000,
            end_year=2025,
            runtime=runtime,
        )
    )

    assert fake_client.calls == [
        {"series_ids": ["CUSR0000SA0"], "start_year": 2016, "end_year": 2025}
    ]
    assert result["status"] == "success"
    assert result["data_files"]["CUSR0000SA0"].endswith(
        "CUSR0000SA0_bls_public_2016_2025_job-bls.csv"
    )
    assert result["metadata"]["requested_year_window"] == {
        "start_year": 2000,
        "end_year": 2025,
    }
    assert result["metadata"]["applied_year_window"] == {
        "start_year": 2016,
        "end_year": 2025,
    }
    assert "use FRED for long-history macro coverage" in result["metadata"]["coverage_note"]


def test_bls_get_series_marks_daily_quota_as_terminal(monkeypatch):
    monkeypatch.setattr(tools, "BLSPublicDataClient", lambda: FakeBLSDailyQuotaClient())
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-bls"))

    result = json.loads(
        tools.bls_get_series.func(
            series_ids=["LNS14000000"],
            start_year=2015,
            end_year=2024,
            runtime=runtime,
        )
    )

    assert result["status"] == "error"
    assert result["retryable"] is False
    assert result["error_type"] == "provider_quota_exhausted"
    assert result["retry_scope"] == "none"
    assert "daily no-key quota is exhausted" in result["hint"]
    assert "Do not retry BLS in this run" in result["hint"]


def test_bls_get_series_surfaces_client_window_errors_as_correctable(monkeypatch):
    monkeypatch.setattr(tools, "BLSPublicDataClient", lambda: FakeBLSWideWindowClient())
    runtime = SimpleNamespace(context=SimpleNamespace(job_id="job-bls"))

    result = json.loads(
        tools.bls_get_series.func(
            series_ids=["LNS14000000"],
            start_year=2000,
            end_year=2024,
            runtime=runtime,
        )
    )

    assert result["status"] == "error"
    assert result["retryable"] is True
    assert result["error_type"] == "correctable_parameters"
    assert result["retry_scope"] == "corrected_parameters"
    assert "10 years or less" in result["hint"]
