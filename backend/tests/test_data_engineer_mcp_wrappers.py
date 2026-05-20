import asyncio
import json

import pytest

from agents.data_engineer import mcp_wrappers


class _DummyMCPTool:
    name = "fred_get_series"
    response_format = ""

    def __init__(self):
        self.calls = []

    async def _arun(self, *args, config, run_manager=None, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return {"status": "ok"}


async def _call_wrapped_fred(*args, **kwargs):
    tool = _DummyMCPTool()
    wrapped = mcp_wrappers._with_timeout(tool, 5, "FRED")
    await wrapped._arun(*args, config={}, **kwargs)
    return wrapped.calls[-1]


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


@pytest.mark.asyncio
async def test_fred_limited_series_defaults_direct_kwargs_to_latest_first():
    call = await _call_wrapped_fred(series_id="T10Y2Y", limit=24)

    assert call["kwargs"]["series_id"] == "T10Y2Y"
    assert call["kwargs"]["limit"] == 24
    assert call["kwargs"]["sort_order"] == "desc"


@pytest.mark.asyncio
async def test_fred_limited_series_defaults_input_dict_to_latest_first():
    payload = {"series_id": "UNRATE", "limit": "36"}

    call = await _call_wrapped_fred(input=payload)

    assert call["kwargs"]["input"]["series_id"] == "UNRATE"
    assert call["kwargs"]["input"]["limit"] == "36"
    assert call["kwargs"]["input"]["sort_order"] == "desc"
    assert "sort_order" not in payload


@pytest.mark.asyncio
async def test_fred_limited_series_defaults_positional_dict_to_latest_first():
    payload = {"series_id": "FEDFUNDS", "limit": 12}

    call = await _call_wrapped_fred(payload)

    assert call["args"][0]["series_id"] == "FEDFUNDS"
    assert call["args"][0]["limit"] == 12
    assert call["args"][0]["sort_order"] == "desc"
    assert "sort_order" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"series_id": "PAYEMS"},
        {"series_id": "PAYEMS", "limit": 0},
        {"series_id": "PAYEMS", "limit": "0"},
    ],
)
async def test_fred_series_does_not_default_without_positive_limit(payload):
    call = await _call_wrapped_fred(**payload)

    assert call["kwargs"] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"series_id": "GDPC1", "limit": 10, "sort_order": "asc"},
        {"series_id": "UNRATE", "limit": 12, "observation_start": "2008-01-01"},
        {"series_id": "CPIAUCSL", "limit": 10, "observation_end": "2020-12-31"},
        {"series_id": "USREC", "limit": 10, "offset": 10},
    ],
)
async def test_fred_limited_series_preserves_explicit_sort_window_or_offset(payload):
    call = await _call_wrapped_fred(**payload)

    assert call["kwargs"] == payload
