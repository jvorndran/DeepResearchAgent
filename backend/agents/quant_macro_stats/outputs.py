"""Artifact serialization for generated quant scripts."""
from .shared import *
from .shared import (
    _adfuller,
    _as_ordered_frame,
    _clean_regression_frame,
    _direction_multiplier,
    _finite_float,
    _iso_date,
    _require_columns,
    _scipy_stats,
    _statsmodels_api,
)
from .charts import (
    _chart_map_from_payload,
    _drop_empty_chart_definitions,
    _normalize_declared_since_lists,
)
from .normalization import (
    _normalize_legacy_scenario_summary,
    _normalize_validation_handoff,
)

def save_quant_outputs(
    output_dir: str | Path,
    charts: dict[str, Any] | list[dict[str, Any]],
    execution_summary: dict[str, Any],
    *,
    statistical_summary_excerpt: str | None = None,
) -> dict[str, Any]:
    """Save canonical quant artifacts and return the compact handoff JSON.

    Generated ``analysis.py`` scripts use this to avoid custom serializers and
    stale ``chart_ids`` lists. The helper writes strict JSON with ``NaN`` values
    converted to ``None``.
    """

    if not isinstance(execution_summary, dict):
        raise ValueError("execution_summary must be a JSON object")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    charts_path = output_path / "charts.json"
    summary_path = output_path / "execution_summary.json"

    chart_map, dropped_chart_ids = _drop_empty_chart_definitions(_chart_map_from_payload(charts))
    preserved_prior_charts = False
    if not chart_map and charts_path.exists():
        try:
            existing_chart_map = _chart_map_from_payload(
                json.loads(charts_path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, ValueError):
            existing_chart_map = {}
        if existing_chart_map:
            chart_map = existing_chart_map
            preserved_prior_charts = True
    chart_ids = list(chart_map.keys())

    summary = deepcopy(execution_summary)
    _normalize_legacy_scenario_summary(summary)
    _normalize_validation_handoff(summary)
    _normalize_declared_since_lists(summary)
    summary["charts_json"] = str(charts_path)
    summary["execution_summary_json"] = str(summary_path)
    summary["chart_ids"] = chart_ids
    if dropped_chart_ids:
        summary["dropped_chart_ids"] = dropped_chart_ids
    if preserved_prior_charts:
        summary["preserved_prior_charts"] = True

    if not preserved_prior_charts:
        charts_path.write_text(
            json.dumps(to_json_safe(chart_map), indent=2, allow_nan=False),
            encoding="utf-8",
        )
    summary_path.write_text(
        json.dumps(to_json_safe(summary), indent=2, allow_nan=False),
        encoding="utf-8",
    )

    excerpt = statistical_summary_excerpt
    if excerpt is None:
        excerpt = str(summary.get("statistical_summary", ""))[:600]

    return {
        "charts_json": str(charts_path),
        "execution_summary_json": str(summary_path),
        "chart_ids": chart_ids,
        "dropped_chart_ids": dropped_chart_ids,
        "preserved_prior_charts": preserved_prior_charts,
        "statistical_summary_excerpt": str(excerpt)[:600],
    }
