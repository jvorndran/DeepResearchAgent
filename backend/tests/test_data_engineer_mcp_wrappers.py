import asyncio
import json

import pytest

from agents.data_engineer import mcp_wrappers


@pytest.mark.asyncio
async def test_auto_save_result_uses_unique_paths_for_parallel_series(monkeypatch):
    saved_paths = []

    async def fake_save_data_to_storage(data, file_path):
        saved_paths.append(file_path.as_posix())
        return {
            "storage_path": file_path.as_posix(),
            "row_count": len(data["data"]),
            "columns": ["date", "value", "series_id"],
        }

    monkeypatch.setattr(mcp_wrappers, "_save_data_to_storage", fake_save_data_to_storage)

    payloads = [
        {"series_id": "UNRATE", "data": [{"date": "2025-01-01", "value": "4.0"}]},
        {"series_id": "PAYEMS", "data": [{"date": "2025-01-01", "value": "159000"}]},
        {"series_id": "JTSJOL", "data": [{"date": "2025-01-01", "value": "7600"}]},
    ]

    results = await asyncio.gather(
        *(mcp_wrappers._auto_save_result(payload, "fred_get_series") for payload in payloads)
    )

    pointers = [json.loads(result) for result in results]
    returned_paths = [pointer["file_path"] for pointer in pointers]

    assert len(returned_paths) == len(set(returned_paths))
    assert len(saved_paths) == len(set(saved_paths))
    assert all("fred_get_series_" in path for path in returned_paths)
    assert any("UNRATE" in path for path in returned_paths)
    assert all("do not call save_data" in pointer["note"] for pointer in pointers)
