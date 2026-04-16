import asyncio
import json
from pathlib import Path

import pandas as pd
import pytest

from agents import data_engineer as de


def _workspace_storage_dir(tmp_path: Path) -> Path:
    storage_dir = Path.cwd() / ".pytest-tmp" / tmp_path.name
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


def test_normalize_mcp_tuple_spills_structured_content_to_csv(monkeypatch, tmp_path):
    monkeypatch.setattr(de, "DATA_STORAGE_DIR", _workspace_storage_dir(tmp_path))

    result = (
        [{"type": "text", "text": "FRED series data fetched."}],
        {
            "structured_content": {
                "series_id": "GDPC1",
                "units": "Billions of Chained 2017 Dollars",
                "data": [
                    {"date": "2024-01-01", "value": 100.0},
                    {"date": "2024-04-01", "value": 101.5},
                    {"date": "2024-07-01", "value": 102.25},
                ],
            }
        },
    )

    compact_content, compact_artifact = asyncio.run(
        de._normalize_mcp_result_for_llm(result, "fred_get_series")
    )

    pointer = json.loads(compact_content)
    assert pointer["status"] == "auto_saved"
    assert pointer["row_count"] == 3

    saved_path = de._resolve_pointer_path(pointer["file_path"])
    assert saved_path is not None
    assert saved_path.exists()

    df = pd.read_csv(saved_path)
    assert list(df.columns) == ["date", "value", "series_id", "units"]
    assert df["series_id"].tolist() == ["GDPC1", "GDPC1", "GDPC1"]
    assert compact_artifact["structured_content_pointer"]["file_path"] == pointer["file_path"]
    artifact_json = json.dumps(compact_artifact)
    assert "2024-04-01" not in artifact_json
    assert "102.25" not in artifact_json


def test_save_data_storage_resolves_auto_saved_pointer(monkeypatch, tmp_path):
    storage_dir = _workspace_storage_dir(tmp_path)
    monkeypatch.setattr(de, "DATA_STORAGE_DIR", storage_dir)

    source_csv = storage_dir / "_auto" / "fred_get_series_123.csv"
    source_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"date": "2024-01-01", "value": 5.0},
            {"date": "2024-02-01", "value": 6.0},
        ]
    ).to_csv(source_csv, index=False)

    pointer = json.dumps(
        {
            "status": "auto_saved",
            "file_path": source_csv.relative_to(Path.cwd()).as_posix(),
            "row_count": 2,
            "columns": ["date", "value"],
        }
    )

    target_path = storage_dir / "job_123" / "GDPC1_gdp_job_123.csv"
    meta = asyncio.run(de._save_data_to_storage(pointer, target_path))

    assert meta["row_count"] == 2
    assert target_path.exists()
    df = pd.read_csv(target_path)
    assert df.to_dict("records") == [
        {"date": "2024-01-01", "value": 5.0},
        {"date": "2024-02-01", "value": 6.0},
    ]


def test_auto_save_result_fails_closed_when_raw_write_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(de, "DATA_STORAGE_DIR", _workspace_storage_dir(tmp_path))

    original_write_text = Path.write_text

    def raising_write_text(self, data, encoding=None, errors=None, newline=None):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", raising_write_text)

    compact = asyncio.run(de._auto_save_result("x" * (de._MCP_INLINE_LIMIT + 50), "fred_search"))
    payload = json.loads(compact)

    assert payload["status"] == "mcp_result_omitted"
    assert payload["tool"] == "fred_search"
    assert payload["byte_size"] > de._MCP_INLINE_LIMIT

    monkeypatch.setattr(Path, "write_text", original_write_text)


def test_run_mcp_request_surfaces_first_failure_to_agent():
    attempts = {"count": 0}

    async def _request():
        attempts["count"] += 1
        raise RuntimeError("Bad Request. The series does not exist.")

    with pytest.raises(de.MCPRequestError, match="Use the exact error to adjust the next request"):
        asyncio.run(
            de._run_mcp_request(
                provider="FRED",
                operation="fred_get_series",
                timeout_secs=1,
                request_factory=_request,
            )
        )

    assert attempts["count"] == 1


def test_with_timeout_returns_error_payload_instead_of_raising():
    class FakeTool:
        name = "fred_get_series"
        response_format = "content_and_artifact"

        async def _arun(self, *args, config=None, run_manager=None, **kwargs):
            raise RuntimeError("Failed to retrieve series data: FRED API error (400)")

    wrapped = de._with_timeout(FakeTool(), 1, "FRED")
    payload, artifact = asyncio.run(
        wrapped._arun(config={}, run_manager=None, series_id="BAD_SERIES")
    )
    result = json.loads(payload)

    assert result["status"] == "error"
    assert result["provider"] == "FRED"
    assert result["tool"] == "fred_get_series"
    assert result["retryable"] is True
    assert "change the next series/query/parameters" in result["hint"]
    assert artifact["structured_content_pointer"]["status"] == "error"
    assert artifact["structured_content_pointer"]["tool"] == "fred_get_series"
