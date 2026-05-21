import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from agents import quant_macro_stats as qms
from agents.artifact_fact_consistency import (
    artifact_fact_consistency_blocker,
    artifact_fact_consistency_dict,
)
from agents.quant_macro_stats.artifacts.evidence_bundle import (
    EvidenceBundle,
    transform_operation_from_text,
    transform_operation_requires_basis,
)
from agents.quant_macro_stats.artifacts.artifact_fingerprints import (
    evidence_bundle_self_excluded_bytes,
    sha256_bytes,
)
from agents.quant_macro_stats.artifacts.recharts_schema_normalization import (
    normalize_quant_report_charts,
)
from agents.quant_macro_stats.data.series_input_resolution import SeriesSpec, load_monthly_panel


def _write_series(path: Path, values: list[tuple[str, float]]) -> str:
    pd.DataFrame(values, columns=["date", "value"]).to_csv(path, index=False)
    return str(path)


_SEC_TEST_METRIC_CONCEPTS = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "USD"),
    "gross_profit": ("GrossProfit", "USD"),
    "operating_income": ("OperatingIncomeLoss", "USD"),
    "net_income": ("NetIncomeLoss", "USD"),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities", "USD"),
    "capital_expenditures": ("PaymentsToAcquirePropertyPlantAndEquipment", "USD"),
    "cash_and_equivalents": ("CashAndCashEquivalentsAtCarryingValue", "USD"),
    "marketable_securities_current": ("MarketableSecuritiesCurrent", "USD"),
    "long_term_debt": ("LongTermDebtNoncurrent", "USD"),
    "stockholders_equity": ("StockholdersEquity", "USD"),
    "assets": ("Assets", "USD"),
    "liabilities": ("Liabilities", "USD"),
    "diluted_eps": ("EarningsPerShareDiluted", "USD/shares"),
    "shares": ("CommonStocksSharesOutstanding", "shares"),
}


def _with_sec_test_provenance(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    enriched: list[dict[str, object]] = []
    for row in rows:
        out = dict(row)
        fiscal_year = int(out["fiscal_year"])
        out["sec_provenance_schema_version"] = 1
        for metric, (concept, unit) in _SEC_TEST_METRIC_CONCEPTS.items():
            if metric not in out:
                continue
            out[f"{metric}_taxonomy"] = "us-gaap"
            out[f"{metric}_concept"] = concept
            out[f"{metric}_unit"] = unit
            out[f"{metric}_fiscal_period"] = "FY"
            out[f"{metric}_form"] = "10-K"
            out[f"{metric}_filed"] = f"{fiscal_year + 1}-02-01"
            out[f"{metric}_accession_number"] = f"0000000000-{fiscal_year}-000001"
            out[f"{metric}_start"] = f"{fiscal_year}-01-01"
            out[f"{metric}_end"] = f"{fiscal_year}-12-31"
        enriched.append(out)
    return enriched


def _write_nvda_sec_company_facts(path: Path) -> str:
    pd.DataFrame(
        _with_sec_test_provenance(
            [
                {
                    "fiscal_year": 2025,
                    "revenue": 130_497_000_000,
                    "gross_profit": 97_858_000_000,
                    "operating_income": 81_453_000_000,
                    "net_income": 72_880_000_000,
                    "operating_cash_flow": 64_089_000_000,
                    "capital_expenditures": 3_236_000_000,
                    "cash_and_equivalents": 8_589_000_000,
                    "marketable_securities_current": 1_716_000_000,
                    "long_term_debt": 8_463_000_000,
                    "stockholders_equity": 65_000_000_000,
                    "assets": 111_601_000_000,
                    "liabilities": 32_274_000_000,
                    "diluted_eps": 2.94,
                    "shares": 24_700_000_000,
                },
                {
                    "fiscal_year": 2026,
                    "revenue": 215_938_000_000,
                    "gross_profit": 153_865_000_000,
                    "operating_income": 136_859_000_000,
                    "net_income": 120_224_000_000,
                    "operating_cash_flow": 118_200_000_000,
                    "capital_expenditures": 21_524_000_000,
                    "cash_and_equivalents": 8_589_000_000,
                    "marketable_securities_current": 2_016_000_000,
                    "long_term_debt": 7_469_000_000,
                    "stockholders_equity": 79_000_000_000,
                    "assets": 124_092_000_000,
                    "liabilities": 45_000_000_000,
                    "diluted_eps": 4.90,
                    "shares": 24_514_000_000,
                },
            ]
        )
    ).to_csv(path, index=False)
    return str(path)


def _chart_traceability(
    source_id: str = "unit_test",
    transform_id: str = "unit_test_projection",
) -> dict[str, object]:
    return {
        "transform_id": transform_id,
        "provenance": qms.chart_provenance(source_series=[source_id]),
    }


def _assert_no_quant_artifacts(path: Path) -> None:
    assert not (path / "charts.json").exists()
    assert not (path / "execution_summary.json").exists()
    assert not (path / "evidence_bundle.json").exists()


def test_quant_macro_stats_public_exports_are_helper_only():
    required_exports = {
        "align_period_features",
        "direct_ols_forecast",
        "signal_framework_backtest",
        "event_signal_backtest",
        "summarize_sec_company_facts",
        "save_quant_outputs",
        "sec_company_facts_evidence",
        "build_composite_predictive_indicator",
        "classify_recession_regime",
        "build_analog_evidence",
        "normalize_scenario_evidence_rows",
        "forecast_band_rows",
        "forecast_model_comparison_rows",
        "forecast_failure_episodes",
        "normalize_quant_execution_summary",
        "QUANT_HELPER_CATALOG",
        "format_quant_helper_catalog_for_prompt",
        "chart_provenance",
        "source_unit_metadata",
        "source_unit_metadata_from_csv",
        "unit_comparison",
        "latest_numeric_fact",
        "sahm_rule_signal",
    }
    removed_report_generators = {
        "build_company_fundamental_outputs",
        "build_consumer_stress_dashboard_outputs",
        "build_historical_replay_chart_pack_outputs",
        "build_inflation_policy_chart_pack_outputs",
        "build_macro_cycle_chart_pack_outputs",
        "build_recession_dashboard_outputs",
        "build_recession_signal_stack_outputs",
        "build_scenario_stress_test",
        "build_unemployment_forecast_chart_pack_outputs",
        "build_unemployment_forecast_contract",
        "build_company_facts_contract",
        "build_requirement_dispositions",
        "build_capability_coverage",
        "build_scope_coverage",
        "requirement_coverage",
        "build_analysis_evidence",
        "build_decision_evidence",
        "build_macro_cycle_numeric_facts",
        "forecast_evidence_summary",
        "decision_evidence_preview",
        "merge_quant_validation_summary",
        "deterministic_artifact_builder",
        "deterministic_artifact_builders",
        "CANONICAL_ANALOG_WINDOWS",
        "DEFAULT_ANALOG_WINDOWS",
        "requested_analog_years",
        "resolve_analog_windows",
        "mark_requested_coverage",
    }

    assert required_exports.issubset(qms.__all__)
    assert removed_report_generators.isdisjoint(qms.__all__)
    for name in removed_report_generators:
        assert not hasattr(qms, name)


def test_quant_helper_catalog_is_compact_agent_context():
    catalog = qms.format_quant_helper_catalog_for_prompt()
    helper_names = {spec.name for spec in qms.iter_quant_helper_specs()}

    assert "Import helpers from `agents.quant_macro_stats`" in catalog
    assert "data: Resolve local handoff files" in catalog
    assert "direct_ols_forecast(data, target_col, feature_cols" in catalog
    assert "signal_framework_backtest(data, *, component_cols" in catalog
    assert "sahm_rule_signal(data, *, unemployment_col='UNRATE'" in catalog
    assert "current_signal_facts" in catalog
    assert "sec_company_facts_evidence(data_files" in catalog
    assert "chart_provenance(source_series=..." in catalog
    assert "attach_methods_used(charts, methods)" in catalog
    assert "chart transform IDs" in catalog
    assert "source_unit_metadata(source_key, source_file=..." in catalog
    assert "unit_comparison(comparison_id, sources" in catalog
    assert "latest_numeric_fact(panel, key" in catalog
    assert "raw_value" in catalog
    assert "display_value" in catalog
    assert "save_quant_outputs(output_dir, charts, execution_summary)" in catalog
    assert {
        "load_monthly_panel",
        "direct_ols_forecast",
        "sahm_rule_signal",
        "save_quant_outputs",
    }.issubset(helper_names)
    for name in helper_names:
        assert hasattr(qms, name)
    assert "build_recession_dashboard" not in catalog
    assert "prebuilt report" not in catalog.lower()


def test_quant_macro_stats_hard_move_removed_generic_module_paths():
    old_root_modules = (
        "alignment",
        "analog_evidence",
        "artifact_inputs",
        "charts",
        "company_evidence",
        "core",
        "correlations",
        "evidence_contracts",
        "forecast_evidence",
        "forecasting",
        "normalization",
        "outputs",
        "scenarios",
        "shared",
    )

    for module_name in old_root_modules:
        assert importlib.util.find_spec(f"agents.quant_macro_stats.{module_name}") is None


def test_quant_macro_stats_in_repo_imports_use_descriptive_modules():
    old_root_modules = (
        "alignment",
        "analog_evidence",
        "artifact_inputs",
        "charts",
        "company_evidence",
        "correlations",
        "evidence_contracts",
        "forecast_evidence",
        "forecasting",
        "normalization",
        "outputs",
        "scenarios",
        "shared",
    )
    old_absolute_paths = tuple(
        f"agents.quant_macro_stats.{module_name}" for module_name in old_root_modules
    )
    old_relative_imports = tuple(
        f"from .{module_name} import" for module_name in old_root_modules
    ) + tuple(
        f"from ..{module_name} import" for module_name in old_root_modules
    )
    backend_root = Path(__file__).resolve().parents[1]
    ignored_runtime_dirs = {".venv", "__pycache__", ".pytest_cache"}
    this_file = Path(__file__).resolve()
    violations: list[str] = []

    for path in backend_root.rglob("*.py"):
        if path == this_file or any(part in ignored_runtime_dirs for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(old_path in text for old_path in old_absolute_paths):
            violations.append(str(path.relative_to(backend_root)))
            continue
        if "quant_macro_stats" in path.parts and any(
            pattern in text for pattern in old_relative_imports
        ):
            violations.append(str(path.relative_to(backend_root)))

    assert violations == []


def test_load_monthly_panel_resolves_reusable_series_specs(tmp_path):
    data_files = {
        "UNRATE": _write_series(
            tmp_path / "unrate.csv",
            [("2024-01-01", 3.8), ("2024-02-01", 3.9)],
        ),
        "PAYEMS": _write_series(
            tmp_path / "payems.csv",
            [("2024-01-01", 155_000), ("2024-02-01", 155_250)],
        ),
    }
    specs = (
        SeriesSpec("unemployment_rate", ("UNRATE",), column="UNRATE"),
        SeriesSpec("payrolls", ("PAYEMS",), column="PAYEMS"),
    )

    loaded = load_monthly_panel(data_files, specs, context="unit test")

    assert loaded.resolution.resolved_sources == {
        "unemployment_rate": "UNRATE",
        "payrolls": "PAYEMS",
    }
    assert list(loaded.panel.columns) == ["date", "UNRATE", "PAYEMS"]
    assert loaded.panel["UNRATE"].tolist() == [3.8, 3.9]


def test_align_period_features_does_not_fill_monthly_tails_when_weekly_extends():
    panel = qms.align_period_features(
        {
            "PAYEMS": pd.DataFrame(
                {
                    "date": ["2026-03-01", "2026-04-01"],
                    "value": [158_000.0, 158_100.0],
                }
            ),
            "JTSJOL": pd.DataFrame(
                {
                    "date": ["2026-02-01", "2026-03-01"],
                    "value": [7_100.0, 6_900.0],
                }
            ),
            "ICSA": pd.DataFrame(
                {
                    "date": ["2026-05-02", "2026-05-09"],
                    "value": [240_000.0, 250_000.0],
                }
            ),
            "T5YIE": pd.DataFrame(
                {
                    "date": ["2026-05-14", "2026-05-15"],
                    "value": [2.30, 2.40],
                }
            ),
        },
        frequency="M",
        how="outer",
        fill_method="ffill",
        fill_limit=2,
        max_date=None,
    )

    rows = panel.set_index(panel["date"].dt.strftime("%Y-%m"))
    assert rows.loc["2026-04", "PAYEMS"] == 158_100.0
    assert pd.isna(rows.loc["2026-04", "JTSJOL"])
    assert pd.isna(rows.loc["2026-05", "PAYEMS"])
    assert pd.isna(rows.loc["2026-05", "JTSJOL"])
    assert rows.loc["2026-05", "ICSA"] == 245_000.0
    assert rows.loc["2026-05", "T5YIE"] == pytest.approx(2.35)


def test_align_period_features_carries_quarterly_values_only_within_quarter():
    panel = qms.align_period_features(
        {
            "GDPC1": pd.DataFrame(
                {
                    "date": ["2026-01-01", "2026-04-01"],
                    "value": [23_000.0, 23_100.0],
                }
            ),
            "UNRATE": pd.DataFrame(
                {
                    "date": pd.date_range("2026-01-01", periods=7, freq="MS"),
                    "value": [4.0, 4.1, 4.1, 4.2, 4.2, 4.3, 4.3],
                }
            ),
        },
        frequency="M",
        how="outer",
        fill_method="ffill",
        fill_limit=3,
        max_date=None,
    )

    rows = panel.set_index(panel["date"].dt.strftime("%Y-%m"))
    assert rows.loc["2026-01", "GDPC1"] == 23_000.0
    assert rows.loc["2026-02", "GDPC1"] == 23_000.0
    assert rows.loc["2026-03", "GDPC1"] == 23_000.0
    assert rows.loc["2026-04", "GDPC1"] == 23_100.0
    assert rows.loc["2026-05", "GDPC1"] == 23_100.0
    assert rows.loc["2026-06", "GDPC1"] == 23_100.0
    assert pd.isna(rows.loc["2026-07", "GDPC1"])


def test_latest_numeric_fact_uses_latest_finite_value_from_mixed_frequency_panel():
    panel = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-03-01", "2026-04-01", "2026-05-01"]),
            "CPI_YOY": [3.1, 3.0, None],
            "DGS10": [4.2, 4.3, 4.5],
        }
    )

    fact = qms.latest_numeric_fact(
        panel,
        "CPI_YOY",
        fact_id="macro.cpi_yoy.latest",
        label="Latest CPI year-over-year",
        unit="percent",
        precision=1,
        tolerance=0.05,
        source_key="panel.CPI_YOY",
    )

    assert fact == {
        "id": "macro.cpi_yoy.latest",
        "label": "Latest CPI year-over-year",
        "raw_value": 3.0,
        "display_value": "3.0%",
        "unit": "percent",
        "precision": 1,
        "tolerance": 0.05,
        "source_key": "panel.CPI_YOY",
        "as_of_date": "2026-04",
        "metric": "CPI_YOY",
    }


def test_normalize_quant_summary_rejects_malformed_numeric_facts():
    with pytest.raises(ValueError) as error:
        qms.normalize_quant_execution_summary(
            {
                "numeric_facts": [
                    {
                        "id": "macro.cpi_yoy.latest",
                        "label": "Latest CPI year-over-year",
                        "value": None,
                        "source_key": "panel.CPI_YOY",
                    },
                    None,
                ]
            }
        )

    message = str(error.value)
    assert "Invalid execution_summary.numeric_facts" in message
    assert "numeric_facts[0] must include a finite raw_value or value" in message


def test_normalize_quant_summary_requires_facts_for_latest_scalar_snapshot():
    with pytest.raises(ValueError) as error:
        qms.normalize_quant_execution_summary(
            {
                "statistical_summary": {
                    "latest_date": "2026-05-01",
                    "cpi_yoy": 3.0,
                    "core_pce": 2.8,
                }
            }
        )

    message = str(error.value)
    assert "execution_summary.numeric_facts is required" in message
    assert "statistical_summary" in message
    assert "latest_numeric_fact(...)" in message


def test_normalize_quant_summary_requires_matching_fact_for_current_scalar_snapshot():
    with pytest.raises(ValueError) as error:
        qms.normalize_quant_execution_summary(
            {
                "statistical_summary": {
                    "current_unrate": 4.3,
                },
                "numeric_facts": [
                    qms.numeric_fact(
                        fact_id="macro.cpi.latest",
                        label="Latest CPI",
                        raw_value=4.3,
                        unit="index",
                        precision=1,
                        tolerance=0.1,
                        source_key="CPIAUCSL",
                        as_of_date="2026-04-01",
                        metric="cpi",
                    )
                ],
            }
        )

    message = str(error.value)
    assert "matching display-ready numeric_facts" in message
    assert "statistical_summary.current_unrate" in message


def test_normalize_quant_summary_rejects_scalar_fact_with_only_modifier_overlap():
    with pytest.raises(ValueError) as error:
        qms.normalize_quant_execution_summary(
            {
                "statistical_summary": {
                    "real_gdp_12mo_chg_pct": -0.33,
                },
                "numeric_facts": [
                    qms.numeric_fact(
                        fact_id="macro.real_ahe_12mo_chg_pct",
                        label="Real average hourly earnings 12-month change",
                        raw_value=-0.33,
                        unit="percent",
                        precision=2,
                        tolerance=0.01,
                        source_key="CES0500000003/CPIAUCSL",
                        as_of_date="2026-04-01",
                        metric="real_ahe_12mo_chg_pct",
                        operation="pct_change_12mo",
                        transform_basis="CPI-adjusted hourly earnings, 12-month pct change",
                    )
                ],
            }
        )

    message = str(error.value)
    assert "matching display-ready numeric_facts" in message
    assert "statistical_summary.real_gdp_12mo_chg_pct" in message


@pytest.mark.parametrize("label", ["JTSJOL latest", "Job openings latest"])
def test_normalize_quant_summary_rejects_scalar_fact_with_only_source_descriptor_overlap(
    label,
):
    with pytest.raises(ValueError) as error:
        qms.normalize_quant_execution_summary(
            {
                "statistical_summary": {
                    "latest_job_growth": 7.4,
                },
                "numeric_facts": [
                    qms.numeric_fact(
                        fact_id="fred.JTSJOL.latest",
                        label=label,
                        raw_value=7.4,
                        unit="million",
                        precision=1,
                        tolerance=0.01,
                        source_key="JTSJOL",
                        as_of_date="2026-04-01",
                        metric="JTSJOL",
                        operation="latest_observation",
                    )
                ],
            }
        )

    message = str(error.value)
    assert "matching display-ready numeric_facts" in message
    assert "statistical_summary.latest_job_growth" in message


def test_normalize_quant_summary_requires_current_scalar_fact_metadata():
    with pytest.raises(ValueError) as error:
        qms.normalize_quant_execution_summary(
            {
                "statistical_summary": {
                    "real_ahe_12mo_chg_pct": -0.33,
                },
                "numeric_facts": [
                    qms.numeric_fact(
                        fact_id="macro.real_ahe_12mo_chg_pct",
                        label="Real average hourly earnings 12-month change",
                        raw_value=-0.33,
                        unit="percent",
                        precision=2,
                        tolerance=0.01,
                        source_key="CES0500000003/CPIAUCSL",
                        as_of_date="2026-04-01",
                        metric="real_ahe_12mo_chg_pct",
                    )
                ],
            }
        )

    message = str(error.value)
    assert "operation_or_transform_basis" in message
    assert "macro.real_ahe_12mo_chg_pct" in message


def test_normalize_quant_summary_accepts_current_scalars_with_typed_facts():
    summary = qms.normalize_quant_execution_summary(
        {
            "statistical_summary": {
                "current_unrate": 4.3,
                "real_ahe_12mo_chg_pct": -0.33,
            },
            "numeric_facts": [
                qms.numeric_fact(
                    fact_id="macro.current_unrate",
                    label="Current unemployment rate",
                    raw_value=4.3,
                    unit="percent",
                    precision=1,
                    tolerance=0.05,
                    source_key="UNRATE",
                    as_of_date="2026-04-01",
                    metric="current_unrate",
                ),
                qms.numeric_fact(
                    fact_id="macro.real_ahe_12mo_chg_pct",
                    label="Real average hourly earnings 12-month change",
                    raw_value=-0.33,
                    unit="percent",
                    precision=2,
                    tolerance=0.01,
                    source_key="CES0500000003/CPIAUCSL",
                    as_of_date="2026-04-01",
                    metric="real_ahe_12mo_chg_pct",
                    operation="pct_change_12mo",
                    transform_basis="CPI-adjusted hourly earnings, 12-month pct change",
                ),
            ],
        }
    )

    assert summary["numeric_facts"][1]["operation"] == "pct_change_12mo"


def test_normalize_quant_summary_matches_common_source_id_aliases():
    summary = qms.normalize_quant_execution_summary(
        {
            "statistical_summary": {
                "latest_unemployment_rate": 4.3,
            },
            "numeric_facts": [
                qms.numeric_fact(
                    fact_id="fred.UNRATE.latest",
                    label="UNRATE latest",
                    raw_value=4.3,
                    unit="percent",
                    precision=1,
                    tolerance=0.05,
                    source_key="UNRATE",
                    as_of_date="2026-04-01",
                    metric="UNRATE",
                )
            ],
        }
    )

    assert summary["numeric_facts"][0]["source_key"] == "UNRATE"


@pytest.mark.parametrize(
    ("field", "source_key", "value", "unit"),
    [
        ("current_ahe", "CES0500000003", 37.41, "usd"),
        ("current_uempm", "UEMPMEAN", 24.4, "weeks"),
        ("current_underemployment", "LNS12032195", 3289, "thousands"),
    ],
)
def test_normalize_quant_summary_matches_labor_source_id_semantics(
    field,
    source_key,
    value,
    unit,
):
    summary = qms.normalize_quant_execution_summary(
        {
            "statistical_summary": {
                field: value,
            },
            "numeric_facts": [
                qms.numeric_fact(
                    fact_id=f"fred.{source_key}.latest",
                    label=f"{source_key} latest",
                    raw_value=value,
                    unit=unit,
                    precision=2,
                    tolerance=0.01,
                    source_key=source_key,
                    as_of_date="2026-04-01",
                    metric=source_key,
                    operation="latest_observation",
                )
            ],
        }
    )

    assert summary["numeric_facts"][0]["source_key"] == source_key


@pytest.mark.parametrize(
    ("field", "source_key", "value", "operation"),
    [
        ("latest_yield_spread", "T10Y2Y", 0.21, "latest_spread"),
        ("latest_cpi_yoy", "CPIAUCSL", 3.0, "pct_change_yoy"),
        ("latest_core_pce_yoy", "PCEPILFE", 2.8, "pct_change_yoy"),
        ("latest_policy_rate", "FEDFUNDS", 3.64, "latest_observation"),
        ("latest_job_openings", "JTSJOL", 7.4, "latest_observation"),
        (
            "latest_labor_force_participation_rate",
            "CIVPART",
            62.6,
            "latest_observation",
        ),
    ],
)
def test_normalize_quant_summary_matches_common_fred_source_id_aliases(
    field,
    source_key,
    value,
    operation,
):
    summary = qms.normalize_quant_execution_summary(
        {
            "statistical_summary": {
                field: value,
            },
            "numeric_facts": [
                qms.numeric_fact(
                    fact_id=f"fred.{source_key}.latest",
                    label=f"{source_key} latest",
                    raw_value=value,
                    unit="percent",
                    precision=2,
                    tolerance=0.01,
                    source_key=source_key,
                    as_of_date="2026-04-01",
                    metric=source_key,
                    operation=operation,
                )
            ],
        }
    )

    assert summary["numeric_facts"][0]["source_key"] == source_key


def test_normalize_quant_summary_allows_null_current_scalar_with_unavailable_source():
    summary = qms.normalize_quant_execution_summary(
        {
            "statistical_summary": {
                "current_jtsjol": None,
            },
            "source_coverage": {
                "JTSJOL": {
                    "status": "not_available",
                    "reason": "FRED returned no finite current job-openings observation.",
                }
            },
        }
    )

    assert summary["statistical_summary"]["current_jtsjol"] is None


@pytest.mark.parametrize("status", ["no_data", "not_fetched"])
def test_normalize_quant_summary_allows_null_current_scalar_with_qa_unavailable_statuses(
    status,
):
    summary = qms.normalize_quant_execution_summary(
        {
            "statistical_summary": {
                "current_underemployment": None,
            },
            "source_coverage": {
                "LNS12032195": {
                    "status": status,
                    "reason": "No finite current part-time-for-economic-reasons observation.",
                }
            },
        }
    )

    assert summary["statistical_summary"]["current_underemployment"] is None


def test_normalize_quant_summary_preserves_signal_fact_backed_sahm_scalar():
    summary = qms.normalize_quant_execution_summary(
        {
            "statistical_summary": {
                "sahm_value": 0.2,
                "sahm_rule_triggered": False,
            },
            "current_signal_facts": [
                {
                    "signal_id": "sahm_rule",
                    "label": "Sahm rule unemployment gap",
                    "value": 0.2,
                    "threshold": 0.5,
                    "direction": "high",
                    "triggered": False,
                    "threshold_distance": -0.3,
                    "as_of_date": "2026-04-01",
                    "source_key": "UNRATE",
                    "chart_id": "sahm_chart",
                    "data_key": "sahm_gap",
                    "unit": "percentage_point",
                    "tolerance": 0.005,
                }
            ],
        }
    )

    assert "numeric_facts" not in summary
    assert summary["current_signal_facts"][0]["signal_id"] == "sahm_rule"


def test_normalize_quant_summary_rejects_freeform_statistical_assessment():
    with pytest.raises(ValueError) as error:
        qms.normalize_quant_execution_summary(
            {
                "statistical_summary": {
                    "current_unrate": 4.3,
                    "assessment": "The labor market remains resilient.",
                },
                "numeric_facts": [
                    qms.numeric_fact(
                        fact_id="macro.current_unrate",
                        label="Current unemployment rate",
                        raw_value=4.3,
                        unit="percent",
                        precision=1,
                        tolerance=0.05,
                        source_key="UNRATE",
                        as_of_date="2026-04-01",
                        metric="current_unrate",
                    )
                ],
            }
        )

    assert "statistical_summary.assessment is freeform" in str(error.value)


def test_normalize_quant_summary_rejects_null_latest_scalar_slots_with_unrelated_fact():
    with pytest.raises(ValueError) as error:
        qms.normalize_quant_execution_summary(
            {
                "statistical_summary": {
                    "latest_date": "2026-05-01",
                    "cpi_yoy": None,
                    "core_pce": None,
                },
                "numeric_facts": [
                    qms.numeric_fact(
                        fact_id="macro.unrelated.latest",
                        label="Unrelated latest value",
                        raw_value=1.0,
                        unit="index",
                        precision=1,
                        tolerance=0.1,
                        source_key="panel.UNRELATED",
                    )
                ],
            }
        )

    message = str(error.value)
    assert "current/latest scalar snapshots cannot include null scalar fields" in message
    assert "statistical_summary.cpi_yoy" in message
    assert "statistical_summary.core_pce" in message
    assert "latest_numeric_fact(...)" in message


def test_normalize_quant_summary_rejects_empty_facts_for_latest_scalar_snapshot():
    with pytest.raises(ValueError) as error:
        qms.normalize_quant_execution_summary(
            {
                "statistical_summary": {
                    "latest_date": "2026-05-01",
                    "cpi_yoy": 3.0,
                },
                "numeric_facts": [],
            }
        )

    message = str(error.value)
    assert "execution_summary.numeric_facts cannot be empty" in message
    assert "statistical_summary" in message
    assert "numeric_fact(...)" in message


def test_direct_ols_forecast_and_signal_backtest_are_reusable_helpers():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=30, freq="MS"),
            "target": [float(i) for i in range(30)],
            "feature": [float(i) / 2 for i in range(30)],
            "signal_a": [1 if i % 5 == 0 else 0 for i in range(30)],
            "signal_b": [1 if i % 7 == 0 else 0 for i in range(30)],
            "USREC": [1 if 20 <= i <= 22 else 0 for i in range(30)],
        }
    )

    forecast = qms.direct_ols_forecast(
        frame,
        target_col="target",
        feature_cols=["feature"],
        horizon=3,
        min_observations=12,
    )
    backtest = qms.signal_framework_backtest(
        frame,
        component_cols=["signal_a", "signal_b"],
        recession_col="USREC",
        threshold=1,
        lookback_periods=3,
        false_alarm_lookahead_periods=3,
    )

    assert len(forecast["forecast_rows"]) == 3
    assert forecast["model_spec"]
    assert forecast["walk_forward_backtest_rows"]
    assert forecast["model_validation_rows"]
    assert "backtest_summary" not in forecast
    assert "model_comparison" not in forecast
    assert "forecast_table" not in forecast
    assert backtest["signal_validation_metrics"]["event_count"] >= 1
    assert backtest["signal_validation_metrics"]["false_positive_windows"] >= 0
    assert isinstance(backtest["latest_signal_observation"]["above_threshold"], bool)
    assert "interpretation" not in backtest["latest_signal_observation"]
    assert isinstance(backtest["signal_event_rows"], list)
    assert all(isinstance(row, dict) for row in backtest["signal_event_rows"])
    assert isinstance(backtest["signal_score_rows"], list)
    assert "signal_backtest_metrics" not in backtest
    assert "current_signal_row" not in backtest
    assert "pre_recession_signal_rows" not in backtest
    assert "false_alarm_rows" not in backtest
    assert "backtest_design" not in backtest
    assert "historical_simulations" not in backtest
    assert "backtest_summary" not in backtest


def test_sahm_rule_signal_emits_current_signal_contract(tmp_path):
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=15, freq="MS"),
            "UNRATE": [4.0] * 12 + [4.1, 4.2, 4.3],
        }
    )

    signal = qms.sahm_rule_signal(frame, chart_id="sahm_chart")
    current_signal = signal["current_signal_facts"][0]

    assert signal["methods_used"] == [qms.METHOD_SAHM_RULE_SIGNAL]
    assert current_signal["signal_id"] == "sahm_rule"
    assert current_signal["value"] == pytest.approx(0.2)
    assert current_signal["threshold"] == 0.5
    assert current_signal["triggered"] is False
    assert current_signal["threshold_distance"] == pytest.approx(-0.3)
    assert current_signal["chart_id"] == "sahm_chart"
    assert current_signal["data_key"] == "sahm_gap"
    assert signal["numeric_facts"][0]["raw_value"] == pytest.approx(0.2)

    charts = {
        "sahm_chart": {
            "id": "sahm_chart",
            "type": "line",
            "title": "Sahm Rule Signal",
            "xAxisKey": "date",
            "series": [{"dataKey": "sahm_gap", "label": "Sahm gap"}],
            "data": signal["signal_score_rows"],
            **_chart_traceability("UNRATE", qms.METHOD_SAHM_RULE_SIGNAL),
        }
    }
    summary = {
        "signal_score_rows": signal["signal_score_rows"],
        "current_signal_facts": signal["current_signal_facts"],
        "numeric_facts": signal["numeric_facts"],
        "methods_used": signal["methods_used"],
    }

    handoff = qms.save_quant_outputs(tmp_path, charts, summary)
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text())

    assert saved_summary["current_signal_facts"] == signal["current_signal_facts"]
    assert handoff["current_signal_facts"] == signal["current_signal_facts"]


def test_artifact_fact_consistency_rejects_current_signal_mismatches():
    signal_fact = {
        "signal_id": "sahm_rule",
        "value": 0.575,
        "threshold": 0.5,
        "direction": "high",
        "triggered": False,
        "threshold_distance": 0.075,
        "as_of_date": "2026-03-01",
        "source_key": "UNRATE",
        "chart_id": "sahm_chart",
        "data_key": "sahm_gap",
    }

    consistency = artifact_fact_consistency_dict(
        execution_summary={"current_signal_facts": [signal_fact]},
        charts={
            "sahm_chart": {
                "type": "line",
                "data": [{"date": "2026-03-01", "sahm_gap": 0.575}],
            }
        },
    )

    assert consistency["valid"] is False
    assert consistency["signal_mismatches"][0]["reason"] == "trigger_state_mismatch"
    assert "current signal fact for sahm_rule" in artifact_fact_consistency_blocker(
        consistency
    )


def test_save_quant_outputs_rejects_current_signal_chart_latest_mismatch(tmp_path):
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=15, freq="MS"),
            "UNRATE": [4.0] * 12 + [4.1, 4.2, 4.3],
        }
    )
    signal = qms.sahm_rule_signal(frame, chart_id="sahm_chart")
    bad_rows = list(signal["signal_score_rows"])
    bad_rows[-1] = {**bad_rows[-1], "sahm_gap": 0.575, "score": 0.575}
    charts = {
        "sahm_chart": {
            "type": "line",
            "title": "Sahm Rule Signal",
            "xAxisKey": "date",
            "series": [{"dataKey": "sahm_gap", "label": "Sahm gap"}],
            "data": bad_rows,
            **_chart_traceability("UNRATE", qms.METHOD_SAHM_RULE_SIGNAL),
        }
    }

    with pytest.raises(ValueError, match="current signal fact for sahm_rule"):
        qms.save_quant_outputs(
            tmp_path,
            charts,
            {
                "current_signal_facts": signal["current_signal_facts"],
                "numeric_facts": signal["numeric_facts"],
            },
        )


def test_historical_scenario_replay_requires_explicit_windows_and_returns_rows():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=18, freq="MS"),
            "signal": [float(i) / 10 for i in range(18)],
            "USREC": [0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0, 0],
        }
    )

    with pytest.raises(ValueError, match="explicit historical window"):
        qms.historical_scenario_replay(
            frame,
            signal_cols=["signal"],
            outcome_col="USREC",
            windows=[],
        )

    replay = qms.historical_scenario_replay(
        frame,
        signal_cols=["signal"],
        outcome_col="USREC",
        windows=[
            {"label": "first window", "start": "2020-03-01", "end": "2020-05-01"},
            {"label": "later window", "start": "2020-10-01", "end": "2020-12-01"},
        ],
        lookahead_periods=2,
    )

    assert replay["replay_design"]["window_count"] == 2
    assert replay["replay_design"]["outcome_variable"] == "USREC"
    assert [row["label"] for row in replay["replay_rows"]] == [
        "first window",
        "later window",
    ]
    assert replay["replay_rows"][0]["subsequent_outcome"]["periods"] == 2
    assert "historical_simulations" not in replay
    assert "simulation_design" not in replay
    assert "analog_windows" not in replay


def test_build_analog_evidence_returns_generic_rows():
    periods = 390
    frame = pd.DataFrame(
        {
            "date": pd.date_range("1994-01-01", periods=periods, freq="MS"),
            "labor": [4.0 + (i % 36) * 0.03 for i in range(periods)],
            "inflation": [2.0 + (i % 48) * 0.04 for i in range(periods)],
        }
    )

    evidence = qms.build_analog_evidence(
        frame,
        value_cols=["labor", "inflation"],
        current_window={"start": "2023-01-01", "end": "2024-12-01"},
        analog_windows=[
            {
                "label": "1995 soft landing",
                "start": "1994-07-01",
                "end": "1996-12-01",
                "requested": True,
                "requested_years": ["1995"],
            },
            {
                "label": "2001 recession",
                "start": "2000-07-01",
                "end": "2002-12-01",
                "requested": True,
                "requested_years": ["2001"],
            },
            {
                "label": "2008 financial crisis",
                "start": "2007-07-01",
                "end": "2009-12-01",
                "requested": True,
                "requested_years": ["2008"],
            },
            {
                "label": "2020 covid shock",
                "start": "2019-08-01",
                "end": "2021-12-01",
                "requested": True,
                "requested_years": ["2020"],
            },
        ],
        min_required_cap=6,
    )

    assert evidence["historical_window_coverage"]
    assert evidence["analog_similarity_ranking"]
    assert evidence["analog_profile_rows"]
    assert evidence["comparison_design"]["named_windows"]
    assert evidence["methods_used"] == [qms.METHOD_ANALOG_WINDOW_COMPARISON]
    removed_fields = {
        "backtest_summary",
        "historical_simulations",
        "analog_window_contract",
        "analogy_breakdown",
        "similarity_scores",
        "top_analog",
    }
    assert removed_fields.isdisjoint(evidence)


def test_forecast_evidence_helpers_return_generic_rows():
    periods = 84
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2018-01-01", periods=periods, freq="MS"),
            "UNRATE": [4.0 + (i * 0.01) + (0.15 if i > 60 else 0.0) for i in range(periods)],
            "payroll_momentum": [0.1 + (i % 6) * 0.02 for i in range(periods)],
            "claims_pressure": [40.0 + (i % 10) * 2.0 for i in range(periods)],
            "composite_signal": [45.0 + (i % 12) * 3.0 for i in range(periods)],
            "labor_deterioration_event": [1 if i in {62, 63, 70} else 0 for i in range(periods)],
        }
    )
    feature_cols = ["payroll_momentum", "claims_pressure"]
    forecast_frame = frame[["date", "UNRATE", *feature_cols]].dropna()
    forecast = qms.direct_ols_forecast(
        forecast_frame,
        target_col="UNRATE",
        feature_cols=feature_cols,
        horizon=6,
        min_observations=24,
    )
    backtest = qms.walk_forward_ols_backtest(
        forecast_frame,
        "UNRATE",
        feature_cols,
        horizon=6,
        min_observations=24,
        max_table_rows=72,
    )
    signal_frame = frame[["date", "composite_signal", "labor_deterioration_event"]]
    signal_backtest = qms.event_signal_backtest(
        signal_frame,
        signal_col="composite_signal",
        target_col="labor_deterioration_event",
        threshold=65.0,
        prediction_horizon=6,
        min_observations=24,
    )
    latest = frame.dropna(subset=["UNRATE"]).iloc[-1]

    comparison_rows = qms.forecast_model_comparison_rows(forecast["model_validation_rows"])
    failure_episodes = qms.forecast_failure_episodes(backtest)
    false_alarm_episodes = qms.forecast_false_alarm_episodes(
        signal_frame,
        signal_col="composite_signal",
        event_col="labor_deterioration_event",
        threshold=65.0,
        prediction_horizon=6,
    )
    predictor_rows = qms.predictor_contribution_rows(
        forecast_result=forecast,
        forecast_frame=forecast_frame,
        target_col="UNRATE",
        feature_cols=feature_cols,
        panel=frame,
        component_specs=[
            ("Payroll momentum", "payroll_momentum", "composite_signal"),
            ("Claims pressure", "claims_pressure", "composite_signal"),
        ],
    )
    band_rows = qms.forecast_band_rows(
        frame,
        forecast["forecast_rows"],
        latest_value=latest["UNRATE"],
        target_col="UNRATE",
        history_tail=12,
    )
    execution_summary = {
        "forecast_table": qms.normalize_forecast_table(
            forecast,
            latest_value=latest["UNRATE"],
        ),
        "model_comparison_by_horizon": comparison_rows,
        "diagnostics": {
            "direct_ols": forecast["diagnostics"],
            "walk_forward_backtest_rows": forecast["walk_forward_backtest_rows"],
        },
        "methods_used": forecast["methods_used"],
        "historical_failure_episodes": failure_episodes,
        "event_backtest_metrics": signal_backtest.get("event_backtest_metrics"),
        "signal_false_positive_windows": false_alarm_episodes,
        "predictor_contributions": predictor_rows,
        "forecast_band_rows": band_rows,
    }

    assert execution_summary["forecast_table"]
    assert comparison_rows == execution_summary["model_comparison_by_horizon"]
    assert any(row.get("winner_by_mae") for row in comparison_rows)
    assert any("direct_beats_last_value" in row for row in comparison_rows)
    assert execution_summary["historical_failure_episodes"]
    assert execution_summary["event_backtest_metrics"]
    assert execution_summary["signal_false_positive_windows"]
    assert predictor_rows
    assert band_rows[-1]["forecast"] is not None
    assert "baseline_verdicts" not in execution_summary
    assert "false_alarm_backtest" not in execution_summary
    assert "forecast_backtest_summary" not in execution_summary
    assert "forecast_evidence" not in execution_summary
    assert "backtest_summary" not in execution_summary
    assert "model_comparison" not in execution_summary
    assert "method" not in execution_summary
    assert "requirement_disposition" not in execution_summary
    assert not hasattr(qms, "forecast_baseline_verdicts")
    assert not hasattr(qms, "forecast_evidence_summary")
    assert not hasattr(qms, "build_unemployment_forecast_contract")


def test_sec_company_facts_helpers_emit_generic_evidence_rows(tmp_path):
    sec_path = tmp_path / "aapl_sec_edgar_company_facts.csv"
    pd.DataFrame(
        _with_sec_test_provenance(
            [
                {
                    "fiscal_year": 2022,
                    "revenue": 100_000_000_000,
                    "gross_profit": 40_000_000_000,
                    "operating_income": 30_000_000_000,
                    "net_income": 20_000_000_000,
                    "operating_cash_flow": 25_000_000_000,
                    "capital_expenditures": 5_000_000_000,
                    "cash_and_equivalents": 12_000_000_000,
                    "marketable_securities_current": 8_000_000_000,
                    "long_term_debt": 30_000_000_000,
                    "stockholders_equity": 60_000_000_000,
                    "assets": 160_000_000_000,
                    "liabilities": 100_000_000_000,
                    "diluted_eps": 1.25,
                    "shares": 16_000_000_000,
                },
                {
                    "fiscal_year": 2023,
                    "revenue": 125_000_000_000,
                    "gross_profit": 55_000_000_000,
                    "operating_income": 42_000_000_000,
                    "net_income": 28_000_000_000,
                    "operating_cash_flow": 34_000_000_000,
                    "capital_expenditures": 6_000_000_000,
                    "cash_and_equivalents": 14_000_000_000,
                    "marketable_securities_current": 10_000_000_000,
                    "long_term_debt": 32_000_000_000,
                    "stockholders_equity": 70_000_000_000,
                    "assets": 180_000_000_000,
                    "liabilities": 110_000_000_000,
                    "diluted_eps": 1.9,
                    "shares": 15_000_000_000,
                },
                {
                    "fiscal_year": 2024,
                    "revenue": 150_000_000_000,
                    "gross_profit": 70_000_000_000,
                    "operating_income": 55_000_000_000,
                    "net_income": 36_000_000_000,
                    "operating_cash_flow": 44_000_000_000,
                    "capital_expenditures": 8_000_000_000,
                    "cash_and_equivalents": 16_000_000_000,
                    "marketable_securities_current": 12_000_000_000,
                    "long_term_debt": 35_000_000_000,
                    "stockholders_equity": 80_000_000_000,
                    "assets": 210_000_000_000,
                    "liabilities": 130_000_000_000,
                    "diluted_eps": 2.6,
                    "shares": 14_000_000_000,
                },
            ]
        )
    ).to_csv(sec_path, index=False)

    summary = qms.summarize_sec_company_facts(sec_path)
    evidence = qms.sec_company_facts_evidence(
        {"AAPL_SEC": str(sec_path)},
        query="Assess Apple fundamentals, macro sensitivity, and scenario inputs.",
        tickers=["AAPL"],
        include_macro_overlay=False,
    )

    assert summary["fiscal_year_latest"] == 2024
    assert summary["revenue_latest"] == pytest.approx(150.0)
    assert summary["net_margin_pct"] == pytest.approx(24.0)
    assert evidence["status"] == "covered"
    assert evidence["evidence_type"] == "sec_company_facts"
    assert evidence["latest_fundamentals"]["AAPL"]["revenue_b"] == pytest.approx(150.0)
    assert evidence["history_rows"][-1]["ticker"] == "AAPL"
    assert evidence["trend_diagnostics"][0]["ticker"] == "AAPL"
    assert evidence["company_macro_sensitivity"][0] == {
        "ticker": "AAPL",
        "latest_fiscal_year": 2024,
        "latest_avg_fedfunds_pct": None,
        "latest_recession_months": None,
        "recession_fiscal_years_in_history": [],
        "high_rate_fiscal_year_count": 0,
    }
    removed_keys = {
        "compact_ticker_metrics",
        "company_summaries",
        "company_earnings_risk",
        "company_scenario_stress_test",
        "earnings_stress_evidence",
        "earnings_stress_rows",
        "earnings_stress_chart_rows",
        "macro_to_company_channels",
        "requirement_disposition",
        "technology_requirement_disposition",
        "capability_coverage",
        "decision_evidence_preview",
    }
    assert removed_keys.isdisjoint(evidence)
    assert any(
        fact["id"].startswith("sec_company_facts.AAPL.")
        for fact in evidence["numeric_facts"]
    )
    revenue_fact = next(
        fact
        for fact in evidence["numeric_facts"]
        if fact["id"] == "sec_company_facts.AAPL.revenue_b"
    )
    assert revenue_fact["source_provenance_schema"] == "sec_company_facts_v1"
    assert revenue_fact["sec_fact_provenance"]["revenue"]["concept"] == (
        "RevenueFromContractWithCustomerExcludingAssessedTax"
    )
    assert revenue_fact["sec_fact_provenance"]["revenue"]["accession_number"] == (
        "0000000000-2024-000001"
    )
    growth_fact = next(
        fact
        for fact in evidence["numeric_facts"]
        if fact["id"] == "sec_company_facts.AAPL.revenue_growth_pct"
    )
    cagr_fact = next(
        fact
        for fact in evidence["numeric_facts"]
        if fact["id"] == "sec_company_facts.AAPL.revenue_cagr_pct"
    )
    assert growth_fact["sec_metric_components"] == ["revenue_start", "revenue_end"]
    assert growth_fact["sec_fact_provenance"]["revenue_start"]["accession_number"] == (
        "0000000000-2023-000001"
    )
    assert growth_fact["sec_fact_provenance"]["revenue_end"]["accession_number"] == (
        "0000000000-2024-000001"
    )
    assert cagr_fact["sec_metric_components"] == ["revenue_start", "revenue_end"]
    assert cagr_fact["sec_fact_provenance"]["revenue_start"]["accession_number"] == (
        "0000000000-2022-000001"
    )
    assert cagr_fact["sec_fact_provenance"]["revenue_end"]["accession_number"] == (
        "0000000000-2024-000001"
    )
    assert (
        evidence["sec_fact_provenance"]["AAPL"]["derived_metrics"]["revenue_cagr_pct"][
            "revenue_start"
        ]["accession_number"]
        == "0000000000-2022-000001"
    )
    assert evidence["sec_fact_provenance"]["AAPL"]["latest_metrics"]["revenue"]["unit"] == "USD"
    assert evidence["source_unit_metadata"][0]["provider"] == "SEC EDGAR"
    assert evidence["source_coverage"]["sec_company_facts"]["status"] == "covered"
    assert evidence["source_coverage"]["sec_company_facts"]["provenance_fields"]
    valuation_coverage = evidence["source_coverage"]["valuation_market_data"]
    assert valuation_coverage["status"] == "not_available"
    assert valuation_coverage["limitation"]
    assert valuation_coverage["reason"]
    assert "price" in valuation_coverage["capability_list"]
    assert valuation_coverage["capabilities"]
    assert evidence["limitations"]
    assert "contract_type" not in evidence


def test_sec_company_facts_share_count_diagnostics_flag_split_discontinuity(tmp_path):
    sec_path = tmp_path / "aapl_sec_edgar_company_facts.csv"
    pd.DataFrame(
        _with_sec_test_provenance(
            [
                {
                    "fiscal_year": 2019,
                    "revenue": 100_000_000_000,
                    "net_income": 20_000_000_000,
                    "shares": 4_650_000_000,
                },
                {
                    "fiscal_year": 2020,
                    "revenue": 110_000_000_000,
                    "net_income": 21_000_000_000,
                    "shares": 17_500_000_000,
                },
                {
                    "fiscal_year": 2021,
                    "revenue": 120_000_000_000,
                    "net_income": 22_000_000_000,
                    "shares": 16_900_000_000,
                },
            ]
        )
    ).to_csv(sec_path, index=False)

    evidence = qms.sec_company_facts_evidence(
        {"AAPL_SEC": str(sec_path)},
        query="Assess Apple share-count trend and buybacks.",
        tickers=["AAPL"],
        include_macro_overlay=False,
    )

    diagnostic = evidence["share_count_diagnostics"]["AAPL"]
    assert diagnostic["status"] == "split_affected"
    assert diagnostic["comparability"] == "raw_full_series_uncomparable"
    assert diagnostic["full_window_trend"] == "raw_full_series_uncomparable"
    assert diagnostic["latest_comparable_trend"] == "buyback"
    assert diagnostic["discontinuities"][0]["from_fiscal_year"] == 2019
    assert diagnostic["discontinuities"][0]["to_fiscal_year"] == 2020
    assert diagnostic["discontinuities"][0]["ratio"] == pytest.approx(3.763)
    trend = evidence["trend_diagnostics"][0]
    assert trend["share_count_comparability"] == "raw_full_series_uncomparable"
    assert trend["share_count_latest_comparable_trend"] == "buyback"
    assert any("Raw SEC share counts" in item for item in evidence["limitations"])


def test_sec_company_facts_helpers_omit_facts_with_partial_component_provenance(tmp_path):
    sec_path = tmp_path / "aapl_sec_edgar_company_facts.csv"
    rows = _with_sec_test_provenance(
        [
            {
                "fiscal_year": 2023,
                "revenue": 125_000_000_000,
                "gross_profit": 55_000_000_000,
                "net_income": 28_000_000_000,
            },
            {
                "fiscal_year": 2024,
                "revenue": 150_000_000_000,
                "gross_profit": 70_000_000_000,
                "net_income": 36_000_000_000,
            },
        ]
    )
    for key in list(rows[-1]):
        if key.startswith("gross_profit_"):
            del rows[-1][key]
    pd.DataFrame(rows).to_csv(sec_path, index=False)

    evidence = qms.sec_company_facts_evidence(
        {"AAPL_SEC": str(sec_path)},
        query="Assess Apple fundamentals.",
        tickers=["AAPL"],
        include_macro_overlay=False,
    )

    fact_ids = {fact["id"] for fact in evidence["numeric_facts"]}
    assert "sec_company_facts.AAPL.revenue_b" in fact_ids
    assert "sec_company_facts.AAPL.gross_margin_pct" not in fact_ids


def test_event_signal_backtest_returns_reusable_metrics():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=24, freq="MS"),
            "stress_signal": [
                0.1,
                0.2,
                0.8,
                0.9,
                0.2,
                0.1,
                0.3,
                0.9,
                0.8,
                0.2,
                0.1,
                0.1,
                0.2,
                0.2,
                0.85,
                0.9,
                0.2,
                0.2,
                0.1,
                0.1,
                0.1,
                0.1,
                0.1,
                0.1,
            ],
            "future_event": [0, 0, 0, 0, 1, 1, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0],
        }
    )

    backtest = qms.event_signal_backtest(
        frame,
        signal_col="stress_signal",
        target_col="future_event",
        threshold=0.75,
        prediction_horizon=2,
        min_observations=12,
    )

    assert backtest["status"] == "ok"
    assert backtest["methods_used"] == [qms.METHOD_EVENT_SIGNAL_BACKTEST]
    assert backtest["test_observations"] == 22
    assert set(backtest["event_backtest_metrics"]) >= {
        "true_positive",
        "false_positive",
        "true_negative",
        "false_negative",
    }
    assert "average_lead_periods" in backtest["event_backtest_metrics"]
    assert backtest["lead_time_rows"]
    assert "backtest_summary" not in backtest
    json.dumps(backtest)


@pytest.mark.parametrize(
    "container_key",
    ["event_signal_backtest", "signal_framework", "signal_backtest"],
)
def test_normalize_quant_summary_does_not_promote_legacy_signal_packets(container_key):
    summary = qms.normalize_quant_execution_summary(
        {
            container_key: {
                "backtest_summary": {
                    "status": "legacy_signal_packet",
                    "false_alarms": 3,
                },
                "methods_used": ["legacy_signal_method"],
            }
        }
    )

    assert "backtest_summary" not in summary
    assert summary["methods_used"] == []


def test_normalize_quant_summary_canonicalizes_legacy_numeric_facts():
    summary = qms.normalize_quant_execution_summary(
        {
            "numeric_facts": [
                {
                    "id": "unrate",
                    "label": "UNRATE",
                    "value": 4.3,
                    "unit": "%",
                    "precision": 1,
                },
                {
                    "id": "inversion",
                    "label": "Inversion Months",
                    "value": 0,
                    "unit": "months",
                    "precision": 0,
                },
            ]
        }
    )

    unrate, inversion = summary["numeric_facts"]
    assert unrate["raw_value"] == 4.3
    assert unrate["display_value"] == "4.3%"
    assert unrate["source_key"] == "unrate"
    assert unrate.get("literal_required", True) is True

    assert inversion["raw_value"] == 0.0
    assert inversion["display_value"] == "0 months"
    assert inversion["source_key"] == "inversion"
    assert inversion["semantic_role"] == "current_state_duration"
    assert inversion["literal_required"] is False
    assert "no active/current episode" in inversion["state_description"]


def test_current_state_zero_duration_ignores_literal_required_override():
    fact = {
        "id": "inversion",
        "label": "Inversion Months",
        "value": 0,
        "unit": "months",
        "precision": 0,
        "literal_required": True,
    }

    normalized = qms.normalize_numeric_facts([fact], strict=True)[0]

    assert normalized["semantic_role"] == "current_state_duration"
    assert normalized["literal_required"] is False
    assert qms.numeric_fact_literal_required(normalized) is False
    assert qms.numeric_fact_current_state_duration_misuse(
        "The curve normalized after 0 months of inversion.",
        fact | {"raw_value": 0, "semantic_role": "current_state_duration"},
    )

    helper_fact = qms.numeric_fact(
        fact_id="inversion",
        label="Inversion Months",
        raw_value=0,
        unit="months",
        precision=0,
        tolerance=0,
        source_key="inversion",
        literal_required=True,
    )
    assert helper_fact is not None
    assert helper_fact["literal_required"] is False


@pytest.mark.parametrize("literal_required", [None, 0, ""])
def test_numeric_fact_literal_required_malformed_values_do_not_opt_out(literal_required):
    fact = {
        "id": "nvda_revenue_b",
        "label": "NVDA revenue",
        "value": 130.5,
        "unit": "usd_b",
        "precision": 1,
        "subject": "NVDA",
        "metric": "revenue_b",
        "literal_required": literal_required,
    }

    normalized = qms.normalize_numeric_facts([fact])

    assert qms.numeric_fact_literal_required(fact) is True
    assert "literal_required" not in normalized[0]
    assert qms.numeric_fact_literal_required(normalized[0]) is True
    with pytest.raises(ValueError, match="literal_required"):
        qms.normalize_numeric_facts([fact], strict=True)


def test_numeric_fact_literal_required_false_requires_current_state_duration():
    fact = {
        "id": "nvda_revenue_b",
        "label": "NVDA revenue",
        "value": 130.5,
        "unit": "usd_b",
        "precision": 1,
        "subject": "NVDA",
        "metric": "revenue_b",
        "literal_required": False,
    }

    normalized = qms.normalize_numeric_facts([fact])

    assert qms.numeric_fact_literal_required(fact) is True
    assert "literal_required" not in normalized[0]
    assert qms.numeric_fact_literal_required(normalized[0]) is True
    with pytest.raises(ValueError, match="current_state_duration"):
        qms.normalize_numeric_facts([fact], strict=True)
    with pytest.raises(ValueError, match="current_state_duration"):
        qms.numeric_fact(
            fact_id="nvda_revenue_b",
            label="NVDA revenue",
            raw_value=130.5,
            unit="usd_b",
            precision=1,
            tolerance=0.1,
            source_key="sec_company_facts.NVDA.revenue_b",
            subject="NVDA",
            metric="revenue_b",
            literal_required=False,
        )


def test_zero_duration_with_explicit_non_current_role_remains_literal():
    fact = {
        "id": "completed_inversion_duration",
        "label": "Completed inversion duration",
        "value": 0,
        "unit": "months",
        "precision": 0,
        "semantic_role": "historical_duration",
    }

    normalized = qms.normalize_numeric_facts([fact])[0]

    assert normalized["semantic_role"] == "historical_duration"
    assert "literal_required" not in normalized
    assert "state_description" not in normalized
    assert qms.numeric_fact_literal_required(normalized) is True

    opt_out = dict(fact, literal_required=False)
    normalized_opt_out = qms.normalize_numeric_facts([opt_out])[0]
    assert "literal_required" not in normalized_opt_out
    assert qms.numeric_fact_literal_required(normalized_opt_out) is True
    with pytest.raises(ValueError, match="current_state_duration"):
        qms.normalize_numeric_facts([opt_out], strict=True)


def test_composite_regime_and_scenario_helpers_return_generic_payloads():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=36, freq="MS"),
            "target": [0] * 18 + [1] * 18,
            "labor_stress": [i / 10 for i in range(36)],
            "credit_stress": [(i % 12) / 10 for i in range(36)],
            "rates": [-0.3] * 12 + [0.1] * 12 + [0.7] * 12,
            "labor": [-0.2] * 12 + [0.2] * 12 + [0.8] * 12,
            "inflation": [0.0] * 12 + [0.2] * 12 + [0.6] * 12,
            "credit": [-0.1] * 12 + [0.2] * 12 + [0.7] * 12,
            "output": [-0.2] * 12 + [0.3] * 12 + [0.8] * 12,
            "usrec": [0] * 36,
        }
    )

    composite = qms.build_composite_predictive_indicator(
        frame,
        target_col="target",
        feature_cols=["labor_stress", "credit_stress"],
        prediction_horizon=2,
        train_fraction=0.7,
        min_observations=8,
    )
    regime = qms.classify_recession_regime(frame, recession_col="usrec")
    scenarios = qms.normalize_scenario_evidence_rows(
        [
            {
                "scenario": "base",
                "metric": "Composite stress",
                "score": 0.15,
                "drivers": ["Current trend persists"],
                "confidence": "medium",
                "notes": "Input data can be revised.",
            },
            {
                "scenario": "upside labor recovery",
                "metric": "Labor stress",
                "value": -0.2,
                "evidence": ["Labor and output improve", "Stress indicators ease"],
                "confidence": "low",
                "notes": "Policy lags; data revisions",
            },
            {
                "scenario": "credit stress",
                "metric": "Credit stress",
                "delta": 0.4,
                "drivers": ["Credit and labor stress broaden"],
                "notes": "Trigger timing is uncertain.",
                "interpretation": "Legacy report prose should be composed by analysis.py.",
            },
        ],
    )

    assert composite["methods_used"] == [qms.METHOD_COMPOSITE_PREDICTIVE_INDICATOR]
    assert composite["feature_coverage"]["available_features"] == 2
    assert composite["composite_validation_metrics"]["status"] in {
        "ok",
        "insufficient_test_observations",
    }
    assert composite["composite_current_row"]["classification"] in {"low", "medium", "high"}
    assert composite["composite_score_rows"]
    assert "backtest_summary" not in composite
    assert "score_history" not in composite
    assert regime["methods_used"] == [qms.METHOD_RECESSION_REGIME_CLASSIFIER]
    current_regime = regime["current_regime_row"]
    assert current_regime["status"] == "ok"
    assert current_regime["regime"] in {
        "expansion",
        "slowdown",
        "recession",
        "recovery",
        "reacceleration",
    }
    assert set(current_regime["category_scores"]) == set(qms.DEFAULT_REGIME_CATEGORIES)
    assert regime["regime_evidence_rows"]
    assert regime["regime_history_rows"]
    assert isinstance(regime["regime_analog_rows"], list)
    assert regime["missing_indicator_rows"] == []
    assert regime["regime_design"]["method"] == qms.METHOD_RECESSION_REGIME_CLASSIFIER
    assert "evidence_table" not in regime
    assert "historical_analogs" not in regime
    assert "false_positive_caveat" not in regime
    assert "fallback_behavior" not in regime
    assert [row["scenario"] for row in scenarios] == [
        "base",
        "upside labor recovery",
        "credit stress",
    ]
    assert scenarios[1]["evidence"] == ["Labor and output improve", "Stress indicators ease"]
    assert "interpretation" not in scenarios[2]
    assert "indicator_triggers" not in scenarios[0]
    json.dumps({"composite": composite, "regime": regime, "scenarios": scenarios})


def test_save_quant_outputs_writes_generic_evidence_payload(tmp_path):
    charts = {
        "trend": {
            "type": "line",
            "title": "Trend",
            "data": [{"date": "2024-01", "value": 1.0}],
            "series": [{"dataKey": "value", "name": "Value"}],
            "xAxis": {"dataKey": "date"},
            **_chart_traceability("FRED", "unit_test_projection"),
        },
        "empty": {"type": "line", "data": []},
    }
    summary = {
        "methods_used": ["unit_test_method"],
        "numeric_facts": [
            qms.numeric_fact(
                fact_id="latest_value",
                label="Latest value",
                raw_value=1.0,
                unit="index",
                precision=1,
                tolerance=0.1,
                source_key="FRED",
            )
        ],
        "source_coverage": {"FRED": ["UNRATE"]},
    }

    handoff = qms.save_quant_outputs(tmp_path, charts, summary)
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text())
    saved_charts = json.loads((tmp_path / "charts.json").read_text())
    saved_bundle = json.loads((tmp_path / "evidence_bundle.json").read_text())

    assert handoff["chart_ids"] == ["trend"]
    assert handoff["evidence_bundle_json"] == str(tmp_path / "evidence_bundle.json")
    assert saved_summary["chart_ids"] == ["trend"]
    assert saved_summary["evidence_bundle_json"] == str(
        tmp_path / "evidence_bundle.json"
    )
    assert saved_summary["numeric_facts"][0]["id"] == "latest_value"
    assert list(saved_charts) == ["trend"]
    assert saved_bundle["bundle_type"] == "quant_evidence_bundle"
    assert saved_bundle["facts"][0]["fact_id"] == "latest_value"
    assert saved_bundle["charts"][0]["chart_id"] == "trend"
    assert saved_bundle["charts"][0]["source_table_ids"] == ["chart_data:trend"]
    assert saved_bundle["charts"][0]["transform_ids"] == ["unit_test_projection"]
    assert saved_bundle["transforms"][0]["transform_id"] == "unit_test_projection"
    assert saved_bundle["transforms"][0]["chart_ids"] == ["trend"]
    assert saved_bundle["transforms"][0]["source_ids"] == ["FRED"]
    assert saved_bundle["normalized_tables"][0]["table_id"] == "chart_data:trend"
    assert saved_bundle["normalized_tables"][0]["source_id"] == "FRED"
    chart_source_validation = saved_summary["chart_source_table_validation"]["trend"]
    assert chart_source_validation == {
        "status": "valid",
        "validation_version": 1,
        "chart_id": "trend",
        "table_id": "chart_data:trend",
        "chart_type": "line",
        "axis_key": "date",
        "series_keys": ["value"],
        "row_count": 1,
        "columns": ["date", "value"],
        "unique_axis_values": 1,
    }
    assert (
        saved_bundle["normalized_tables"][0]["metadata"][
            "chart_source_table_validation"
        ]
        == chart_source_validation
    )
    assert saved_bundle["sources"][0]["source_id"] == "FRED"
    assert saved_bundle["validation"]["valid"] is True
    assert saved_bundle["artifacts"]["charts_json"] == str(tmp_path / "charts.json")
    assert saved_bundle["artifacts"]["execution_summary_json"] == str(
        tmp_path / "execution_summary.json"
    )
    assert saved_bundle["artifacts"]["evidence_bundle_json"] == str(
        tmp_path / "evidence_bundle.json"
    )
    assert "preserved_prior_charts" not in handoff
    assert "preserved_report_aligned_charts" not in handoff


def test_requested_geography_coverage_contract_and_handoff_preservation(tmp_path):
    summary = {
        "state_comparison": [
            {"state": "California", "income": 91120},
            {"state": "Texas", "income": 72360},
        ],
        "numeric_facts": [
            qms.numeric_fact(
                fact_id="state_comparison.CA.income",
                label="California income",
                raw_value=91120,
                unit="usd_per_person",
                precision=0,
                tolerance=1,
                source_key="state_comparison.CA.income",
            )
        ],
    }
    contract = qms.requested_geography_coverage(
        "Which US regions look healthiest right now?",
        summary,
    )
    summary["requested_geography_coverage"] = contract

    handoff = qms.save_quant_outputs(
        tmp_path,
        charts={},
        execution_summary=summary,
    )
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text())

    assert contract["required"] is True
    assert contract["status"] == "covered"
    assert "state_comparison" in contract["evidence_keys"]
    assert handoff["requested_geography_coverage"]["status"] == "covered"
    assert saved_summary["requested_geography_coverage"]["requested_dimensions"] == [
        "regional",
        "place",
    ]


def test_requested_geography_coverage_rejects_single_numeric_fact_for_ranking_query():
    single_fact = qms.numeric_fact(
        fact_id="state_comparison.CA.income",
        label="California income",
        raw_value=91120,
        unit="usd_per_person",
        precision=0,
        tolerance=1,
        source_key="state_comparison.CA.income",
    )
    contract = qms.requested_geography_coverage(
        "Which US regions look healthiest right now?",
        {"numeric_facts": [single_fact]},
    )
    unavailable_contract = qms.requested_geography_coverage(
        "Which US regions look healthiest right now?",
        {
            "numeric_facts": [single_fact],
            "source_coverage": {
                "census_acs_state": {
                    "dimension": "state",
                    "status": "not_available",
                    "error": "Census state request failed.",
                }
            },
        },
    )
    covered_contract = qms.requested_geography_coverage(
        "Which US regions look healthiest right now?",
        {
            "numeric_facts": [
                single_fact,
                qms.numeric_fact(
                    fact_id="state_comparison.TX.income",
                    label="Texas income",
                    raw_value=72360,
                    unit="usd_per_person",
                    precision=0,
                    tolerance=1,
                    source_key="state_comparison.TX.income",
                ),
            ]
        },
    )

    assert contract["required"] is True
    assert contract["status"] == "missing"
    assert contract["evidence_keys"] == []
    assert "at least two compatible geography entities" in contract["blocker"]
    assert unavailable_contract["status"] == "unavailable"
    assert covered_contract["status"] == "covered"
    assert covered_contract["evidence_keys"] == ["numeric_facts"]


def test_requested_geography_coverage_rejects_placeholder_rows_without_metrics():
    contract = qms.requested_geography_coverage(
        "Which US regions look healthiest right now?",
        {
            "state_comparison": [
                {"state": "California"},
                {"state": "Texas", "state_code": "TX"},
            ],
            "regional_top10": [{"region": "South"}],
            "consumer_stress": {
                "regional_context": [{"region": "Midwest", "source": "Census ACS"}]
            },
        },
    )

    assert contract["required"] is True
    assert contract["status"] == "missing"
    assert contract["evidence_keys"] == []
    assert "matching structured geography evidence" in contract["blocker"]


def test_requested_geography_coverage_ignores_self_attested_status():
    self_reported_covered = qms.requested_geography_coverage(
        "Which US regions look healthiest right now?",
        {
            "requested_geography_coverage": {
                "required": True,
                "status": "covered",
                "evidence_keys": ["state_comparison"],
            }
        },
    )
    self_reported_unavailable = qms.requested_geography_coverage(
        "Which US regions look healthiest right now?",
        {
            "requested_geography_coverage": {
                "required": True,
                "status": "unavailable",
                "unavailable_sources": ["metadata.fetch_errors.census_acs_state"],
            },
            "limitations": ["Census state-level data were unavailable."],
        },
    )

    assert self_reported_covered["status"] == "missing"
    assert self_reported_covered["evidence_keys"] == []
    assert self_reported_unavailable["status"] == "missing"
    assert self_reported_unavailable["unavailable_sources"] == []
    assert "source_coverage" in self_reported_unavailable["blocker"]


def test_requested_geography_coverage_requires_nonempty_unavailable_signal():
    query = "Which US regions look healthiest right now?"
    empty_error_cases = [
        {
            "source_coverage": {
                "census_acs_state": {
                    "dimension": "state",
                    "error": "",
                }
            }
        },
        {
            "source_coverage": {
                "census_acs_state": {
                    "dimension": "state",
                    "error": None,
                }
            }
        },
        {
            "source_coverage": {
                "census_acs_state": {
                    "dimension": "state",
                    "fetch_errors": [],
                }
            }
        },
        {
            "metadata": {
                "fetch_errors": {
                    "census_acs_state": "",
                }
            }
        },
        {
            "metadata": {
                "fetch_errors": {
                    "census_acs_state": None,
                }
            }
        },
        {
            "source_coverage": {
                "census_acs_state": {
                    "dimension": "state",
                    "error": "none",
                }
            }
        },
        {
            "source_coverage": {
                "census_acs_state": {
                    "dimension": "state",
                    "fetch_errors": ["ok"],
                }
            }
        },
        {
            "metadata": {
                "fetch_errors": {
                    "census_acs_state": "ok",
                }
            }
        },
    ]

    for summary in empty_error_cases:
        contract = qms.requested_geography_coverage(query, summary)

        assert contract["status"] == "missing"
        assert contract["unavailable_sources"] == []
        assert "source_coverage" in contract["blocker"]

    nonempty_error = qms.requested_geography_coverage(
        query,
        {
            "source_coverage": {
                "census_acs_state": {
                    "dimension": "state",
                    "error": "Census state request failed.",
                }
            }
        },
    )
    unavailable_status = qms.requested_geography_coverage(
        query,
        {
            "source_coverage": {
                "census_acs_state": {
                    "dimension": "state",
                    "status": "not_available",
                    "error": "",
                }
            }
        },
    )
    unavailable_flag = qms.requested_geography_coverage(
        query,
        {
            "source_coverage": {
                "census_acs_state": {
                    "dimension": "state",
                    "available": False,
                    "error": None,
                }
            }
        },
    )
    metadata_error = qms.requested_geography_coverage(
        query,
        {
            "metadata": {
                "fetch_errors": {
                    "census_acs_state": "Census state request failed.",
                }
            }
        },
    )

    assert nonempty_error["status"] == "unavailable"
    assert unavailable_status["status"] == "unavailable"
    assert unavailable_flag["status"] == "unavailable"
    assert metadata_error["status"] == "unavailable"


def test_requested_geography_coverage_ignores_ordinary_state_language():
    for query in (
        "What is the state of the economy?",
        "What safeguards are in place for recession risk?",
        "United States outlook for growth and inflation",
    ):
        contract = qms.requested_geography_coverage(
            query,
            {"state_comparison": [{"state": "California", "income": 91120}]},
        )

        assert contract["required"] is False
        assert contract["requested_dimensions"] == []
        assert contract["status"] == "not_required"
        assert contract["evidence_keys"] == []

    single_state_contract = qms.requested_geography_coverage(
        "Which US states look healthiest right now?",
        {"state_comparison": [{"state": "California", "income": 91120}]},
    )
    state_contract = qms.requested_geography_coverage(
        "Which US states look healthiest right now?",
        {
            "state_comparison": [
                {"state": "California", "income": 91120},
                {"state": "Texas", "income": 72360},
            ]
        },
    )

    assert single_state_contract["required"] is True
    assert single_state_contract["status"] == "missing"
    assert state_contract["required"] is True
    assert state_contract["requested_dimensions"] == ["state", "place"]
    assert state_contract["status"] == "covered"


def test_requested_geography_coverage_detects_named_and_ranked_state_requests():
    for query in (
        "How healthy is California's economy right now?",
        "Compare California and Texas right now",
        "Compare US states by unemployment",
        "Rank states by unemployment",
    ):
        contract = qms.requested_geography_coverage(query, {})

        assert contract["required"] is True
        assert contract["requested_dimensions"] == ["state", "place"]
        assert contract["status"] == "missing"


def test_requested_geography_coverage_requires_named_state_entities():
    mismatched_contract = qms.requested_geography_coverage(
        "Compare California and Texas right now",
        {
            "state_comparison": [
                {"state": "Florida", "income": 68420},
                {"state": "New York", "income": 88850},
            ]
        },
    )
    mismatched_numeric_contract = qms.requested_geography_coverage(
        "Compare California and Texas right now",
        {
            "numeric_facts": [
                qms.numeric_fact(
                    fact_id="state_comparison.FL.income",
                    label="Florida income",
                    raw_value=68420,
                    unit="usd_per_person",
                    precision=0,
                    tolerance=1,
                    source_key="state_comparison.FL.income",
                ),
                qms.numeric_fact(
                    fact_id="state_comparison.NY.income",
                    label="New York income",
                    raw_value=88850,
                    unit="usd_per_person",
                    precision=0,
                    tolerance=1,
                    source_key="state_comparison.NY.income",
                ),
            ]
        },
    )
    covered_contract = qms.requested_geography_coverage(
        "Compare California and Texas right now",
        {
            "state_comparison": [
                {"state": "California", "income": 91120},
                {"state": "Texas", "income": 72360},
                {"state": "Florida", "income": 68420},
            ]
        },
    )

    assert mismatched_contract["required"] is True
    assert mismatched_contract["requested_entities"] == ["california", "texas"]
    assert mismatched_contract["status"] == "missing"
    assert mismatched_contract["evidence_keys"] == []
    assert mismatched_numeric_contract["status"] == "missing"
    assert mismatched_numeric_contract["evidence_keys"] == []
    assert covered_contract["status"] == "covered"
    assert covered_contract["requested_entities"] == ["california", "texas"]


def test_requested_geography_coverage_requires_peer_entity_for_named_ranking():
    single_structured = qms.requested_geography_coverage(
        "Rank California among states by income",
        {"state_comparison": [{"state": "California", "income": 91120}]},
    )
    single_numeric = qms.requested_geography_coverage(
        "Rank California among states by income",
        {
            "numeric_facts": [
                qms.numeric_fact(
                    fact_id="state_comparison.CA.income",
                    label="California income",
                    raw_value=91120,
                    unit="usd_per_person",
                    precision=0,
                    tolerance=1,
                    source_key="state_comparison.CA.income",
                )
            ]
        },
    )
    covered_contract = qms.requested_geography_coverage(
        "Rank California among states by income",
        {
            "state_comparison": [
                {"state": "California", "income": 91120},
                {"state": "Texas", "income": 72360},
            ]
        },
    )

    assert single_structured["required"] is True
    assert single_structured["requested_entities"] == ["california"]
    assert single_structured["status"] == "missing"
    assert single_structured["evidence_keys"] == []
    assert single_numeric["status"] == "missing"
    assert single_numeric["evidence_keys"] == []
    assert covered_contract["status"] == "covered"


def test_requested_geography_coverage_ignores_non_us_directional_terms():
    for query in (
        "South Korea growth outlook",
        "West Texas Intermediate oil outlook",
        "western Europe manufacturing outlook",
        "coastal shipping outlook",
        "Are regional banks under stress?",
    ):
        contract = qms.requested_geography_coverage(query, {})

        assert contract["required"] is False
        assert contract["requested_dimensions"] == []
        assert contract["status"] == "not_required"

    single_regional_contract = qms.requested_geography_coverage(
        "Compare the South versus the Midwest right now",
        {"regional_top10": [{"region": "South", "score": 72}]},
    )
    regional_contract = qms.requested_geography_coverage(
        "Compare the South versus the Midwest right now",
        {
            "regional_top10": [
                {"region": "South", "score": 72},
                {"region": "Midwest", "score": 68},
            ]
        },
    )

    assert single_regional_contract["required"] is True
    assert single_regional_contract["status"] == "missing"
    assert regional_contract["required"] is True
    assert regional_contract["requested_dimensions"] == ["regional", "place"]
    assert regional_contract["status"] == "covered"


def test_requested_geography_coverage_requires_matching_dimension():
    county_contract = qms.requested_geography_coverage(
        "Which counties look healthiest right now?",
        {
            "regional_top10": [{"state": "California", "score": 92}],
            "state_comparison": [{"state": "California", "income": 91120}],
            "source_coverage": {
                "census_acs_state": {
                    "dimension": "state",
                    "status": "not_available",
                    "error": "State request failed.",
                }
            },
        },
    )

    assert county_contract["required"] is True
    assert county_contract["requested_dimensions"] == ["county"]
    assert county_contract["status"] == "missing"
    assert county_contract["evidence_keys"] == []
    assert county_contract["unavailable_sources"] == []
    assert "matching structured geography evidence" in county_contract["blocker"]

    county_unavailable = qms.requested_geography_coverage(
        "Which counties look healthiest right now?",
        {
            "source_coverage": {
                "census_acs_county": {
                    "dimension": "county",
                    "status": "not_available",
                    "error": "County request failed.",
                }
            }
        },
    )

    assert county_unavailable["status"] == "unavailable"
    assert "source_coverage.census_acs_county" in county_unavailable["unavailable_sources"]
    assert all("state" not in source for source in county_unavailable["unavailable_sources"])


def test_save_quant_outputs_writes_artifact_fingerprint_manifest(tmp_path):
    source_path = tmp_path / "fred_unrate.csv"
    source_path.write_text("date,value\n2024-01,1.0\n", encoding="utf-8")
    snapshot_path = tmp_path / "fred_unrate_snapshot.json"
    snapshot_path.write_text(
        json.dumps({"raw_response": {"observations": [{"date": "2024-01"}]}}),
        encoding="utf-8",
    )
    snapshot_descriptor = {
        "snapshot_id": "fred:unrate:" + "c" * 16,
        "provider": "FRED",
        "source_id": "FRED",
        "source_keys": ["FRED"],
        "endpoint": "https://api.stlouisfed.org/fred/series/observations",
        "method": "GET",
        "request_params": {"series_id": "UNRATE"},
        "retrieved_at": "2026-05-19T00:00:00+00:00",
        "freshness_policy": "Latest available FRED observation payload.",
        "response_sha256": "c" * 64,
        "path": str(snapshot_path),
        "byte_count": snapshot_path.stat().st_size,
        "content_type": "application/json",
    }
    charts = {
        "trend": {
            "type": "line",
            "title": "Trend",
            "data": [{"date": "2024-01", "value": 1.0}],
            "series": [{"dataKey": "value", "name": "Value"}],
            "xAxis": {"dataKey": "date"},
            **_chart_traceability("FRED", "unit_test_projection"),
        },
    }
    summary = {
        "methods_used": ["unit_test_method"],
        "source_files": {"FRED": str(source_path)},
        "source_snapshots": {"FRED": snapshot_descriptor},
        "numeric_facts": [
            qms.numeric_fact(
                fact_id="latest_value",
                label="Latest value",
                raw_value=1.0,
                unit="index",
                precision=1,
                tolerance=0.1,
                source_key="FRED",
            )
        ],
    }

    qms.save_quant_outputs(tmp_path, charts, summary)
    saved_bundle = json.loads((tmp_path / "evidence_bundle.json").read_text())

    fingerprints = {
        fingerprint["artifact_id"]: fingerprint
        for fingerprint in saved_bundle["artifacts"]["fingerprints"]
    }
    assert set(fingerprints) == {
        "charts_json",
        "execution_summary_json",
        "source_files:FRED",
        "source_snapshots:FRED",
        "evidence_bundle_json",
    }
    assert fingerprints["charts_json"]["sha256"] == sha256_bytes(
        (tmp_path / "charts.json").read_bytes()
    )
    assert fingerprints["charts_json"]["byte_count"] == (
        tmp_path / "charts.json"
    ).stat().st_size
    assert fingerprints["execution_summary_json"]["sha256"] == sha256_bytes(
        (tmp_path / "execution_summary.json").read_bytes()
    )
    assert fingerprints["source_files:FRED"]["sha256"] == sha256_bytes(
        source_path.read_bytes()
    )
    assert fingerprints["source_files:FRED"]["content_type"] == "text/csv"
    assert fingerprints["source_snapshots:FRED"]["sha256"] == sha256_bytes(
        snapshot_path.read_bytes()
    )
    assert fingerprints["source_snapshots:FRED"]["role"] == "source_snapshot"
    assert saved_bundle["artifacts"]["source_snapshots"]["FRED"]["path"] == str(
        snapshot_path
    )
    assert fingerprints["evidence_bundle_json"]["self_excluded"] is True
    assert fingerprints["evidence_bundle_json"]["sha256"] == sha256_bytes(
        evidence_bundle_self_excluded_bytes(saved_bundle)
    )
    assert fingerprints["evidence_bundle_json"]["byte_count"] == (
        tmp_path / "evidence_bundle.json"
    ).stat().st_size
    EvidenceBundle.model_validate(saved_bundle)


def test_save_quant_outputs_rejects_chart_without_evidence_bundle_traceability(tmp_path):
    with pytest.raises(ValueError) as exc:
        qms.save_quant_outputs(
            tmp_path,
            {
                "trend": {
                    "type": "line",
                    "title": "Trend",
                    "data": [{"date": "2024-01", "value": 1.0}],
                    "series": [{"dataKey": "value", "name": "Value"}],
                    "xAxis": {"dataKey": "date"},
                }
            },
            {},
        )

    message = str(exc.value)
    assert "source_table_ids" in message
    assert "transform_ids" in message
    assert not (tmp_path / "evidence_bundle.json").exists()


def test_save_quant_outputs_rejects_generic_chart_source_table_without_provenance(
    tmp_path,
):
    with pytest.raises(ValueError) as exc:
        qms.save_quant_outputs(
            tmp_path,
            {
                "trend": {
                    "type": "line",
                    "title": "Trend",
                    "data": [{"date": "2024-01", "value": 1.0}],
                    "series": [{"dataKey": "value", "name": "Value"}],
                    "xAxis": {"dataKey": "date"},
                    "source_table_ids": ["s"],
                }
            },
            {
                "methods_used": ["unit_test_method"],
                "raw_tables": [
                    {
                        "table_id": "s",
                        "description": "generic stats table",
                        "data": [{"k": "latest_value", "v": 1.0}],
                    }
                ],
            },
        )

    message = str(exc.value)
    assert "charts with data rows must include chart provenance" in message
    assert "chart_provenance(source_series=[...])" in message
    _assert_no_quant_artifacts(tmp_path)


def test_evidence_bundle_rejects_unresolved_chart_source_table_ids():
    with pytest.raises(ValueError) as exc:
        EvidenceBundle.model_validate(
            {
                "charts": [
                    {
                        "chart_id": "trend",
                        "source_table_ids": ["UNRATE"],
                        "transform_ids": ["monthly_latest_value_projection"],
                    }
                ],
                "validation": {"valid": True},
                "artifacts": {
                    "charts_json": "charts.json",
                    "execution_summary_json": "execution_summary.json",
                    "evidence_bundle_json": "evidence_bundle.json",
                },
            }
        )

    assert "charts.source_table_ids must resolve" in str(exc.value)


def test_evidence_bundle_rejects_cross_kind_table_id_ambiguity():
    with pytest.raises(ValueError) as exc:
        EvidenceBundle.model_validate(
            {
                "raw_tables": [{"table_id": "OBS", "kind": "raw"}],
                "normalized_tables": [
                    {"table_id": "OBS", "kind": "normalized"}
                ],
                "charts": [
                    {
                        "chart_id": "trend",
                        "source_table_ids": ["OBS"],
                        "transform_ids": ["monthly_projection"],
                    }
                ],
                "validation": {"valid": True},
                "artifacts": {
                    "charts_json": "charts.json",
                    "execution_summary_json": "execution_summary.json",
                    "evidence_bundle_json": "evidence_bundle.json",
                },
            }
        )

    assert "table_id values must be unique across raw_tables" in str(exc.value)


def _valid_sec_component_provenance(concept: str = "Revenues") -> dict[str, str]:
    return {
        "taxonomy": "us-gaap",
        "concept": concept,
        "unit": "USD",
        "fiscal_period": "FY",
        "form": "10-K",
        "filed": "2025-02-01",
        "accession_number": "0000000000-2024-000001",
        "end": "2024-12-31",
    }


def _minimal_sec_bundle_fact(attributes: dict[str, object], metric: str) -> dict[str, object]:
    fact = {
        "fact_id": f"sec_company_facts.AAPL.{metric}",
        "label": f"AAPL latest {metric}",
        "raw_value": 150.0,
        "display_value": "150.0",
        "unit": "usd_b" if metric.endswith("_b") else "percent",
        "precision": 3,
        "tolerance": 0.005,
        "source_key": f"sec_company_facts.latest_fundamentals.AAPL.{metric}",
        "attributes": attributes,
    }
    if "growth" in metric or "cagr" in metric:
        fact["transform_basis"] = "derived from two SEC revenue observations"
    return {
        "sources": [{"source_id": "sec_company_facts"}],
        "facts": [fact],
        "validation": {"valid": True},
        "artifacts": {
            "charts_json": "charts.json",
            "execution_summary_json": "execution_summary.json",
            "evidence_bundle_json": "evidence_bundle.json",
        },
    }


def test_evidence_bundle_rejects_sec_helper_fact_without_provenance_schema():
    with pytest.raises(ValueError) as exc:
        EvidenceBundle.model_validate(_minimal_sec_bundle_fact({}, "revenue_b"))

    assert "SEC helper facts with provenance schemas are invalid" in str(exc.value)
    assert "source_provenance_schema must be" in str(exc.value)


def test_evidence_bundle_rejects_untyped_unavailable_market_valuation_coverage():
    with pytest.raises(ValueError) as exc:
        EvidenceBundle.model_validate(
            {
                "sources": [
                    {
                        "source_id": "valuation_market_data",
                        "status": "not_available",
                        "coverage": {"status": "not_available"},
                    }
                ],
                "validation": {"valid": True},
                "artifacts": {
                    "charts_json": "charts.json",
                    "execution_summary_json": "execution_summary.json",
                    "evidence_bundle_json": "evidence_bundle.json",
                },
            }
        )

    message = str(exc.value)
    assert "market valuation source coverage is invalid" in message
    assert "requires limitation or reason" in message
    assert "requires a non-empty capability list" in message


def test_evidence_bundle_rejects_incomplete_sec_helper_provenance():
    with pytest.raises(ValueError) as exc:
        EvidenceBundle.model_validate(
            _minimal_sec_bundle_fact(
                {
                    "source_provenance_schema": "sec_company_facts_v1",
                    "sec_provenance_schema_version": 1,
                    "sec_metric_components": ["revenue"],
                    "sec_fact_provenance": {
                        "revenue": {
                            "taxonomy": "us-gaap",
                            "concept": "Revenues",
                            "unit": "USD",
                        }
                    },
                },
                "revenue_b",
            )
        )

    assert "SEC helper facts with provenance schemas are invalid" in str(exc.value)
    assert "fiscal_period" in str(exc.value)


def test_evidence_bundle_rejects_sec_derived_fact_missing_expected_component():
    with pytest.raises(ValueError) as exc:
        EvidenceBundle.model_validate(
            _minimal_sec_bundle_fact(
                {
                    "source_provenance_schema": "sec_company_facts_v1",
                    "sec_provenance_schema_version": 1,
                    "sec_metric_components": ["revenue"],
                    "sec_fact_provenance": {
                        "revenue": _valid_sec_component_provenance(),
                    },
                },
                "gross_margin_pct",
            )
        )

    assert "sec_metric_components must be ['gross_profit', 'revenue']" in str(exc.value)
    assert "missing SEC provenance for gross_profit" in str(exc.value)


def test_evidence_bundle_rejects_sec_growth_fact_missing_period_provenance():
    with pytest.raises(ValueError) as exc:
        EvidenceBundle.model_validate(
            _minimal_sec_bundle_fact(
                {
                    "source_provenance_schema": "sec_company_facts_v1",
                    "sec_provenance_schema_version": 1,
                    "sec_metric_components": ["revenue"],
                    "sec_fact_provenance": {
                        "revenue": _valid_sec_component_provenance(),
                    },
                },
                "revenue_cagr_pct",
            )
        )

    assert "sec_metric_components must be ['revenue_start', 'revenue_end']" in str(exc.value)
    assert "missing SEC provenance for revenue_start" in str(exc.value)
    assert "missing SEC provenance for revenue_end" in str(exc.value)


def test_save_quant_outputs_uses_methods_as_evidence_bundle_chart_transform_ids(tmp_path):
    qms.save_quant_outputs(
        tmp_path,
        {
            "trend": {
                "type": "line",
                "title": "Trend",
                "data": [{"date": "2024-01", "value": 1.0}],
                "series": [{"dataKey": "value", "name": "Value"}],
                "xAxis": {"dataKey": "date"},
                "provenance": qms.chart_provenance(source_series=["UNRATE"]),
            }
        },
        {"methods_used": ["monthly_latest_value_projection"]},
    )

    saved_bundle = json.loads((tmp_path / "evidence_bundle.json").read_text())

    assert saved_bundle["charts"][0]["source_table_ids"] == ["chart_data:trend"]
    assert saved_bundle["charts"][0]["transform_ids"] == [
        "monthly_latest_value_projection"
    ]
    table_ref = saved_bundle["normalized_tables"][0]
    assert table_ref["table_id"] == "chart_data:trend"
    assert table_ref["kind"] == "normalized"
    assert table_ref["source_id"] == "UNRATE"
    assert table_ref["role"] == "chart_data"
    assert table_ref["row_count"] == 1
    assert table_ref["columns"] == ["date", "value"]
    assert table_ref["metadata"]["chart_id"] == "trend"
    assert table_ref["metadata"]["source_ids"] == ["UNRATE"]
    assert table_ref["metadata"]["chart_source_table_validation"] == {
        "status": "valid",
        "validation_version": 1,
        "chart_id": "trend",
        "table_id": "chart_data:trend",
        "chart_type": "line",
        "axis_key": "date",
        "series_keys": ["value"],
        "row_count": 1,
        "columns": ["date", "value"],
        "unique_axis_values": 1,
    }


def test_save_quant_outputs_prefers_chart_data_over_stale_source_table_ids(tmp_path):
    qms.save_quant_outputs(
        tmp_path,
        {
            "trend": {
                "type": "line",
                "title": "Trend",
                "data": [{"date": "2024-01", "value": 1.0}],
                "series": [{"dataKey": "value", "name": "Value"}],
                "xAxis": {"dataKey": "date"},
                "source_table_ids": ["s"],
                "transform_id": "unit_test_projection",
                "provenance": qms.chart_provenance(source_series=["FRED"]),
            }
        },
        {
            "raw_tables": [
                {
                    "table_id": "s",
                    "description": "generic stats table",
                    "data": [{"k": "latest_value", "v": 1.0}],
                }
            ],
        },
    )

    saved_bundle = json.loads((tmp_path / "evidence_bundle.json").read_text())

    assert saved_bundle["charts"][0]["source_table_ids"] == ["chart_data:trend"]
    assert saved_bundle["charts"][0]["provenance"]["source_series"] == ["FRED"]
    assert saved_bundle["transforms"][0]["source_table_ids"] == ["chart_data:trend"]
    assert saved_bundle["raw_tables"][0]["table_id"] == "s"
    assert saved_bundle["normalized_tables"][0]["table_id"] == "chart_data:trend"
    assert saved_bundle["normalized_tables"][0]["source_id"] == "FRED"


def test_save_quant_outputs_rejects_duplicate_evidence_bundle_fact_ids(tmp_path):
    fact = qms.numeric_fact(
        fact_id="latest_value",
        label="Latest value",
        raw_value=1.0,
        unit="index",
        precision=1,
        tolerance=0.1,
        source_key="unit_test",
    )
    with pytest.raises(ValueError) as exc:
        qms.save_quant_outputs(
            tmp_path,
            {},
            {
                "methods_used": ["unit_test_method"],
                "numeric_facts": [fact, dict(fact)],
                "source_coverage": {"unit_test": ["latest_value"]},
            },
        )

    assert "facts.fact_id values must be unique" in str(exc.value)
    assert not (tmp_path / "evidence_bundle.json").exists()


def test_save_quant_outputs_infers_simple_evidence_bundle_fact_source_keys(tmp_path):
    qms.save_quant_outputs(
        tmp_path,
        {},
        {
            "methods_used": ["unit_test_method"],
            "numeric_facts": [
                qms.numeric_fact(
                    fact_id="latest_value",
                    label="Latest value",
                    raw_value=1.0,
                    unit="index",
                    precision=1,
                    tolerance=0.1,
                    source_key="UNRATE",
                )
            ],
        },
    )

    saved_bundle = json.loads((tmp_path / "evidence_bundle.json").read_text())

    assert saved_bundle["facts"][0]["source_key"] == "UNRATE"
    assert saved_bundle["sources"][0]["source_id"] == "UNRATE"
    assert saved_bundle["sources"][0]["metadata"] == {
        "inferred_from_fact_source_key": True
    }


def test_chart_provenance_normalizes_comma_delimited_source_series_only():
    provenance = qms.chart_provenance(
        source_series=" UMCSENT, UNRATE, UMCSENT ",
        source_files=["inputs/UMCSENT, UNRATE.csv"],
        limitations="sentiment, hard data overlay",
    )

    assert provenance["source_series"] == ["UMCSENT", "UNRATE"]
    assert provenance["source_files"] == ["inputs/UMCSENT, UNRATE.csv"]
    assert provenance["limitations"] == ["sentiment, hard data overlay"]


def test_save_quant_outputs_preserves_chart_provenance_and_generator_path(
    tmp_path, monkeypatch
):
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    script_path = code_dir / "analysis_v2.py"
    script_path.write_text("# generated script\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", [str(script_path)])
    provenance = qms.chart_provenance(
        source_series=["T10Y2Y"],
        source_files={"T10Y2Y": tmp_path / "t10y2y.csv"},
        raw_window={"start": "2026-05-01", "end": "2026-05-15"},
        raw_latest_observation={"T10Y2Y": "2026-05-15"},
        displayed_window={"start": "2026-05", "end": "2026-05"},
        displayed_latest_label="2026-05",
        frequency="daily",
        resampling="monthly last observation with month labels",
        normalization={"base_date": "2016-01", "base_value": 100},
        limitations=["partial latest month"],
    )
    charts = {
        "yield_spread": {
            "type": "line",
            "title": "Yield Spread",
            "data": [{"date": "2026-05", "spread": 0.5}],
            "series": [{"dataKey": "spread", "name": "Spread"}],
            "xAxis": {"dataKey": "date"},
            "provenance": provenance,
        }
    }

    handoff = qms.save_quant_outputs(tmp_path, charts, {"methods_used": ["unit"]})
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text())
    saved_charts = json.loads((tmp_path / "charts.json").read_text())
    saved_bundle = json.loads((tmp_path / "evidence_bundle.json").read_text())

    assert saved_charts["yield_spread"]["provenance"]["raw_latest_observation"] == {
        "T10Y2Y": "2026-05-15"
    }
    assert saved_summary["chart_provenance"]["yield_spread"]["displayed_latest_label"] == (
        "2026-05"
    )
    assert saved_summary["generated_by"]["script_path"] == str(script_path)
    assert saved_bundle["charts"][0]["source_table_ids"] == ["T10Y2Y"]
    assert saved_bundle["charts"][0]["transform_ids"] == [
        "resampling",
        "normalization.base_date",
        "normalization.base_value",
    ]
    assert saved_bundle["charts"][0]["provenance"]["displayed_latest_label"] == "2026-05"
    assert handoff["chart_provenance"]["yield_spread"]["frequency"] == "daily"
    assert handoff["generated_by"]["script_path"] == str(script_path)


def test_save_quant_outputs_accepts_comma_delimited_chart_provenance_sources(tmp_path):
    qms.save_quant_outputs(
        tmp_path,
        {
            "sentiment_unemployment": {
                "type": "line",
                "title": "Sentiment and unemployment",
                "data": [
                    {"date": "2026-01", "sentiment": 71.7, "unrate": 4.0},
                    {"date": "2026-02", "sentiment": 64.7, "unrate": 4.1},
                ],
                "series": [
                    {"dataKey": "sentiment", "name": "Consumer sentiment"},
                    {"dataKey": "unrate", "name": "Unemployment rate"},
                ],
                "xAxis": {"dataKey": "date"},
                "transform_id": "sentiment_unemployment_correlation",
                "provenance": qms.chart_provenance(
                    source_series="UMCSENT, UNRATE",
                ),
            }
        },
        {
            "transforms": [
                {
                    "transform_id": "sentiment_unemployment_correlation",
                    "operation": "correlation",
                    "transform_basis": (
                        "Pearson correlation between monthly UMCSENT and "
                        "UNRATE observations over common dates"
                    ),
                    "source_ids": ["UMCSENT", "UNRATE"],
                    "source_groups": [["UMCSENT", "UNRATE"]],
                }
            ],
        },
    )

    saved_bundle = json.loads((tmp_path / "evidence_bundle.json").read_text())
    source_ids = [source["source_id"] for source in saved_bundle["sources"]]
    transform = saved_bundle["transforms"][0]

    assert source_ids == ["UMCSENT", "UNRATE"]
    assert transform["source_ids"] == ["UMCSENT", "UNRATE"]
    assert transform["source_groups"] == [["UMCSENT", "UNRATE"]]
    assert saved_bundle["charts"][0]["provenance"]["source_series"] == [
        "UMCSENT",
        "UNRATE",
    ]


def test_source_unit_helpers_flag_hourly_weekly_wage_mismatch(tmp_path):
    hourly_path = tmp_path / "hourly.csv"
    weekly_path = tmp_path / "weekly.csv"
    pd.DataFrame(
        [
            {
                "date": "2025-12-01",
                "value": 37.02,
                "series_id": "CES0500000008",
                "title": "Average Hourly Earnings of Production and Nonsupervisory Employees",
                "units": "dollars per hour",
            }
        ]
    ).to_csv(hourly_path, index=False)
    pd.DataFrame(
        [
            {
                "date": "2025-12-01",
                "value": 1072.67,
                "series_id": "CES0500000030",
                "title": "Average Weekly Earnings of Production and Nonsupervisory Employees",
                "units": "dollars per week",
            }
        ]
    ).to_csv(weekly_path, index=False)

    hourly = qms.source_unit_metadata("prod_hourly", source_file=hourly_path)
    weekly = qms.source_unit_metadata("prod_weekly", source_file=weekly_path)
    comparison = qms.unit_comparison(
        "production_wage_gap",
        [hourly, weekly],
        operation="difference",
        metric="production/nonsupervisory earnings gap",
    )

    assert hourly["unit_basis"] == "hour"
    assert weekly["unit_basis"] == "week"
    assert comparison["status"] == "failed"
    assert comparison["compatible"] is False
    assert "Convert compared sources to a common unit" in comparison["error"]


def test_save_quant_outputs_persists_source_and_transform_descriptors(tmp_path):
    hourly = qms.source_unit_metadata(
        "all_hourly",
        series_id="CES0500000003",
        title="Average Hourly Earnings of All Employees, Total Private",
        units="dollars per hour",
        frequency="monthly",
        currency="USD",
        fiscal_period="calendar_month",
        revision_policy="latest available vintage",
    )
    weekly = qms.source_unit_metadata(
        "prod_weekly",
        series_id="CES0500000030",
        title="Average Weekly Earnings of Production and Nonsupervisory Employees",
        units="dollars per week",
        frequency="monthly",
        currency="USD",
    )
    comparison = qms.unit_comparison(
        "wage_divergence",
        [hourly, weekly],
        conversion={"all_hourly": "multiply by average weekly hours"},
    )

    qms.save_quant_outputs(
        tmp_path,
        {},
        {
            "source_unit_metadata": [hourly, weekly],
            "unit_comparisons": [comparison],
        },
    )

    saved_bundle = json.loads((tmp_path / "evidence_bundle.json").read_text())
    sources = {source["source_id"]: source for source in saved_bundle["sources"]}
    transform = saved_bundle["transforms"][0]

    assert sources["all_hourly"]["unit_family"] == "currency_per_time"
    assert sources["all_hourly"]["unit_basis"] == "hour"
    assert sources["all_hourly"]["frequency"] == "monthly"
    assert sources["all_hourly"]["currency"] == "USD"
    assert sources["all_hourly"]["fiscal_period"] == "calendar_month"
    assert sources["all_hourly"]["revision_policy"] == "latest available vintage"
    assert transform["transform_id"] == "wage_divergence"
    assert transform["source_ids"] == ["all_hourly", "prod_weekly"]
    assert transform["source_groups"] == [["all_hourly", "prod_weekly"]]
    assert transform["conversion"] == {
        "source_conversions": {"all_hourly": "multiply by average weekly hours"}
    }


def test_save_quant_outputs_rejects_conversion_operation_without_details(tmp_path):
    hourly = qms.source_unit_metadata(
        "all_hourly",
        title="Average Hourly Earnings",
        units="dollars per hour",
        frequency="monthly",
    )
    weekly = qms.source_unit_metadata(
        "prod_weekly",
        title="Average Weekly Earnings",
        units="dollars per week",
        frequency="monthly",
    )

    with pytest.raises(ValueError, match="without conversion"):
        qms.save_quant_outputs(
            tmp_path,
            {},
            {
                "source_unit_metadata": [hourly, weekly],
                "transforms": [
                    {
                        "transform_id": "label_only_conversion",
                        "operation": "conversion",
                        "source_ids": ["all_hourly", "prod_weekly"],
                        "source_groups": [["all_hourly", "prod_weekly"]],
                    }
                ],
            },
        )


@pytest.mark.parametrize(
    ("conversion", "message"),
    [
        ("multiply hourly wages by weekly hours", "conversion must be a non-empty mapping"),
        ({"unrelated_label": "multiply hourly wages by weekly hours"}, "without conversion"),
        ({"description": "multiply hourly wages by weekly hours"}, "without conversion"),
        ({"method": "multiply hourly wages by weekly hours"}, "without conversion"),
    ],
)
def test_save_quant_outputs_rejects_unstructured_conversion_payload(
    tmp_path,
    conversion,
    message,
):
    hourly = qms.source_unit_metadata(
        "all_hourly",
        title="Average Hourly Earnings",
        units="dollars per hour",
        frequency="monthly",
    )
    weekly = qms.source_unit_metadata(
        "prod_weekly",
        title="Average Weekly Earnings",
        units="dollars per week",
        frequency="monthly",
    )

    with pytest.raises(ValueError, match=message):
        qms.save_quant_outputs(
            tmp_path,
            {},
            {
                "source_unit_metadata": [hourly, weekly],
                "transforms": [
                    {
                        "transform_id": "unstructured_conversion",
                        "source_ids": ["all_hourly", "prod_weekly"],
                        "source_groups": [["all_hourly", "prod_weekly"]],
                        "conversion": conversion,
                    }
                ],
            },
        )


def test_save_quant_outputs_rejects_flat_source_groups_payload(tmp_path):
    hourly = qms.source_unit_metadata(
        "all_hourly",
        title="Average Hourly Earnings",
        units="dollars per hour",
        frequency="monthly",
    )
    weekly = qms.source_unit_metadata(
        "prod_weekly",
        title="Average Weekly Earnings",
        units="dollars per week",
        frequency="monthly",
    )

    with pytest.raises(ValueError, match="source_groups must be a list"):
        qms.save_quant_outputs(
            tmp_path,
            {},
            {
                "source_unit_metadata": [hourly, weekly],
                "transforms": [
                    {
                        "transform_id": "flat_source_groups",
                        "source_ids": ["all_hourly", "prod_weekly"],
                        "source_groups": ["all_hourly", "prod_weekly"],
                        "conversion": {
                            "all_hourly": "multiply by average weekly hours"
                        },
                    }
                ],
            },
        )


@pytest.mark.parametrize(
    ("field_name", "values", "message"),
    [
        (
            "input_unit_families",
            ["currency_per_time", "index"],
            "incompatible unit families",
        ),
        ("input_unit_bases", ["hour", "week"], "incompatible unit bases"),
        ("input_frequencies", ["monthly", "quarterly"], "incompatible frequencies"),
    ],
)
def test_save_quant_outputs_rejects_declared_mixed_transform_inputs_without_alignment(
    tmp_path,
    field_name,
    values,
    message,
):
    source_a = qms.source_unit_metadata("source_a", title="Source A")
    source_b = qms.source_unit_metadata("source_b", title="Source B")

    with pytest.raises(ValueError, match=message):
        qms.save_quant_outputs(
            tmp_path,
            {},
            {
                "source_unit_metadata": [source_a, source_b],
                "transforms": [
                    {
                        "transform_id": f"declared_{field_name}",
                        "source_ids": ["source_a", "source_b"],
                        "source_groups": [["source_a", "source_b"]],
                        field_name: values,
                    }
                ],
            },
        )


def test_save_quant_outputs_allows_shared_transform_for_single_source_groups(tmp_path):
    labor_rate = qms.source_unit_metadata(
        "labor_rate",
        title="Monthly unemployment rate",
        units="percent",
        frequency="monthly",
    )
    revenue = qms.source_unit_metadata(
        "revenue",
        title="Company revenue",
        units="dollars",
        frequency="quarterly",
        currency="USD",
    )

    qms.save_quant_outputs(
        tmp_path,
        {
            "labor_rate_chart": {
                "type": "line",
                "data": [{"date": "2026-01", "value": 4.1}],
                "series": [{"dataKey": "value", "name": "Labor rate"}],
                "xAxis": {"dataKey": "date"},
                "transform_id": "line_projection",
                "provenance": qms.chart_provenance(source_series=["labor_rate"]),
            },
            "revenue_chart": {
                "type": "line",
                "data": [{"date": "2026-Q1", "value": 125_000_000.0}],
                "series": [{"dataKey": "value", "name": "Revenue"}],
                "xAxis": {"dataKey": "date"},
                "transform_id": "line_projection",
                "provenance": qms.chart_provenance(source_series=["revenue"]),
            },
        },
        {"source_unit_metadata": [labor_rate, revenue]},
    )

    saved_bundle = json.loads((tmp_path / "evidence_bundle.json").read_text())
    transform = saved_bundle["transforms"][0]

    assert transform["transform_id"] == "line_projection"
    assert transform["source_ids"] == ["labor_rate", "revenue"]
    assert transform["source_groups"] == [["labor_rate"], ["revenue"]]


def test_save_quant_outputs_rejects_mixed_frequency_chart_without_alignment(tmp_path):
    monthly = qms.source_unit_metadata(
        "monthly_rate",
        title="Monthly unemployment rate",
        units="percent",
        frequency="monthly",
    )
    quarterly = qms.source_unit_metadata(
        "quarterly_rate",
        title="Quarterly unemployment rate",
        units="percent",
        frequency="quarterly",
    )

    with pytest.raises(ValueError, match="incompatible frequencies"):
        qms.save_quant_outputs(
            tmp_path,
            {
                "rate_overlay": {
                    "type": "line",
                    "data": [{"date": "2026-Q1", "monthly": 4.1, "quarterly": 4.0}],
                    "series": [
                        {"dataKey": "monthly", "name": "Monthly"},
                        {"dataKey": "quarterly", "name": "Quarterly"},
                    ],
                    "xAxis": {"dataKey": "date"},
                    "transform_id": "direct_overlay",
                    "provenance": qms.chart_provenance(
                        source_series=["monthly_rate", "quarterly_rate"],
                    ),
                }
            },
            {"source_unit_metadata": [monthly, quarterly]},
        )


def test_save_quant_outputs_rejects_mixed_frequency_chart_with_label_only_resampling(
    tmp_path,
):
    monthly = qms.source_unit_metadata(
        "monthly_rate",
        title="Monthly unemployment rate",
        units="percent",
        frequency="monthly",
    )
    quarterly = qms.source_unit_metadata(
        "quarterly_rate",
        title="Quarterly unemployment rate",
        units="percent",
        frequency="quarterly",
    )

    with pytest.raises(ValueError, match="incompatible frequencies"):
        qms.save_quant_outputs(
            tmp_path,
            {
                "rate_overlay": {
                    "type": "line",
                    "data": [{"date": "2026-Q1", "monthly": 4.1, "quarterly": 4.0}],
                    "series": [
                        {"dataKey": "monthly", "name": "Monthly"},
                        {"dataKey": "quarterly", "name": "Quarterly"},
                    ],
                    "xAxis": {"dataKey": "date"},
                    "transform_id": "resampling",
                    "provenance": qms.chart_provenance(
                        source_series=["monthly_rate", "quarterly_rate"],
                    ),
                }
            },
            {"source_unit_metadata": [monthly, quarterly]},
        )


def test_save_quant_outputs_allows_mixed_unit_chart_with_provenance_normalization(
    tmp_path,
):
    labor_rate = qms.source_unit_metadata(
        "labor_rate",
        title="Monthly unemployment rate",
        units="percent",
        frequency="monthly",
    )
    retail_sales = qms.source_unit_metadata(
        "retail_sales",
        title="Monthly retail sales",
        units="dollars",
        frequency="monthly",
        currency="USD",
    )

    qms.save_quant_outputs(
        tmp_path,
        {
            "normalized_overlay": {
                "type": "line",
                "data": [
                    {
                        "date": "2026-01",
                        "labor_rate_index": 100.0,
                        "retail_sales_index": 100.0,
                    },
                    {
                        "date": "2026-02",
                        "labor_rate_index": 101.2,
                        "retail_sales_index": 99.7,
                    },
                ],
                "series": [
                    {"dataKey": "labor_rate_index", "name": "Labor rate"},
                    {"dataKey": "retail_sales_index", "name": "Retail sales"},
                ],
                "xAxis": {"dataKey": "date"},
                "provenance": qms.chart_provenance(
                    source_series=["labor_rate", "retail_sales"],
                    normalization={"base_date": "2026-01", "base_value": 100},
                ),
            }
        },
        {"source_unit_metadata": [labor_rate, retail_sales]},
    )

    saved_bundle = json.loads((tmp_path / "evidence_bundle.json").read_text())
    transforms = {
        transform["transform_id"]: transform for transform in saved_bundle["transforms"]
    }

    assert saved_bundle["charts"][0]["transform_ids"] == [
        "normalization.base_date",
        "normalization.base_value",
    ]
    assert transforms["normalization.base_date"]["operation"] == "normalized_index"
    assert transforms["normalization.base_value"]["operation"] == "normalized_index"
    assert transforms["normalization.base_date"]["transform_basis"] == (
        "base_date=2026-01; base_value=100"
    )


def test_transform_operation_helpers_classify_basis_required_labels():
    assert transform_operation_from_text("pearson_correlation") == "correlation"
    assert transform_operation_from_text("yoy_growth") == "growth_rate"
    assert transform_operation_from_text("z_score_normalization") == "normalized_index"
    assert transform_operation_requires_basis("z_score_normalization") is True
    assert transform_operation_requires_basis("quarterly_resampling") is False


def test_save_quant_outputs_requires_transform_basis_for_correlation_facts(tmp_path):
    with pytest.raises(ValueError, match="transform_basis is required"):
        qms.save_quant_outputs(
            tmp_path,
            {},
            {
                "numeric_facts": [
                    {
                        "id": "corr_UNRATE_CPIAUCSL",
                        "label": "Correlation(UNRATE, CPIAUCSL)",
                        "raw_value": 0.24,
                        "display_value": "0.24",
                        "unit": "correlation",
                        "precision": 2,
                        "tolerance": 0.005,
                        "source_key": "scenario_stress.corr.UNRATE.CPIAUCSL",
                    }
                ],
            },
        )


def test_save_quant_outputs_requires_transform_basis_for_typed_fact_operation(tmp_path):
    fact = qms.numeric_fact(
        fact_id="cpi_percent_change",
        label="CPI percent change",
        raw_value=3.2,
        unit="percent",
        precision=1,
        tolerance=0.05,
        source_key="CPIAUCSL",
        operation="percent_change",
    )

    with pytest.raises(ValueError, match="transform_basis is required"):
        qms.save_quant_outputs(
            tmp_path,
            {},
            {"numeric_facts": [fact]},
        )


def test_save_quant_outputs_rejects_mixed_source_transform_basis_without_label(
    tmp_path,
):
    level = qms.source_unit_metadata(
        "unrate_level",
        title="Unemployment rate",
        units="percent",
        frequency="monthly",
        transform_basis="level",
    )
    yoy = qms.source_unit_metadata(
        "cpi_yoy",
        title="CPI year-over-year rate",
        units="percent",
        frequency="monthly",
        transform_basis="yoy",
    )

    with pytest.raises(ValueError, match="incompatible transform bases"):
        qms.save_quant_outputs(
            tmp_path,
            {
                "mixed_basis_correlation": {
                    "type": "line",
                    "data": [
                        {
                            "date": "2026-01",
                            "unrate_level": 4.1,
                            "cpi_yoy": 2.7,
                        }
                    ],
                    "series": [
                        {"dataKey": "unrate_level", "name": "Unemployment"},
                        {"dataKey": "cpi_yoy", "name": "CPI yoy"},
                    ],
                    "xAxis": {"dataKey": "date"},
                    "transform_id": "rolling_correlation",
                    "transform_basis": "level correlation",
                    "provenance": qms.chart_provenance(
                        source_series=["unrate_level", "cpi_yoy"],
                    ),
                }
            },
            {"source_unit_metadata": [level, yoy]},
        )


def test_save_quant_outputs_allows_labeled_mixed_source_transform_basis(tmp_path):
    level = qms.source_unit_metadata(
        "unrate_level",
        title="Unemployment rate",
        units="percent",
        frequency="monthly",
        transform_basis="level",
    )
    yoy = qms.source_unit_metadata(
        "cpi_yoy",
        title="CPI year-over-year rate",
        units="percent",
        frequency="monthly",
        transform_basis="yoy",
    )

    qms.save_quant_outputs(
        tmp_path,
        {
            "mixed_basis_correlation": {
                "type": "line",
                "data": [
                    {"date": "2026-01", "unrate_level": 4.1, "cpi_yoy": 2.7}
                ],
                "series": [
                    {"dataKey": "unrate_level", "name": "Unemployment"},
                    {"dataKey": "cpi_yoy", "name": "CPI yoy"},
                ],
                "xAxis": {"dataKey": "date"},
                "transform_id": "rolling_correlation",
                "transform_basis": "level vs yoy correlation",
                "provenance": qms.chart_provenance(
                    source_series=["unrate_level", "cpi_yoy"],
                ),
            }
        },
        {"source_unit_metadata": [level, yoy]},
    )

    saved_bundle = json.loads((tmp_path / "evidence_bundle.json").read_text())
    assert saved_bundle["transforms"][0]["transform_basis"] == (
        "level vs yoy correlation"
    )


def test_save_quant_outputs_preserves_source_unit_metadata_from_source_files(tmp_path):
    weekly_path = tmp_path / "CES0500000030.csv"
    pd.DataFrame(
        [
            {
                "date": "2025-12-01",
                "value": 1072.67,
                "series_id": "CES0500000030",
            }
        ]
    ).to_csv(weekly_path, index=False)

    charts = {
        "weekly_wages": {
            "type": "line",
            "title": "Weekly Wages",
            "data": [{"date": "2025-12-01", "wages": 1072.67}],
            "series": [{"dataKey": "wages", "name": "Wages"}],
            "xAxis": {"dataKey": "date"},
            **_chart_traceability("weekly_wages", "weekly_wages_projection"),
        }
    }
    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {
            "methods_used": ["unit_test_method"],
            "source_files": {"weekly_wages": str(weekly_path)},
        },
    )
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text())

    source_units = saved_summary["source_unit_metadata"]
    assert source_units[0]["series_id"] == "CES0500000030"
    assert source_units[0]["units"] == "dollars per week"
    assert source_units[0]["unit_basis"] == "week"
    assert handoff["source_unit_metadata"][0]["unit_family"] == "currency_per_time"


def test_save_quant_outputs_preserves_bea_source_descriptors_from_source_files(tmp_path):
    bea_path = tmp_path / "bea_nipa_t10105.csv"
    pd.DataFrame(
        [
            {
                "date": "2025-10-01",
                "time_period": "2025Q4",
                "value": 29184.9,
                "provider": "BEA",
                "series_id": "BEA.NIPA.T10105.A191RC.Q",
                "concept_id": "A191RC",
                "table_name": "T10105",
                "table_title": "Table 1.1.5. Gross Domestic Product",
                "line_number": 1,
                "title": "Gross domestic product",
                "units": "Current Dollars",
                "frequency": "quarterly",
                "unit_mult": 6,
                "source": "BEA NIPA Data API",
                "source_url": "https://apps.bea.gov/api/data",
                "release_cadence": "quarterly GDP release cycle with annual NIPA updates",
                "revision_policy": "Latest available BEA NIPA estimates; subject to revisions.",
                "response_hash": "a" * 64,
            }
        ]
    ).to_csv(bea_path, index=False)

    charts = {
        "bea_gdp": {
            "type": "line",
            "title": "BEA GDP",
            "data": [{"date": "2025-10-01", "gdp": 29184.9}],
            "series": [{"dataKey": "gdp", "name": "GDP"}],
            "xAxis": {"dataKey": "date"},
            **_chart_traceability("bea_gdp", "bea_gdp_projection"),
        }
    }
    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {
            "methods_used": ["unit_test_method"],
            "source_files": {"bea_gdp": str(bea_path)},
        },
    )
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text())

    source_units = saved_summary["source_unit_metadata"]
    assert source_units[0]["provider"] == "BEA"
    assert source_units[0]["table_name"] == "T10105"
    assert source_units[0]["concept_id"] == "A191RC"
    assert source_units[0]["line_number"] == "1"
    assert source_units[0]["unit_mult"] == "6"
    assert source_units[0]["release_cadence"].startswith("quarterly GDP")
    assert source_units[0]["revision_policy"].startswith("Latest available BEA")
    assert handoff["source_unit_metadata"][0]["unit_family"] == "currency"


def test_save_quant_outputs_rejects_failed_source_unit_comparison(tmp_path):
    hourly = qms.source_unit_metadata(
        "all_hourly",
        series_id="CES0500000003",
        title="Average Hourly Earnings of All Employees, Total Private",
        units="dollars per hour",
    )
    weekly = qms.source_unit_metadata(
        "prod_weekly",
        series_id="CES0500000030",
        title="Average Weekly Earnings of Production and Nonsupervisory Employees",
        units="dollars per week",
    )
    comparison = qms.unit_comparison("wage_divergence", [hourly, weekly])

    with pytest.raises(ValueError, match="wage_divergence failed source-unit validation"):
        qms.save_quant_outputs(
            tmp_path,
            {
                "wages": {
                    "type": "line",
                    "data": [{"date": "2025", "value": 1}],
                    "series": [{"dataKey": "value", "name": "Value"}],
                    "xAxis": {"dataKey": "date"},
                }
            },
            {
                "source_unit_metadata": [hourly, weekly],
                "unit_comparisons": [comparison],
            },
        )


def test_save_quant_outputs_auto_attaches_sec_helper_evidence(tmp_path):
    sec_path = Path(_write_nvda_sec_company_facts(tmp_path / "NVDA_sec_edgar_company_facts.csv"))
    charts = {
        "income_statement": {
            "type": "line",
            "title": "Revenue",
            "data": [{"fiscal_year": "2026", "revenue": 215_938_000_000}],
            "series": [{"dataKey": "revenue", "name": "Revenue"}],
            "xAxis": {"dataKey": "fiscal_year"},
            **_chart_traceability(
                "sec_company_facts",
                "sec_income_statement_projection",
            ),
        }
    }
    manual_fact_source_keys = [
        "sec_company_facts",
        "NVDA_SEC",
        str(sec_path),
        sec_path.name,
        sec_path.stem,
    ]
    summary = {
        "title": "NVIDIA AI spending resilience",
        "source_files": {"sec_company_facts": str(sec_path)},
        "quant_input_manifest": {"data_files": {"NVDA_SEC": str(sec_path)}},
        "methods_used": ["manual_sec_summary"],
        "numeric_facts": [
            qms.numeric_fact(
                fact_id=f"manual_revenue_{index}",
                label="Latest revenue",
                raw_value=215_938_000_000,
                unit="$M",
                precision=0,
                tolerance=0.1,
                source_key=source_key,
            )
            for index, source_key in enumerate(manual_fact_source_keys)
        ]
        + [
            qms.numeric_fact(
                fact_id="fred_latest",
                label="FRED latest",
                raw_value=4.5,
                unit="percent",
                precision=1,
                tolerance=0.1,
                source_key="FRED.FEDFUNDS",
            )
        ],
    }

    handoff = qms.save_quant_outputs(tmp_path, charts, summary)
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text())
    saved_bundle = json.loads((tmp_path / "evidence_bundle.json").read_text())

    fact_ids = {fact["id"] for fact in saved_summary["numeric_facts"]}
    revenue_fact = next(
        fact
        for fact in saved_summary["numeric_facts"]
        if fact["id"] == "sec_company_facts.NVDA.revenue_b"
    )
    assert saved_summary["latest_fundamentals"]["NVDA"]["revenue_b"] == pytest.approx(215.938)
    assert saved_summary["latest_fundamentals"]["NVDA"]["cash_and_securities_b"] == pytest.approx(10.605)
    assert saved_summary["latest_fundamentals"]["NVDA"]["long_term_debt_b"] == pytest.approx(7.469)
    assert saved_summary["company_history_rows"][-1]["ticker"] == "NVDA"
    assert saved_summary["source_coverage"]["sec_company_facts"]["status"] == "covered"
    assert saved_summary["source_coverage"]["sec_company_facts"]["covered_tickers"] == ["NVDA"]
    assert saved_summary["sec_fact_provenance"]["NVDA"]["schema_version"] == 1
    assert revenue_fact["source_provenance_schema"] == "sec_company_facts_v1"
    assert revenue_fact["sec_fact_provenance"]["revenue"]["accession_number"] == (
        "0000000000-2026-000001"
    )
    assert "sec_company_fundamentals" in saved_summary["methods_used"]
    assert not any(fact_id.startswith("manual_revenue_") for fact_id in fact_ids)
    assert "fred_latest" in fact_ids
    assert "sec_company_facts.NVDA.revenue_b" in fact_ids
    bundle_revenue_fact = next(
        fact
        for fact in saved_bundle["facts"]
        if fact["fact_id"] == "sec_company_facts.NVDA.revenue_b"
    )
    assert bundle_revenue_fact["attributes"]["source_provenance_schema"] == (
        "sec_company_facts_v1"
    )
    sec_sources = {
        source["source_id"]: source
        for source in saved_bundle["sources"]
        if source["source_id"].startswith("sec_company_facts")
    }
    assert sec_sources["sec_company_facts"]["provider"] == "SEC EDGAR"
    assert sec_sources["sec_company_facts.NVDA"]["taxonomy"] == "us-gaap"
    market_source = next(
        source for source in saved_bundle["sources"] if source["source_id"] == "valuation_market_data"
    )
    assert market_source["status"] == "not_available"
    assert market_source["coverage"]["capability_list"]
    assert market_source["coverage"]["limitation"]
    assert handoff["latest_fundamentals"]["NVDA"]["revenue_b"] == pytest.approx(215.938)


def test_save_quant_outputs_sanitizes_split_affected_share_trends(tmp_path):
    sec_path = tmp_path / "AAPL_sec_edgar_company_facts.csv"
    pd.DataFrame(
        _with_sec_test_provenance(
            [
                {
                    "fiscal_year": 2019,
                    "revenue": 100_000_000_000,
                    "net_income": 20_000_000_000,
                    "shares": 4_650_000_000,
                },
                {
                    "fiscal_year": 2020,
                    "revenue": 110_000_000_000,
                    "net_income": 21_000_000_000,
                    "shares": 17_500_000_000,
                },
                {
                    "fiscal_year": 2021,
                    "revenue": 120_000_000_000,
                    "net_income": 22_000_000_000,
                    "shares": 16_900_000_000,
                },
            ]
        )
    ).to_csv(sec_path, index=False)
    charts = {
        "share_count_trend": {
            "type": "line",
            "title": "Shares Outstanding",
            "data": [
                {"fiscal_year": "2019", "AAPL": 4.65},
                {"fiscal_year": "2020", "AAPL": 17.5},
                {"fiscal_year": "2021", "AAPL": 16.9},
            ],
            "series": [{"dataKey": "AAPL", "name": "AAPL"}],
            "xAxis": {"dataKey": "fiscal_year"},
            **_chart_traceability(
                "sec_company_facts",
                "sec_share_count_trend",
            ),
            "provenance": qms.chart_provenance(source_series=["shares"]),
        }
    }

    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {
            "source_files": {"sec_company_facts": str(sec_path)},
            "quant_input_manifest": {"data_files": {"AAPL_SEC": str(sec_path)}},
            "statistical_summary": {"AAPL": {"shares_trend": "dilution"}},
        },
    )
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text())
    saved_charts = json.loads((tmp_path / "charts.json").read_text())

    diagnostic = saved_summary["share_count_diagnostics"]["AAPL"]
    assert diagnostic["status"] == "split_affected"
    assert saved_summary["statistical_summary"]["AAPL"]["shares_trend"] == (
        "raw_full_series_uncomparable"
    )
    assert saved_summary["statistical_summary"]["AAPL"][
        "shares_latest_comparable_trend"
    ] == "buyback"
    limitations = saved_summary["chart_provenance"]["share_count_trend"]["limitations"]
    assert any("Raw SEC share counts" in item for item in limitations)
    assert saved_charts["share_count_trend"]["provenance"]["limitations"] == limitations
    assert handoff["share_count_diagnostics"]["AAPL"]["comparability"] == (
        "raw_full_series_uncomparable"
    )


def test_save_quant_outputs_rejects_unbuildable_sec_helper_evidence(tmp_path):
    missing_path = tmp_path / "NVDA_sec_edgar_company_facts.csv"

    with pytest.raises(ValueError, match="SEC company-facts files are present"):
        qms.save_quant_outputs(
            tmp_path,
            {},
            {
                "source_files": {"NVDA_SEC": str(missing_path)},
                "numeric_facts": [
                    {
                        "id": "latest_revenue",
                        "display_value": "215,938,000,000",
                        "raw_value": 215_938_000_000,
                        "source_key": "NVDA_SEC",
                    }
                ],
            },
        )


def test_save_quant_outputs_rejects_conflicting_correlation_facts(tmp_path):
    charts = {
        "macro_correlation_heatmap": {
            "type": "bar",
            "title": "Macro Correlations",
            "data": [
                {
                    "pair": "(UNRATE, CPIAUCSL)",
                    "var1": "UNRATE",
                    "var2": "CPIAUCSL",
                    "correlation": 0.024,
                }
            ],
            "series": [{"dataKey": "correlation", "name": "Correlation"}],
            "xAxis": {"dataKey": "pair"},
        }
    }
    summary = {
        "scenario_stress": {
            "corr": {
                "UNRATE": {"UNRATE": 1.0, "CPIAUCSL": 0.908},
                "CPIAUCSL": {"UNRATE": 0.908, "CPIAUCSL": 1.0},
            }
        },
        "numeric_facts": [
            {
                "id": "corr_UNRATE_CPIAUCSL",
                "label": "Correlation(UNRATE, CPIAUCSL)",
                "raw_value": 0.024,
                "display_value": "0.024",
                "unit": "correlation",
                "tolerance": 0.005,
                "source_key": "scenario_stress.corr.UNRATE.CPIAUCSL",
            }
        ],
    }

    with pytest.raises(ValueError, match="artifact_fact_mismatch"):
        qms.save_quant_outputs(tmp_path, charts, summary)

    assert not (tmp_path / "charts.json").exists()
    assert not (tmp_path / "execution_summary.json").exists()


def test_artifact_fact_consistency_uses_numeric_fact_id_only_correlation_pair():
    consistency = artifact_fact_consistency_dict(
        execution_summary={
            "numeric_facts": [
                {
                    "id": "corr_UNRATE_CPIAUCSL",
                    "value": 0.024,
                    "display_value": "0.024",
                }
            ]
        },
        charts={
            "macro_correlation_heatmap": {
                "type": "bar",
                "data": [
                    {
                        "pair": "(UNRATE, CPIAUCSL)",
                        "var1": "UNRATE",
                        "var2": "CPIAUCSL",
                        "correlation": 0.908,
                    }
                ],
            }
        },
    )

    assert consistency["valid"] is False
    assert consistency["mismatches"][0]["pair"] == ["UNRATE", "CPIAUCSL"]
    assert "artifact_fact_mismatch" in artifact_fact_consistency_blocker(consistency)


def test_artifact_fact_consistency_parses_chart_pair_label_correlation_pair():
    consistency = artifact_fact_consistency_dict(
        execution_summary={
            "numeric_facts": [
                {
                    "id": "corr_UNRATE_CPIAUCSL",
                    "value": 0.024,
                    "display_value": "0.024",
                }
            ]
        },
        charts={
            "macro_correlation_heatmap": {
                "type": "bar",
                "data": [
                    {
                        "pair": "UNRATE/CPIAUCSL",
                        "correlation": 0.908,
                    }
                ],
            }
        },
    )

    assert consistency["valid"] is False
    assert consistency["mismatches"][0]["pair"] == ["UNRATE", "CPIAUCSL"]
    assert any(
        "macro_correlation_heatmap.data[0]" in observation["source"]
        for observation in consistency["mismatches"][0]["observations"]
    )


def test_save_quant_outputs_does_not_shape_scenario_score_rows(tmp_path):
    charts = {
        "scenario_scores": {
            "type": "bar",
            "title": "Scenario Scores",
            "data": [{"scenario": "caller base", "score": 0.2}],
            "series": [{"dataKey": "score", "name": "Score"}],
            "xAxis": {"dataKey": "scenario"},
            **_chart_traceability(
                "scenario_score_rows",
                "scenario_score_passthrough",
            ),
        }
    }
    scenario_rows = [
        {"name": "caller base", "score": 0.2, "note": "caller-owned evidence"},
    ]

    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {"scenario_score_rows": scenario_rows},
    )
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text())

    assert saved_summary["scenario_score_rows"] == scenario_rows
    assert handoff["scenario_score_rows"] == scenario_rows


def test_save_quant_outputs_overwrites_stale_artifacts_with_current_payload(tmp_path):
    stale_chart = {
        "type": "line",
        "title": "Stale",
        "data": [{"date": "2023-01", "value": 99}],
        "series": [{"dataKey": "value", "name": "Old"}],
        "xAxis": {"dataKey": "date"},
    }
    (tmp_path / "charts.json").write_text(
        json.dumps({"stale": stale_chart}),
        encoding="utf-8",
    )
    (tmp_path / "execution_summary.json").write_text(
        json.dumps(
            {
                "methods_used": ["old_method"],
                "chart_ids": ["stale"],
                "statistical_summary": "old summary",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "evidence_bundle.json").write_text(
        json.dumps({"bundle_type": "stale", "charts": [{"chart_id": "stale"}]}),
        encoding="utf-8",
    )

    handoff = qms.save_quant_outputs(
        tmp_path,
        {"empty_current_chart": {"type": "line", "data": []}},
        {
            "methods_used": ["current_method"],
            "statistical_summary": "current summary",
            "numeric_facts": [],
        },
    )
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text())
    saved_charts = json.loads((tmp_path / "charts.json").read_text())
    saved_bundle = json.loads((tmp_path / "evidence_bundle.json").read_text())

    assert handoff["chart_ids"] == []
    assert saved_summary["chart_ids"] == []
    assert saved_summary["methods_used"] == ["current_method"]
    assert saved_summary["statistical_summary"] == "current summary"
    assert saved_charts == {}
    assert saved_bundle["bundle_type"] == "quant_evidence_bundle"
    assert saved_bundle["charts"] == []
    assert saved_bundle["methods"] == ["current_method"]
    assert "preserved_prior_charts" not in saved_summary
    assert "preserved_report_aligned_charts" not in saved_summary


def test_save_quant_outputs_ignores_report_aligned_preservation_flags(tmp_path):
    stale_chart = {
        "type": "line",
        "title": "Stale",
        "data": [{"date": "2023-01", "value": 99}],
        "series": [{"dataKey": "value", "name": "Old"}],
        "xAxis": {"dataKey": "date"},
    }
    current_chart = {
        "type": "line",
        "title": "Current",
        "data": [{"date": "2024-01", "value": 1}],
        "series": [{"dataKey": "value", "name": "Current"}],
        "xAxis": {"dataKey": "date"},
        **_chart_traceability("current_source", "current_projection"),
    }
    (tmp_path / "charts.json").write_text(
        json.dumps({"stale": stale_chart}),
        encoding="utf-8",
    )
    (tmp_path / "report.json").write_text(
        json.dumps({"charts": [{"id": "stale"}]}),
        encoding="utf-8",
    )

    qms.save_quant_outputs(
        tmp_path,
        {"current": current_chart},
        {
            "methods_used": ["current_method"],
            "preserve_report_aligned_charts": True,
            "supplemental_validation_only": True,
        },
    )
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text())
    saved_charts = json.loads((tmp_path / "charts.json").read_text())

    assert list(saved_charts) == ["current"]
    assert saved_summary["chart_ids"] == ["current"]
    assert saved_summary["methods_used"] == ["current_method"]
    assert "preserve_report_aligned_charts" not in saved_summary
    assert "supplemental_validation_only" not in saved_summary
    assert "preserved_report_aligned_charts" not in saved_summary


def test_save_quant_outputs_rejects_duplicate_axis_rows_before_writes(tmp_path):
    charts = {
        "trend": {
            "type": "line",
            "title": "Trend",
            "xAxisKey": "date",
            "data": [
                {"date": "2024-01", "value": 1.0},
                {"date": "2024-01", "value": 2.0},
            ],
            "series": [{"dataKey": "value", "label": "Value"}],
            **_chart_traceability("FRED", "unit_test_projection"),
        }
    }

    with pytest.raises(ValueError) as exc:
        qms.save_quant_outputs(
            tmp_path,
            charts,
            {"methods_used": ["unit_test_method"]},
        )

    message = str(exc.value)
    assert "chart_source_table_validation failed" in message
    assert "chart 'trend' table 'chart_data:trend' column 'date'" in message
    assert "duplicate axis value '2024-01' at rows 0 and 1" in message
    _assert_no_quant_artifacts(tmp_path)


def test_save_quant_outputs_rejects_missing_declared_series_before_writes(tmp_path):
    charts = {
        "trend": {
            "type": "line",
            "title": "Trend",
            "xAxisKey": "date",
            "data": [{"date": "2024-01", "value": 1.0}],
            **_chart_traceability("FRED", "unit_test_projection"),
        }
    }

    with pytest.raises(ValueError) as exc:
        qms.save_quant_outputs(
            tmp_path,
            charts,
            {"methods_used": ["unit_test_method"]},
        )

    message = str(exc.value)
    assert "chart 'trend' table 'chart_data:trend' column 'series.dataKey'" in message
    assert "missing plotted series dataKey for non-empty axis chart data" in message
    _assert_no_quant_artifacts(tmp_path)


def test_save_quant_outputs_reports_missing_axis_and_series_before_writes(tmp_path):
    charts = {
        "trend": {
            "type": "line",
            "title": "Trend",
            "data": [{"date": "2024-01", "value": 1.0}],
            **_chart_traceability("FRED", "unit_test_projection"),
        }
    }

    with pytest.raises(ValueError) as exc:
        qms.save_quant_outputs(
            tmp_path,
            charts,
            {"methods_used": ["unit_test_method"]},
        )

    message = str(exc.value)
    assert "chart 'trend' table 'chart_data:trend' column 'xAxisKey'" in message
    assert "missing axis key for non-empty axis chart data" in message
    assert "chart 'trend' table 'chart_data:trend' column 'series.dataKey'" in message
    assert "missing plotted series dataKey for non-empty axis chart data" in message
    _assert_no_quant_artifacts(tmp_path)


def test_save_quant_outputs_rejects_untyped_numeric_axis_payload_before_writes(
    tmp_path,
):
    charts = {
        "trend": {
            "title": "Trend",
            "data": [
                {"date": "2024-01", "value": 1.0},
                {"date": "2024-02", "value": 2.0},
            ],
            **_chart_traceability("FRED", "unit_test_projection"),
        }
    }

    with pytest.raises(ValueError) as exc:
        qms.save_quant_outputs(
            tmp_path,
            charts,
            {"methods_used": ["unit_test_method"]},
        )

    message = str(exc.value)
    assert "chart_source_table_validation failed" in message
    assert "chart 'trend' table 'chart_data:trend' column 'xAxisKey'" in message
    assert "missing axis key for non-empty axis chart data" in message
    assert "chart 'trend' table 'chart_data:trend' column 'series.dataKey'" in message
    assert "missing plotted series dataKey for non-empty axis chart data" in message
    _assert_no_quant_artifacts(tmp_path)


def test_save_quant_outputs_rejects_missing_plotted_column_before_writes(tmp_path):
    charts = {
        "trend": {
            "type": "bar",
            "title": "Trend",
            "xAxisKey": "date",
            "data": [{"date": "2024-01", "other": 1.0}],
            "series": [{"dataKey": "value", "label": "Value"}],
            **_chart_traceability("FRED", "unit_test_projection"),
        }
    }

    with pytest.raises(ValueError) as exc:
        qms.save_quant_outputs(
            tmp_path,
            charts,
            {"methods_used": ["unit_test_method"]},
        )

    message = str(exc.value)
    assert "chart 'trend' table 'chart_data:trend' column 'value'" in message
    assert "series 'value' has no finite plotted values" in message
    assert "row 0 must contain at least one finite plotted value" in message
    _assert_no_quant_artifacts(tmp_path)


def test_save_quant_outputs_accepts_sparse_wide_axis_rows_before_writes(tmp_path):
    charts = {
        "cash_flow": {
            "type": "line",
            "title": "Cash Flow",
            "xAxisKey": "fiscal_year",
            "data": [
                {"fiscal_year": "2022", "ocf": 10.0, "capex": None},
                {"fiscal_year": "2023", "ocf": 12.0},
                {"fiscal_year": "2024", "ocf": 15.0, "capex": -2.0},
            ],
            "series": [
                {"dataKey": "ocf", "label": "Operating cash flow"},
                {"dataKey": "capex", "label": "Capital expenditures"},
            ],
            **_chart_traceability("SEC", "unit_test_projection"),
        }
    }

    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {"methods_used": ["unit_test_method"]},
    )
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text())
    saved_charts = json.loads((tmp_path / "charts.json").read_text())

    assert handoff["chart_ids"] == ["cash_flow"]
    assert saved_charts["cash_flow"]["data"] == charts["cash_flow"]["data"]
    assert saved_summary["chart_source_table_validation"]["cash_flow"]["series_keys"] == [
        "ocf",
        "capex",
    ]


def test_save_quant_outputs_rejects_sparse_wide_axis_row_without_values(tmp_path):
    charts = {
        "cash_flow": {
            "type": "line",
            "title": "Cash Flow",
            "xAxisKey": "fiscal_year",
            "data": [
                {"fiscal_year": "2022", "ocf": 10.0, "capex": None},
                {"fiscal_year": "2023", "ocf": None, "capex": None},
                {"fiscal_year": "2024", "ocf": 15.0, "capex": -2.0},
            ],
            "series": [
                {"dataKey": "ocf", "label": "Operating cash flow"},
                {"dataKey": "capex", "label": "Capital expenditures"},
            ],
            **_chart_traceability("SEC", "unit_test_projection"),
        }
    }

    with pytest.raises(ValueError) as exc:
        qms.save_quant_outputs(
            tmp_path,
            charts,
            {"methods_used": ["unit_test_method"]},
        )

    message = str(exc.value)
    assert "row 1 must contain at least one finite plotted value" in message
    _assert_no_quant_artifacts(tmp_path)


def test_save_quant_outputs_rejects_non_finite_plotted_values_before_writes(
    tmp_path,
):
    charts = {
        "trend": {
            "type": "line",
            "title": "Trend",
            "xAxisKey": "date",
            "data": [{"date": "2024-01", "value": float("nan")}],
            "series": [{"dataKey": "value", "label": "Value"}],
            **_chart_traceability("FRED", "unit_test_projection"),
        }
    }

    with pytest.raises(ValueError) as exc:
        qms.save_quant_outputs(
            tmp_path,
            charts,
            {"methods_used": ["unit_test_method"]},
        )

    message = str(exc.value)
    assert "chart 'trend' table 'chart_data:trend' column 'value'" in message
    assert "non-finite plotted value at row 0" in message
    _assert_no_quant_artifacts(tmp_path)


def test_save_quant_outputs_accepts_legacy_layout_series_declarations(tmp_path):
    charts = {
        "legacy_trend": {
            "type": "line",
            "title": "Legacy Trend",
            "layout": {
                "x_data_key": "date",
                "lines": [{"data_key": "value", "label": "Value"}],
            },
            "data": [{"date": "2024-01", "value": 1.0}],
            **_chart_traceability("FRED", "unit_test_projection"),
        }
    }

    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {"methods_used": ["unit_test_method"]},
    )
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text())
    saved_charts = json.loads((tmp_path / "charts.json").read_text())

    validation = saved_summary["chart_source_table_validation"]["legacy_trend"]
    assert handoff["chart_ids"] == ["legacy_trend"]
    assert saved_charts["legacy_trend"]["xAxisKey"] == "date"
    assert saved_charts["legacy_trend"]["series"] == [
        {"dataKey": "value", "label": "Value", "color": "#2563eb"}
    ]
    assert validation["axis_key"] == "date"
    assert validation["series_keys"] == ["value"]
    assert validation["columns"] == ["date", "value"]


def test_save_quant_outputs_rejects_ambiguous_grouped_axis_chart_before_writes(
    tmp_path,
):
    charts = {
        "margin_comparison": {
            "type": "line",
            "title": "Margin Comparison",
            "xAxisKey": "fiscal_year",
            "data": [
                {"fiscal_year": 2024, "ticker": "AAPL", "value": 45.0},
                {"fiscal_year": 2024, "ticker": "AAPL", "value": 31.0},
                {"fiscal_year": 2024, "ticker": "MSFT", "value": 44.0},
            ],
            "series": [
                {"dataKey": "value", "label": "AAPL", "color": "#3b82f6"},
                {"dataKey": "value", "label": "MSFT", "color": "#f59e0b"},
            ],
            "config": {"groupBy": "ticker"},
        }
    }

    with pytest.raises(ValueError) as exc:
        qms.save_quant_outputs(
            tmp_path,
            charts,
            {"methods_used": ["unit_test_method"]},
        )

    message = str(exc.value)
    assert (
        "chart 'margin_comparison' table 'chart_data:margin_comparison' "
        "column 'ticker'"
    ) not in message
    assert (
        "chart 'margin_comparison' table 'chart_source:margin_comparison' "
        "column 'ticker'"
    ) in message
    assert (
        "duplicate groupBy pair fiscal_year='2024' ticker='AAPL' at rows 0 and 1"
    ) in message
    _assert_no_quant_artifacts(tmp_path)


def test_save_quant_outputs_rejects_multi_datakey_grouped_axis_chart_before_writes(
    tmp_path,
):
    charts = {
        "multi_metric_peer_chart": {
            "type": "bar",
            "title": "Peer Metrics",
            "xAxisKey": "fiscal_year",
            "data": [
                {
                    "fiscal_year": 2024,
                    "ticker": "AAPL",
                    "revenue_growth": 6.0,
                    "operating_margin": 31.5,
                },
                {
                    "fiscal_year": 2024,
                    "ticker": "MSFT",
                    "revenue_growth": 15.7,
                    "operating_margin": 44.6,
                },
            ],
            "series": [
                {"dataKey": "revenue_growth", "label": "Revenue Growth"},
                {"dataKey": "operating_margin", "label": "Operating Margin"},
            ],
            "config": {"groupBy": "ticker"},
        }
    }

    with pytest.raises(ValueError) as exc:
        qms.save_quant_outputs(
            tmp_path,
            charts,
            {"methods_used": ["unit_test_method"]},
        )

    message = str(exc.value)
    assert (
        "chart 'multi_metric_peer_chart' table "
        "'chart_source:multi_metric_peer_chart' column 'series.dataKey'"
    ) in message
    assert (
        "groupBy axis charts must declare one shared plotted dataKey; "
        "got revenue_growth, operating_margin"
    ) in message
    _assert_no_quant_artifacts(tmp_path)


def test_save_quant_outputs_rejects_grouped_axis_chart_without_provenance(
    tmp_path,
):
    charts = {
        "cagr_summary": {
            "type": "bar",
            "title": "5-Year CAGR Comparison",
            "xAxisKey": "metric",
            "data": [
                {"metric": "Revenue", "ticker": "AAPL", "cagr": 6.2},
                {"metric": "Revenue", "ticker": "MSFT", "cagr": 12.1},
                {"metric": "FCF", "ticker": "AAPL", "cagr": 8.4},
                {"metric": "FCF", "ticker": "MSFT", "cagr": 9.7},
            ],
            "series": [
                {"dataKey": "cagr", "label": "AAPL", "color": "#3b82f6"},
                {"dataKey": "cagr", "label": "MSFT", "color": "#f59e0b"},
            ],
            "config": {"groupBy": "ticker"},
        }
    }

    with pytest.raises(ValueError) as exc:
        qms.save_quant_outputs(tmp_path, charts, {})

    assert "source_table_ids" in str(exc.value)
    _assert_no_quant_artifacts(tmp_path)


def test_save_quant_outputs_saves_valid_grouped_axis_chart_with_validation_metadata(
    tmp_path,
):
    charts = {
        "cagr_summary": {
            "type": "bar",
            "title": "5-Year CAGR Comparison",
            "xAxisKey": "metric",
            "data": [
                {"metric": "Revenue", "ticker": "AAPL", "cagr": 6.2},
                {"metric": "Revenue", "ticker": "MSFT", "cagr": 12.1},
                {"metric": "FCF", "ticker": "AAPL", "cagr": 8.4},
                {"metric": "FCF", "ticker": "MSFT", "cagr": 9.7},
            ],
            "series": [
                {"dataKey": "cagr", "label": "AAPL", "color": "#3b82f6"},
                {"dataKey": "cagr", "label": "MSFT", "color": "#f59e0b"},
            ],
            "config": {"groupBy": "ticker"},
            **_chart_traceability("SEC", "unit_test_projection"),
        }
    }

    handoff = qms.save_quant_outputs(
        tmp_path,
        charts,
        {"methods_used": ["unit_test_method"]},
    )
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text())
    saved_charts = json.loads((tmp_path / "charts.json").read_text())
    saved_bundle = json.loads((tmp_path / "evidence_bundle.json").read_text())

    source_validation = saved_summary["chart_source_table_validation"]["cagr_summary"]
    render_validation = saved_summary["chart_render_table_validation"]["cagr_summary"]
    projection = saved_summary["chart_projection_transforms"]["cagr_summary"]
    assert handoff["chart_ids"] == ["cagr_summary"]
    assert handoff["chart_projection_transforms"] == {
        "cagr_summary": projection,
    }
    assert saved_charts["cagr_summary"]["series"] == [
        {"dataKey": "AAPL", "label": "AAPL", "color": "#3b82f6"},
        {"dataKey": "MSFT", "label": "MSFT", "color": "#f59e0b"},
    ]
    assert saved_charts["cagr_summary"]["data"] == [
        {"metric": "Revenue", "AAPL": 6.2, "MSFT": 12.1},
        {"metric": "FCF", "AAPL": 8.4, "MSFT": 9.7},
    ]
    assert source_validation == {
        "status": "valid",
        "validation_version": 1,
        "chart_id": "cagr_summary",
        "table_id": "chart_source:cagr_summary",
        "chart_type": "bar",
        "axis_key": "metric",
        "series_keys": ["cagr"],
        "row_count": 4,
        "columns": ["metric", "ticker", "cagr"],
        "group_by_key": "ticker",
        "unique_axis_values": 2,
        "unique_group_pairs": 4,
    }
    assert render_validation == {
        "status": "valid",
        "validation_version": 1,
        "chart_id": "cagr_summary",
        "table_id": "chart_data:cagr_summary",
        "chart_type": "bar",
        "axis_key": "metric",
        "series_keys": ["AAPL", "MSFT"],
        "row_count": 2,
        "columns": ["metric", "AAPL", "MSFT"],
        "unique_axis_values": 2,
    }
    assert projection == {
        "projection_version": 1,
        "transform_id": "chart_projection:cagr_summary:long_to_wide",
        "chart_id": "cagr_summary",
        "operation": "long_to_wide_grouped_axis",
        "source_table_id": "chart_source:cagr_summary",
        "render_table_id": "chart_data:cagr_summary",
        "axis_key": "metric",
        "group_by_key": "ticker",
        "value_key": "cagr",
        "group_values": ["AAPL", "MSFT"],
        "source_columns": ["metric", "ticker", "cagr"],
        "render_columns": ["metric", "AAPL", "MSFT"],
        "source_row_count": 4,
        "render_row_count": 2,
        "metadata": {},
    }
    tables = {table["table_id"]: table for table in saved_bundle["normalized_tables"]}
    assert tables["chart_source:cagr_summary"]["role"] == "chart_source_data"
    assert tables["chart_source:cagr_summary"]["row_count"] == 4
    assert tables["chart_source:cagr_summary"]["columns"] == [
        "metric",
        "ticker",
        "cagr",
    ]
    assert (
        tables["chart_source:cagr_summary"]["metadata"][
            "chart_source_table_validation"
        ]
        == source_validation
    )
    assert tables["chart_data:cagr_summary"]["role"] == "chart_data"
    assert tables["chart_data:cagr_summary"]["row_count"] == 2
    assert tables["chart_data:cagr_summary"]["columns"] == [
        "metric",
        "AAPL",
        "MSFT",
    ]
    assert (
        tables["chart_data:cagr_summary"]["metadata"][
            "chart_render_table_validation"
        ]
        == render_validation
    )
    bundle_chart = saved_bundle["charts"][0]
    assert bundle_chart["source_table_ids"] == [
        "chart_source:cagr_summary",
        "chart_data:cagr_summary",
    ]
    assert bundle_chart["transform_ids"] == [
        "unit_test_projection",
        "chart_projection:cagr_summary:long_to_wide",
    ]
    transforms = {
        transform["transform_id"]: transform for transform in saved_bundle["transforms"]
    }
    assert transforms["chart_projection:cagr_summary:long_to_wide"]["operation"] == (
        "long_to_wide_grouped_axis"
    )
    assert transforms["chart_projection:cagr_summary:long_to_wide"][
        "source_table_ids"
    ] == ["chart_source:cagr_summary", "chart_data:cagr_summary"]


def test_normalize_quant_report_charts_returns_dropped_ids():
    result = normalize_quant_report_charts(
        {
            "usable": {
                "type": "bar",
                "data": [{"name": "A", "value": 2}],
                "series": [{"dataKey": "value"}],
                "xAxis": {"dataKey": "name"},
            },
            "blank": {"type": "bar", "data": []},
        }
    )

    assert result["chart_ids"] == ["usable"]
    assert result["dropped_chart_ids"] == ["blank"]


def test_normalize_quant_report_charts_pivots_grouped_axis_long_form():
    result = normalize_quant_report_charts(
        {
            "cagr_summary": {
                "type": "bar",
                "title": "5-Year CAGR Comparison",
                "xAxisKey": "metric",
                "data": [
                    {"metric": "Revenue", "ticker": "AAPL", "cagr": 6.2},
                    {"metric": "Revenue", "ticker": "MSFT", "cagr": 12.1},
                    {"metric": "FCF", "ticker": "AAPL", "cagr": 8.4},
                    {"metric": "FCF", "ticker": "MSFT", "cagr": 9.7},
                ],
                "series": [
                    {"dataKey": "cagr", "label": "AAPL", "color": "#3b82f6"},
                    {"dataKey": "cagr", "label": "MSFT", "color": "#f59e0b"},
                ],
                "config": {"groupBy": "ticker"},
            }
        }
    )

    chart = result["charts"]["cagr_summary"]

    assert result["chart_ids"] == ["cagr_summary"]
    assert result["dropped_chart_ids"] == []
    assert chart["series"] == [
        {"dataKey": "AAPL", "label": "AAPL", "color": "#3b82f6"},
        {"dataKey": "MSFT", "label": "MSFT", "color": "#f59e0b"},
    ]
    assert chart["data"] == [
        {"metric": "Revenue", "AAPL": 6.2, "MSFT": 12.1},
        {"metric": "FCF", "AAPL": 8.4, "MSFT": 9.7},
    ]
    assert "config" not in chart
    assert result["chart_projection_transforms"] == {
        "cagr_summary": {
            "projection_version": 1,
            "transform_id": "chart_projection:cagr_summary:long_to_wide",
            "chart_id": "cagr_summary",
            "operation": "long_to_wide_grouped_axis",
            "source_table_id": "chart_source:cagr_summary",
            "render_table_id": "chart_data:cagr_summary",
            "axis_key": "metric",
            "group_by_key": "ticker",
            "value_key": "cagr",
            "group_values": ["AAPL", "MSFT"],
            "source_columns": ["metric", "ticker", "cagr"],
            "render_columns": ["metric", "AAPL", "MSFT"],
            "source_row_count": 4,
            "render_row_count": 2,
            "metadata": {},
        }
    }
    assert result["chart_normalization_issues"] == {
        "cagr_summary": [
            "converted unsupported groupBy=ticker long-form cagr chart into wide series columns"
        ]
    }


def test_normalize_quant_report_charts_drops_lossy_grouped_axis_projection():
    result = normalize_quant_report_charts(
        {
            "cagr_summary": {
                "type": "bar",
                "title": "5-Year CAGR Comparison",
                "xAxisKey": "metric",
                "data": [
                    {"metric": "Revenue", "ticker": "AAPL", "cagr": 6.2},
                    {"metric": "Revenue", "ticker": "MSFT", "cagr": None},
                ],
                "series": [
                    {"dataKey": "cagr", "label": "AAPL", "color": "#3b82f6"},
                    {"dataKey": "cagr", "label": "MSFT", "color": "#f59e0b"},
                ],
                "config": {"groupBy": "ticker"},
            }
        }
    )

    assert result["charts"] == {}
    assert result["chart_ids"] == []
    assert result["dropped_chart_ids"] == ["cagr_summary"]
    assert result["chart_projection_transforms"] == {}
    assert result["chart_normalization_issues"] == {
        "cagr_summary": [
            "dropped unsupported groupBy=ticker chart: row has non-finite cagr value"
        ]
    }


def test_normalize_quant_report_charts_labels_single_metric_grouped_series_by_group():
    result = normalize_quant_report_charts(
        {
            "cagr_summary": {
                "type": "bar",
                "title": "5-Year CAGR Comparison",
                "xAxisKey": "metric",
                "data": [
                    {"metric": "Revenue", "ticker": "AAPL", "cagr": 6.2},
                    {"metric": "Revenue", "ticker": "MSFT", "cagr": 12.1},
                    {"metric": "FCF", "ticker": "AAPL", "cagr": 8.4},
                    {"metric": "FCF", "ticker": "MSFT", "cagr": 9.7},
                ],
                "series": [
                    {"dataKey": "cagr", "label": "CAGR", "color": "#3b82f6"},
                ],
                "config": {"groupBy": "ticker"},
            }
        }
    )

    chart = result["charts"]["cagr_summary"]

    assert chart["series"] == [
        {"dataKey": "AAPL", "label": "AAPL", "color": "#3b82f6"},
        {"dataKey": "MSFT", "label": "MSFT", "color": "#2563eb"},
    ]
    assert chart["data"] == [
        {"metric": "Revenue", "AAPL": 6.2, "MSFT": 12.1},
        {"metric": "FCF", "AAPL": 8.4, "MSFT": 9.7},
    ]
