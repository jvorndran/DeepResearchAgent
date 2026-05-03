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
    assert "USREC" in skill
    assert "quant-developer should not fetch recession dates itself" in skill


def test_quant_skill_exposes_regime_helper_signature_without_source_reading():
    skill_path = (
        Path(__file__).resolve().parents[1]
        / "skills"
        / "quant-developer"
        / "SKILL.md"
    )
    skill = skill_path.read_text()

    assert "classify_recession_regime(scored_frame" in skill
    assert 'recession_col="USREC"' in skill
    assert "weak_threshold" in skill
    assert "favorable_when" in skill
    assert "Do not read" in skill
    assert "to rediscover this signature before writing" in skill


def test_quant_skill_keeps_broad_multi_source_first_draft_compact():
    skill_path = (
        Path(__file__).resolve().parents[1]
        / "skills"
        / "quant-developer"
        / "SKILL.md"
    )
    skill = skill_path.read_text()

    assert "For broad macro + equity + regional + international prompts" in skill
    assert "FRED/helper-centered" in skill
    assert "international peer, regional consumer, BLS" in skill
    assert "compact summary rows in `execution_summary`" in skill
    assert "Never leave explicitly requested provider sections as `not processed`" in skill
    assert "placeholders when source CSVs are available" in skill
    assert 'execution_summary["source_context_files"]' in skill
    assert "first `DATA_FILES` manifest may be a subset" in skill
    assert "Copy exact CSV path strings only for the FRED/local series" in skill
    assert "one `load_series(key)` helper" in skill
    assert "historical replay as applicable" in skill
    assert "World Bank, Census, BLS, or SEC EDGAR CSVs" in skill
