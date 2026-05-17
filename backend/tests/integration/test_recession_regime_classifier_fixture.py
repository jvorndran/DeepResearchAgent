import json

import pandas as pd

from agents.quant_macro_stats import classify_recession_regime


def test_recession_regime_classifier_fixture_execution_summary_schema(tmp_path):
    fixture = pd.DataFrame(
        {
            "date": pd.date_range("2023-01-31", periods=6, freq="ME"),
            "rates": [0.4, 0.3, 0.1, -0.1, -0.3, -0.4],
            "labor": [0.6, 0.5, 0.4, 0.1, -0.1, -0.2],
            "inflation": [0.2, 0.1, 0.0, -0.1, -0.2, -0.1],
            "credit": [0.4, 0.3, 0.1, 0.0, -0.1, -0.2],
            "output": [0.5, 0.4, 0.3, 0.1, -0.1, 0.0],
            "usrec": [0, 0, 0, 0, 0, 0],
        }
    )

    regime = classify_recession_regime(fixture, recession_col="usrec")
    execution_summary = {
        **regime,
        "charts_json": str(tmp_path / "charts.json"),
        "chart_ids": ["regime_evidence"],
        "statistical_summary": "Fixture-driven local regime classifier output.",
    }
    summary_path = tmp_path / "execution_summary.json"
    summary_path.write_text(json.dumps(execution_summary), encoding="utf-8")

    loaded = json.loads(summary_path.read_text(encoding="utf-8"))

    assert loaded["current_regime_row"]["regime"] in {
        "expansion",
        "slowdown",
        "recession",
        "recovery",
        "reacceleration",
    }
    assert loaded["regime_evidence_rows"]
    assert isinstance(loaded["regime_analog_rows"], list)
    assert loaded["missing_indicator_rows"] == []
    assert loaded["regime_design"]["method"] == "recession_regime_classifier"
    assert "evidence_table" not in loaded
    assert "historical_analogs" not in loaded
    assert "false_positive_caveat" not in loaded
    assert loaded["methods_used"] == ["recession_regime_classifier"]
