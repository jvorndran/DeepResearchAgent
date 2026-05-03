import json
from types import SimpleNamespace

from langchain.tools import ToolRuntime

from agents.data_engineer import tools


class FakeWorldBankClient:
    def get_indicator(self, *, country_codes, indicator, start_year=None, end_year=None):
        return {
            "status": "success",
            "provider": "World Bank Indicators API",
            "indicator": {
                "indicator_id": "NY.GDP.MKTP.KD.ZG",
                "title": "GDP growth (annual %)",
                "units": "annual percent change",
                "frequency": "annual",
            },
            "countries": {
                "USA": {"code": "USA", "name": "United States"},
                "CAN": {"code": "CAN", "name": "Canada"},
            },
            "observations": [
                {
                    "country_code": "USA",
                    "country_name": "United States",
                    "indicator_id": "NY.GDP.MKTP.KD.ZG",
                    "year": 2023,
                    "value": 2.9,
                },
                {
                    "country_code": "CAN",
                    "country_name": "Canada",
                    "indicator_id": "NY.GDP.MKTP.KD.ZG",
                    "year": 2023,
                    "value": 1.5,
                },
            ],
            "metadata": {
                "year_window": [2020, 2023],
                "handoff_guidance": "World Bank indicators are annual; align FRED monthly data explicitly.",
            },
        }


def test_worldbank_get_indicator_saves_rows_and_returns_data_files_contract(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(tools, "WorldBankIndicatorsClient", lambda: FakeWorldBankClient())
    monkeypatch.setattr(tools, "DATA_STORAGE_DIR", tmp_path)
    runtime = ToolRuntime(
        state={},
        context=SimpleNamespace(job_id="job-worldbank"),
        config={},
        stream_writer=lambda _: None,
        tool_call_id=None,
        store=None,
    )

    payload = tools.worldbank_get_indicator.func(
        country_codes='["USA", "CAN"]',
        indicator="gdp_growth",
        start_year=2020,
        end_year=2023,
        runtime=runtime,
    )
    result = json.loads(payload)

    assert result["status"] == "success"
    assert result["data_files"]["NY.GDP.MKTP.KD.ZG"].endswith(
        "worldbank_ny_gdp_mktp_kd_zg_usa_can_job-worldbank.csv"
    )
    assert result["row_counts"] == {"NY.GDP.MKTP.KD.ZG": 2}
    assert result["metadata"]["requires_api_key"] is False
    assert result["metadata"]["data_type"] == "worldbank_annual_indicator"
    assert "annual" in result["metadata"]["handoff_guidance"]


def test_save_data_returns_existing_worldbank_path_without_resaving(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "DATA_STORAGE_DIR", tmp_path)
    job_dir = tmp_path / "job-worldbank"
    job_dir.mkdir()
    existing = job_dir / "worldbank_ny_gdp_mktp_kd_zg_usa_can_job-worldbank.csv"
    existing.write_text(
        "country_code,indicator_id,year,value\n"
        "USA,NY.GDP.MKTP.KD.ZG,2023,2.9\n"
        "CAN,NY.GDP.MKTP.KD.ZG,2023,1.5\n",
        encoding="utf-8",
    )
    runtime = ToolRuntime(
        state={},
        context=SimpleNamespace(job_id="job-worldbank"),
        config={},
        stream_writer=lambda _: None,
        tool_call_id=None,
        store=None,
    )
    tools.save_data.args_schema.model_validate(
        {
            "data": json.dumps({"file_path": existing.resolve().as_posix()}),
            "ticker": "NY.GDP.MKTP.KD.ZG",
            "data_type": "worldbank_gdp_growth_annual",
            "metadata": {"source_detail": {"provider": "World Bank Indicators API"}},
            "runtime": runtime,
        }
    )

    payload = tools.save_data.func(
        data=json.dumps(
            {
                "file_path": existing.resolve().as_posix(),
                "note": "Already persisted by worldbank_get_indicator",
            }
        ),
        ticker="NY.GDP.MKTP.KD.ZG",
        data_type="worldbank_gdp_growth_annual",
        metadata={
            "target_filename": "worldbank_gdp_growth_annual.csv",
            "source_detail": {"provider": "World Bank Indicators API"},
        },
        runtime=runtime,
    )
    result = json.loads(payload)

    assert result["status"] == "success"
    assert result["storage_path"] == existing.resolve().as_posix()
    assert result["row_count"] == 2
    assert result["source_detail"]["provider"] == "World Bank Indicators API"
    assert not (job_dir / "NY.GDP.MKTP.KD.ZG_worldbank_gdp_growth_annual_job-worldbank.csv").exists()
