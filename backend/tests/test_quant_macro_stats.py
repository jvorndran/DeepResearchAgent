import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from agents import quant_macro_stats as qms
from agents.quant_macro_stats.artifacts.recharts_schema_normalization import (
    normalize_quant_report_charts,
)
from agents.quant_macro_stats.data.series_input_resolution import SeriesSpec, load_monthly_panel


def _write_series(path: Path, values: list[tuple[str, float]]) -> str:
    pd.DataFrame(values, columns=["date", "value"]).to_csv(path, index=False)
    return str(path)


def _write_nvda_sec_company_facts(path: Path) -> str:
    pd.DataFrame(
        {
            "fiscal_year": [2025, 2026],
            "revenue": [130_497_000_000, 215_938_000_000],
            "gross_profit": [97_858_000_000, 153_865_000_000],
            "operating_income": [81_453_000_000, 136_859_000_000],
            "net_income": [72_880_000_000, 120_224_000_000],
            "operating_cash_flow": [64_089_000_000, 118_200_000_000],
            "capital_expenditures": [3_236_000_000, 21_524_000_000],
            "cash_and_equivalents": [8_589_000_000, 8_589_000_000],
            "marketable_securities_current": [1_716_000_000, 2_016_000_000],
            "long_term_debt": [8_463_000_000, 7_469_000_000],
            "stockholders_equity": [65_000_000_000, 79_000_000_000],
            "assets": [111_601_000_000, 124_092_000_000],
            "liabilities": [32_274_000_000, 45_000_000_000],
            "diluted_eps": [2.94, 4.90],
            "shares": [24_700_000_000, 24_514_000_000],
        }
    ).to_csv(path, index=False)
    return str(path)


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
    assert "sec_company_facts_evidence(data_files" in catalog
    assert "chart_provenance(source_series=..." in catalog
    assert "source_unit_metadata(source_key, source_file=..." in catalog
    assert "unit_comparison(comparison_id, sources" in catalog
    assert "latest_numeric_fact(panel, key" in catalog
    assert "raw_value" in catalog
    assert "display_value" in catalog
    assert "save_quant_outputs(output_dir, charts, execution_summary)" in catalog
    assert {"load_monthly_panel", "direct_ols_forecast", "save_quant_outputs"}.issubset(
        helper_names
    )
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
    assert "Malformed execution_summary.numeric_facts" in message
    assert "macro.cpi_yoy.latest" in message
    assert "raw_value" in message
    assert "display_value" in message
    assert "numeric_facts[1]: expected object" in message
    assert "latest_numeric_fact(...)" in message


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
        {
            "fiscal_year": [2022, 2023, 2024],
            "revenue": [100_000_000_000, 125_000_000_000, 150_000_000_000],
            "gross_profit": [40_000_000_000, 55_000_000_000, 70_000_000_000],
            "operating_income": [30_000_000_000, 42_000_000_000, 55_000_000_000],
            "net_income": [20_000_000_000, 28_000_000_000, 36_000_000_000],
            "operating_cash_flow": [25_000_000_000, 34_000_000_000, 44_000_000_000],
            "capital_expenditures": [5_000_000_000, 6_000_000_000, 8_000_000_000],
            "cash_and_equivalents": [12_000_000_000, 14_000_000_000, 16_000_000_000],
            "marketable_securities_current": [8_000_000_000, 10_000_000_000, 12_000_000_000],
            "long_term_debt": [30_000_000_000, 32_000_000_000, 35_000_000_000],
            "stockholders_equity": [60_000_000_000, 70_000_000_000, 80_000_000_000],
            "assets": [160_000_000_000, 180_000_000_000, 210_000_000_000],
            "liabilities": [100_000_000_000, 110_000_000_000, 130_000_000_000],
            "diluted_eps": [1.25, 1.9, 2.6],
            "shares": [16_000_000_000, 15_000_000_000, 14_000_000_000],
        }
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
    assert evidence["source_coverage"]["sec_company_facts"]["status"] == "covered"
    assert evidence["limitations"]
    assert "contract_type" not in evidence


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
                source_key="unit_test",
            )
        ],
        "source_coverage": {"FRED": ["UNRATE"]},
    }

    handoff = qms.save_quant_outputs(tmp_path, charts, summary)
    saved_summary = json.loads((tmp_path / "execution_summary.json").read_text())
    saved_charts = json.loads((tmp_path / "charts.json").read_text())

    assert handoff["chart_ids"] == ["trend"]
    assert saved_summary["chart_ids"] == ["trend"]
    assert saved_summary["numeric_facts"][0]["id"] == "latest_value"
    assert list(saved_charts) == ["trend"]
    assert "preserved_prior_charts" not in handoff
    assert "preserved_report_aligned_charts" not in handoff


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

    assert saved_charts["yield_spread"]["provenance"]["raw_latest_observation"] == {
        "T10Y2Y": "2026-05-15"
    }
    assert saved_summary["chart_provenance"]["yield_spread"]["displayed_latest_label"] == (
        "2026-05"
    )
    assert saved_summary["generated_by"]["script_path"] == str(script_path)
    assert handoff["chart_provenance"]["yield_spread"]["frequency"] == "daily"
    assert handoff["generated_by"]["script_path"] == str(script_path)


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
            {"wages": {"type": "line", "data": [{"date": "2025", "value": 1}]}},
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

    fact_ids = {fact["id"] for fact in saved_summary["numeric_facts"]}
    assert saved_summary["latest_fundamentals"]["NVDA"]["revenue_b"] == pytest.approx(215.938)
    assert saved_summary["latest_fundamentals"]["NVDA"]["cash_and_securities_b"] == pytest.approx(10.605)
    assert saved_summary["latest_fundamentals"]["NVDA"]["long_term_debt_b"] == pytest.approx(7.469)
    assert saved_summary["company_history_rows"][-1]["ticker"] == "NVDA"
    assert saved_summary["source_coverage"]["sec_company_facts"]["status"] == "covered"
    assert "sec_company_fundamentals" in saved_summary["methods_used"]
    assert not any(fact_id.startswith("manual_revenue_") for fact_id in fact_ids)
    assert "fred_latest" in fact_ids
    assert "sec_company_facts.NVDA.revenue_b" in fact_ids
    assert handoff["latest_fundamentals"]["NVDA"]["revenue_b"] == pytest.approx(215.938)


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


def test_save_quant_outputs_does_not_shape_scenario_score_rows(tmp_path):
    charts = {
        "scenario_scores": {
            "type": "bar",
            "title": "Scenario Scores",
            "data": [{"scenario": "caller base", "score": 0.2}],
            "series": [{"dataKey": "score", "name": "Score"}],
            "xAxis": {"dataKey": "scenario"},
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

    assert handoff["chart_ids"] == []
    assert saved_summary["chart_ids"] == []
    assert saved_summary["methods_used"] == ["current_method"]
    assert saved_summary["statistical_summary"] == "current summary"
    assert saved_charts == {}
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
