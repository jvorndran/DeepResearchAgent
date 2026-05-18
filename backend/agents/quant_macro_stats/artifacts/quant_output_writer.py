"""Artifact serialization for generated quant scripts."""

import json
from pathlib import Path
from typing import Any

from .json_safety import to_json_safe
from .recharts_schema_normalization import (
    _chart_map_from_payload,
    _drop_empty_chart_definitions,
    _normalize_declared_since_lists,
)
from .execution_summary_normalization import (
    build_quant_output_handoff,
    normalize_quant_execution_summary,
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
    chart_ids = list(chart_map.keys())

    summary = normalize_quant_execution_summary(execution_summary)
    _normalize_declared_since_lists(summary)

    summary["charts_json"] = str(charts_path)
    summary["execution_summary_json"] = str(summary_path)
    summary["chart_ids"] = chart_ids
    if dropped_chart_ids:
        summary["dropped_chart_ids"] = dropped_chart_ids

    charts_path.write_text(
        json.dumps(to_json_safe(chart_map), indent=2, allow_nan=False),
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(to_json_safe(summary), indent=2, allow_nan=False),
        encoding="utf-8",
    )

    return build_quant_output_handoff(
        summary,
        charts_json=str(charts_path),
        execution_summary_json=str(summary_path),
        chart_ids=chart_ids,
        dropped_chart_ids=dropped_chart_ids,
        statistical_summary_excerpt=statistical_summary_excerpt,
    )
