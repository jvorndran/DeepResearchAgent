import re
from pathlib import Path


def test_orchestrator_skills_are_native_deepagents_shape():
    skills_dir = Path(__file__).resolve().parents[1] / "skills" / "orchestrator"
    expected = {
        "broad-investment-committee-workflow",
        "company-fundamental-research-workflow",
        "data-to-quant-handoff",
        "equity-earnings-workflow",
        "labor-real-wage-workflow",
        "macro-correlation-workflow",
        "paths-artifacts-and-sources",
        "quality-analyst-handoff",
        "qa-rejection-recovery",
        "regional-consumer-stress-workflow",
        "sector-comparison-workflow",
        "technical-writer-handoff",
    }

    actual = {path.parent.name for path in skills_dir.glob("*/SKILL.md")}

    assert actual == expected
    for name in expected:
        skill = (skills_dir / name / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = skill.split("---", 2)[1]
        keys = {
            line.split(":", 1)[0].strip()
            for line in frontmatter.splitlines()
            if line.strip()
        }
        assert keys == {"name", "description"}
        assert f"name: {name}" in frontmatter
        assert "description:" in skill
        assert "triggers:" not in frontmatter


def test_orchestrator_skill_descriptions_preserve_routing_triggers():
    skills_dir = Path(__file__).resolve().parents[1] / "skills" / "orchestrator"
    descriptions = {
        path.parent.name: path.read_text(encoding="utf-8").split("---", 2)[1]
        for path in skills_dir.glob("*/SKILL.md")
    }

    assert "recession windows, regimes, correlations" in descriptions[
        "macro-correlation-workflow"
    ]
    assert "real average hourly earnings" in descriptions["labor-real-wage-workflow"]
    assert "state-level US consumer-stress" in descriptions[
        "regional-consumer-stress-workflow"
    ]
    assert "international peers" in descriptions["broad-investment-committee-workflow"]
    assert "public-company or ticker fundamental research" in descriptions[
        "company-fundamental-research-workflow"
    ]
    assert "AAPL vs MSFT" in descriptions["sector-comparison-workflow"]
    assert "before every quant-developer delegation" in descriptions["data-to-quant-handoff"]


def test_macro_correlation_skill_respects_fred_auto_save_contract():
    skill_path = (
        Path(__file__).resolve().parents[1]
        / "skills"
        / "orchestrator"
        / "macro-correlation-workflow"
        / "SKILL.md"
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
        / "quant-macro-helper-workflows"
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
        / "quant-script-workflow"
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
    assert "6-8" in skill
    assert "explicit chart-heavy/dashboard prompts" in skill


def test_orchestrator_skills_do_not_advance_empty_chart_heavy_handoffs():
    skills_dir = Path(__file__).resolve().parents[1] / "skills" / "orchestrator"
    writer_skill = (
        skills_dir / "technical-writer-handoff" / "SKILL.md"
    ).read_text(encoding="utf-8")
    broad_skill = (
        skills_dir / "broad-investment-committee-workflow" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "generally expect 6-8 distinct chart IDs" in writer_skill
    assert "Do not call technical-writer on an empty chart map" in writer_skill
    assert "do not call technical-writer on those artifacts" in writer_skill
    assert "unless a later validated quant handoff is present" in writer_skill
    assert "6-8 distinct renderable charts" in broad_skill


def test_agent_facing_instructions_do_not_contain_concrete_job_path_examples():
    backend_root = Path(__file__).resolve().parents[1]
    instruction_files = [
        backend_root / "AGENTS.md",
        *backend_root.glob("agents/**/prompts.py"),
        *backend_root.glob("skills/**/*.md"),
    ]
    concrete_job_path = re.compile(
        r"\bjob_[0-9a-fA-F]{8}\b|outputs/job_[A-Za-z0-9_.-]+"
    )

    offenders = [
        str(path.relative_to(backend_root))
        for path in instruction_files
        if concrete_job_path.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
