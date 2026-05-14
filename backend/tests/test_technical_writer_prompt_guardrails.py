from pathlib import Path

from agents.technical_writer.constants import TECHNICAL_WRITER_SKILLS_DIR
from agents.technical_writer.subagent import TECHNICAL_WRITER_SUBAGENT


def _writer_skill_text(*names: str) -> str:
    text = "\n".join(
        (TECHNICAL_WRITER_SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
        for name in names
    )
    return " ".join(text.split())


def test_technical_writer_prompt_is_compact_skill_router():
    prompt = TECHNICAL_WRITER_SUBAGENT["system_prompt"]

    assert len(prompt) < 3_500
    assert "Call `plan_report_structure` before any other tool" in prompt
    assert "Assistant message content must be empty whenever you call tools" in prompt
    assert "After `validate_research_report_file` returns `passes_gate: true`, stop immediately" in prompt
    assert "Do not add a prose summary" in prompt
    assert "report-writing-contract" in prompt
    assert "macro-report-writing" in prompt
    assert "equity-report-writing" in prompt

    migrated_details = [
        "Exact headline metrics from execution_summary.json",
        "Do not substitute older public-memory values",
        "Use only IDs returned in `chart_ids`",
        "Scenario table format",
        "first-column row keys must be lowercase `base`, `bull`, and `bear`",
        "World Bank Indicators API",
        "Do not cite OECD, BIS, IMF",
        "Company Filings",
        "explicitly supplied scenario probabilities",
        "do not invent probability weights",
        "Follow `general_rules`",
        "Copy `charts_json_path` and `original_query`",
        "End the markdown body with `## Research Query`",
        "If `write_research_report` reports an argument error",
        "If `passes_gate` is false, revise markdown",
    ]
    for detail in migrated_details:
        assert detail not in prompt


def test_technical_writer_skills_are_native_deepagents_shape():
    expected = {
        "report-writing-contract",
        "macro-report-writing",
        "equity-report-writing",
    }

    actual = {
        path.parent.name
        for path in Path(TECHNICAL_WRITER_SKILLS_DIR).glob("*/SKILL.md")
    }

    assert actual == expected
    for name in expected:
        skill = (TECHNICAL_WRITER_SKILLS_DIR / name / "SKILL.md").read_text(
            encoding="utf-8"
        )
        assert f"name: {name}" in skill
        assert "description:" in skill


def test_migrated_technical_writer_details_live_in_skills_not_prompt():
    prompt = TECHNICAL_WRITER_SUBAGENT["system_prompt"]
    skill_text = _writer_skill_text(
        "report-writing-contract",
        "macro-report-writing",
        "equity-report-writing",
    )

    for detail in [
        "Draft internally",
        "Exact headline metrics from execution_summary.json",
        "Do not substitute older public-memory values",
        "If `execution_summary_for_draft` looks truncated",
        "Use only IDs returned in `chart_ids`",
        "chart_facts_for_draft",
        "World Bank Indicators API",
        "Do not cite OECD, BIS, IMF",
        "generic \"Company Filings\"",
        "explicitly supplied scenario probabilities",
        "do not invent probability weights",
        "Follow `general_rules`",
        "Copy `charts_json_path` and `original_query`",
        "End the markdown body with `## Research Query`",
        "If `write_research_report` reports an argument error",
        "If `passes_gate` is false, revise markdown",
        "first-column row keys must be lowercase `base`, `bull`, and `bear`",
        "`Scenario`, `Assumptions`, `Indicator Triggers`, `Confidence`, `Uncertainty Notes`",
    ]:
        assert detail in skill_text
        assert detail not in prompt
