# Quant Macro Stats Helper Package

This package is a helper library for generated `analysis.py` scripts. Keep
helpers deterministic, local-data only, and reusable across report types.

## Structure

- `__init__.py`: stable public facade. Quant scripts should import from
  `agents.quant_macro_stats` so internal files can move without breaking agent
  code.
- `catalog.py`: compact agent-facing helper catalog embedded in the quantitative
  developer prompt and guardrail messages.
- `data/`: data-file resolution, series loading, frequency alignment, and
  time-series observation helpers.
- `stats/`: reusable statistical helpers for correlations, forecasts,
  backtests, predictive indicators, regimes, scenarios, and analog windows.
- `evidence/`: forecast, scenario, and analog evidence-row normalization.
- `company/`: SEC company-facts source detection and generic company evidence.
- `artifacts/`: chart cleanup, execution-summary normalization, numeric facts,
  and final artifact writes.

Root-level implementation modules are intentionally not compatibility surfaces.
Generated quant scripts should import helper functions from
`agents.quant_macro_stats`; new agent-facing helpers should be exposed through
`__init__.py` and described in `catalog.py`.
