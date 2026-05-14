"""Subagent configuration for quantitative developer."""

from .constants import _BACKEND_DIR
from .middleware import QuantDeveloperToolBoundaryMiddleware
from .prompts import QUANT_DEVELOPER_SYSTEM_PROMPT
from .tools import (
    build_consumer_stress_dashboard_artifacts,
    build_historical_replay_chart_pack_artifacts,
    build_inflation_policy_chart_pack_artifacts,
    build_macro_cycle_chart_pack_artifacts,
    build_recession_dashboard_artifacts,
    build_unemployment_forecast_chart_pack_artifacts,
)

_TOOL_BOUNDARY_MIDDLEWARE = QuantDeveloperToolBoundaryMiddleware()

# SUBAGENT CONFIGURATION
# =============================================================================

QUANT_DEVELOPER_SUBAGENT = {
    "name": "quant-developer",
    "description": """Use this subagent to generate and execute Python analysis code.

    Delegate when you need to:
    - Generate pandas/numpy/scipy code from data schemas
    - Execute code in the sandbox environment
    - Create named chart definitions (charts.json dict) for Recharts
    - Perform statistical analysis, correlations, or calculations

    Provide the exact data schemas, file paths, and analysis goal.
    The quant developer will write code, run it, fix any errors, and return
    a charts.json path, execution_summary.json path, chart IDs, and a short
    statistical summary excerpt. Full computed values are saved to execution_summary.json.""",
    "system_prompt": QUANT_DEVELOPER_SYSTEM_PROMPT,
    "tools": [
        build_recession_dashboard_artifacts,
        build_inflation_policy_chart_pack_artifacts,
        build_consumer_stress_dashboard_artifacts,
        build_historical_replay_chart_pack_artifacts,
        build_unemployment_forecast_chart_pack_artifacts,
        build_macro_cycle_chart_pack_artifacts,
    ],
    "model": "deepseek:deepseek-chat",
    "middleware": [_TOOL_BOUNDARY_MIDDLEWARE],
    "skills": [str(_BACKEND_DIR / "skills" / "quant-developer")],
}
