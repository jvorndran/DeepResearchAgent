"""Specialized quant-developer tools for deterministic artifact generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain.tools import tool

from agents.quant_macro_stats import (
    build_consumer_stress_dashboard_outputs,
    build_historical_replay_chart_pack_outputs,
    build_inflation_policy_chart_pack_outputs,
    build_macro_cycle_chart_pack_outputs,
    build_recession_dashboard_outputs,
    build_unemployment_forecast_chart_pack_outputs,
)

from .constants import OUTPUT_BASE_DIR


def _script_literal(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def _write_repro_script(
    *,
    output_dir: Path,
    data_files: dict[str, str],
    query: str | None,
    helper_name: str,
) -> None:
    code_dir = output_dir / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    script = f'''#!/usr/bin/env python3
"""Reproduce deterministic quant artifacts."""

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[3]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from agents.quant_macro_stats import {helper_name}

DATA_FILES = {_script_literal(data_files)}
OUTPUT_DIR = Path(__file__).resolve().parents[1]
QUERY = {_script_literal(query or "")}

if __name__ == "__main__":
    handoff = {helper_name}(DATA_FILES, OUTPUT_DIR, query=QUERY)
    print(json.dumps(handoff, sort_keys=True))
'''
    (code_dir / "analysis.py").write_text(script, encoding="utf-8")


@tool
def build_recession_dashboard_artifacts(
    job_id: str,
    data_files: dict[str, str],
    query: str = "",
) -> str:
    """Build recession-dashboard charts from FRED CSVs and return compact handoff JSON.

    Use for FRED recession-dashboard/chart-pack tasks that include UNRATE,
    INDPRO, USREC, and either T10Y3M or real GDP (GDPC1/GDP). A credit or
    risk-context proxy is optional. The tool writes charts.json,
    execution_summary.json, and a reproducible code/analysis.py without passing
    a large generated script through write_file.
    """

    clean_job_id = str(job_id).strip()
    if not clean_job_id:
        raise ValueError("job_id is required")
    output_dir = Path(OUTPUT_BASE_DIR) / clean_job_id
    _write_repro_script(
        output_dir=output_dir,
        data_files=data_files,
        query=query,
        helper_name="build_recession_dashboard_outputs",
    )
    handoff = build_recession_dashboard_outputs(data_files, output_dir, query=query)
    return json.dumps(handoff, sort_keys=True)


@tool
def build_inflation_policy_chart_pack_artifacts(
    job_id: str,
    data_files: dict[str, str],
    query: str = "",
) -> str:
    """Build a CPI/core CPI/Fed funds chart pack and return compact handoff JSON.

    Use for chart-heavy FRED macro tasks that include CPIAUCSL, CPILFESL,
    FEDFUNDS, and optionally USREC. The tool writes 6-8 governed renderable
    charts, execution_summary.json, and a reproducible code/analysis.py without
    passing a large generated script through write_file.
    """

    clean_job_id = str(job_id).strip()
    if not clean_job_id:
        raise ValueError("job_id is required")
    output_dir = Path(OUTPUT_BASE_DIR) / clean_job_id
    _write_repro_script(
        output_dir=output_dir,
        data_files=data_files,
        query=query,
        helper_name="build_inflation_policy_chart_pack_outputs",
    )
    handoff = build_inflation_policy_chart_pack_outputs(data_files, output_dir, query=query)
    return json.dumps(handoff, sort_keys=True)


@tool
def build_consumer_stress_dashboard_artifacts(
    job_id: str,
    data_files: dict[str, str],
    query: str = "",
) -> str:
    """Build a consumer-stress chart dashboard and return compact handoff JSON.

    Use for chart-heavy FRED consumer-stress tasks that include savings,
    unemployment, CPI, wages, sentiment, consumption, and consumer credit
    series. The tool writes 6-8 governed renderable charts,
    execution_summary.json, and a reproducible code/analysis.py without
    passing a large generated script through write_file.
    """

    clean_job_id = str(job_id).strip()
    if not clean_job_id:
        raise ValueError("job_id is required")
    output_dir = Path(OUTPUT_BASE_DIR) / clean_job_id
    _write_repro_script(
        output_dir=output_dir,
        data_files=data_files,
        query=query,
        helper_name="build_consumer_stress_dashboard_outputs",
    )
    handoff = build_consumer_stress_dashboard_outputs(data_files, output_dir, query=query)
    return json.dumps(handoff, sort_keys=True)


@tool
def build_historical_replay_chart_pack_artifacts(
    job_id: str,
    data_files: dict[str, str],
    query: str = "",
) -> str:
    """Build a historical macro-replay chart pack and return compact handoff JSON.

    Use for chart-heavy historical replay or analog-window tasks that include
    unemployment, CPI inflation, fed funds, industrial production, and USREC.
    The tool writes 6-8 governed renderable charts, execution_summary.json,
    and a reproducible code/analysis.py without passing a large generated
    script through write_file.
    """

    clean_job_id = str(job_id).strip()
    if not clean_job_id:
        raise ValueError("job_id is required")
    output_dir = Path(OUTPUT_BASE_DIR) / clean_job_id
    _write_repro_script(
        output_dir=output_dir,
        data_files=data_files,
        query=query,
        helper_name="build_historical_replay_chart_pack_outputs",
    )
    handoff = build_historical_replay_chart_pack_outputs(
        data_files, output_dir, query=query
    )
    return json.dumps(handoff, sort_keys=True)


@tool
def build_unemployment_forecast_chart_pack_artifacts(
    job_id: str,
    data_files: dict[str, str],
    query: str = "",
) -> str:
    """Build an unemployment forecast-overlay chart pack and return handoff JSON.

    Use for chart-heavy unemployment forecast tasks that include UNRATE,
    PAYEMS, and any available predictor evidence such as ICSA/IC4WSA, U6RATE,
    DGS10/FEDFUNDS, NROU, CPIAUCSL/PCEPI, or GDPC1/GDP. The tool writes 6-8
    governed renderable charts, execution_summary.json, and a reproducible
    code/analysis.py without passing a large generated script through
    write_file.
    """

    clean_job_id = str(job_id).strip()
    if not clean_job_id:
        raise ValueError("job_id is required")
    output_dir = Path(OUTPUT_BASE_DIR) / clean_job_id
    _write_repro_script(
        output_dir=output_dir,
        data_files=data_files,
        query=query,
        helper_name="build_unemployment_forecast_chart_pack_outputs",
    )
    handoff = build_unemployment_forecast_chart_pack_outputs(
        data_files, output_dir, query=query
    )
    return json.dumps(handoff, sort_keys=True)


@tool
def build_macro_cycle_chart_pack_artifacts(
    job_id: str,
    data_files: dict[str, str],
    query: str = "",
) -> str:
    """Build a broad macro-cycle chart pack and return compact handoff JSON.

    Use for chart-heavy macro-cycle or macro-regime classification tasks that
    include rates/inflation, labor, output/production, consumer stress,
    historical analogs, and synthesis views from public macro CSVs. The tool writes 8 governed
    renderable charts, execution_summary.json, and a reproducible
    code/analysis.py without passing a large generated script through
    write_file.
    """

    clean_job_id = str(job_id).strip()
    if not clean_job_id:
        raise ValueError("job_id is required")
    output_dir = Path(OUTPUT_BASE_DIR) / clean_job_id
    _write_repro_script(
        output_dir=output_dir,
        data_files=data_files,
        query=query,
        helper_name="build_macro_cycle_chart_pack_outputs",
    )
    handoff = build_macro_cycle_chart_pack_outputs(data_files, output_dir, query=query)
    return json.dumps(handoff, sort_keys=True)
