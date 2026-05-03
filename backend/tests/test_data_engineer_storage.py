import json

import pytest

from agents.data_engineer.tools import extract_schema
from agents.data_engineer import tools as data_engineer_tools
from agents.data_engineer.storage import _save_data_to_storage


@pytest.mark.asyncio
async def test_save_data_to_storage_returns_absolute_path(tmp_path):
    file_path = tmp_path / "data" / "UNRATE.csv"

    result = await _save_data_to_storage(
        [{"date": "2026-03-01", "value": "4.2"}],
        file_path,
    )

    assert result["storage_path"] == file_path.resolve().as_posix()
    assert file_path.exists()


def test_extract_schema_returns_compact_metadata_without_sample_rows(tmp_path):
    file_path = tmp_path / "fred.csv"
    long_notes = "Long source note. " * 80
    file_path.write_text(
        "date,value,series_id,title,units,frequency,source,notes\n"
        f"2024-01-01,100.0,CPIAUCSL,Consumer Price Index,Index,Monthly,FRED,{long_notes}\n"
        f"2024-02-01,101.0,CPIAUCSL,Consumer Price Index,Index,Monthly,FRED,{long_notes}\n"
    )

    payload = json.loads(extract_schema.invoke({"file_paths": file_path.as_posix()}))
    schema = payload["schemas"][file_path.as_posix()]

    assert schema["columns"] == [
        "date",
        "value",
        "series_id",
        "title",
        "units",
        "frequency",
        "source",
        "notes",
    ]
    assert schema["row_count"] == 2
    assert schema["date_min"] == "2024-01-01"
    assert schema["date_max"] == "2024-02-01"
    assert schema["metadata"]["series_id"] == "CPIAUCSL"
    assert schema["metadata"]["source"] == "FRED"
    assert "sample_rows" not in schema
    assert "notes" not in schema["metadata"]
    assert long_notes not in json.dumps(payload)


def test_existing_data_files_pointer_returns_canonical_paths_without_resave(tmp_path, monkeypatch):
    monkeypatch.setattr(data_engineer_tools, "DATA_STORAGE_DIR", tmp_path)
    job_id = "job-123"
    canonical_path = tmp_path / job_id / "AAPL_sec_edgar_company_facts_job-123.csv"
    canonical_path.parent.mkdir(parents=True)
    canonical_path.write_text(
        "fiscal_year,revenue,net_income,assets,liabilities,shares\n"
        "2024,391035000000,93736000000,364980000000,308030000000,15343783000\n"
    )

    result = data_engineer_tools._summarize_existing_csv_pointers(
        json.dumps({"data_files": {"sec_company_facts": canonical_path.as_posix()}}),
        job_id,
    )

    assert result is not None
    assert result["data_files"] == {"sec_company_facts": canonical_path.as_posix()}
    assert result["row_counts"] == {"sec_company_facts": 1}
    assert result["schema_summary"]["sec_company_facts"] == [
        "fiscal_year",
        "revenue",
        "net_income",
        "assets",
        "liabilities",
        "shares",
    ]
    assert "without re-saving" in result["note"]


def test_existing_auto_file_path_pointer_can_reference_storage_auto_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(data_engineer_tools, "DATA_STORAGE_DIR", tmp_path)
    job_id = "job-123"
    canonical_path = tmp_path / "_auto" / "fred_get_series_CPIAUCSL.csv"
    canonical_path.parent.mkdir(parents=True)
    canonical_path.write_text("date,value,series_id\n2024-01-01,100.0,CPIAUCSL\n")

    result = data_engineer_tools._summarize_existing_csv_pointers(
        json.dumps({"status": "auto_saved", "file_path": canonical_path.as_posix()}),
        job_id,
    )

    assert result is not None
    assert result["storage_path"] == canonical_path.as_posix()
    assert result["row_count"] == 1
    assert result["columns"] == ["date", "value", "series_id"]
    assert "without re-saving" in result["note"]
