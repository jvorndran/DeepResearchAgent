"""Statistical helper modules for quant scripts."""

from .analog_window_comparison import (
    analog_window_profile,
    build_analog_evidence,
    compare_analog_windows,
    normalize_analog_ranking,
)
from .composite_predictive_indicators import build_composite_predictive_indicator
from .correlation_analysis import (
    lead_lag_correlations,
    rolling_correlation,
)
from .event_signal_backtesting import event_signal_backtest, signal_framework_backtest
from .forecast_backtesting import walk_forward_ols_backtest
from .historical_scenario_replay import historical_scenario_replay
from .ols_forecasting import (
    direct_ols_forecast,
    ols_regression,
)
from .recession_regime_classification import classify_recession_regime
from .recession_signal_facts import sahm_rule_signal
from .recession_window_analysis import recession_window_summary
from ..artifacts.method_metadata import attach_methods_used, attach_summary_methods
from ..evidence.scenario_evidence_rows import (
    normalize_scenario_evidence_rows,
    normalize_scenario_projection_rows,
)

__all__ = [
    "analog_window_profile",
    "attach_methods_used",
    "attach_summary_methods",
    "build_analog_evidence",
    "build_composite_predictive_indicator",
    "classify_recession_regime",
    "compare_analog_windows",
    "direct_ols_forecast",
    "event_signal_backtest",
    "historical_scenario_replay",
    "lead_lag_correlations",
    "normalize_analog_ranking",
    "ols_regression",
    "recession_window_summary",
    "rolling_correlation",
    "sahm_rule_signal",
    "signal_framework_backtest",
    "normalize_scenario_evidence_rows",
    "normalize_scenario_projection_rows",
    "walk_forward_ols_backtest",
]
