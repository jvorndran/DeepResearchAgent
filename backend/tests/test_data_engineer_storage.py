import pytest

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
