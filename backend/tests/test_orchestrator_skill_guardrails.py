from pathlib import Path


def test_macro_correlation_skill_respects_fred_auto_save_contract():
    skill_path = (
        Path(__file__).resolve().parents[1]
        / "skills"
        / "orchestrator"
        / "macro-correlation-workflow.md"
    )
    skill = skill_path.read_text()

    assert "status:auto_saved" in skill
    assert "do not call `save_data`" in skill
    assert "`fred_get_series` → `save_data`" not in skill
