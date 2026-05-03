from agents.technical_writer.subagent import TECHNICAL_WRITER_SUBAGENT


def test_technical_writer_prompt_blocks_chatter_and_stops_after_gate():
    prompt = TECHNICAL_WRITER_SUBAGENT["system_prompt"]

    assert "Draft internally" in prompt
    assert "Call `plan_report_structure` before any other tool" in prompt
    assert "Assistant message content must be empty whenever you call tools" in prompt
    assert "If `execution_summary_for_draft` looks truncated" in prompt
    assert "Exact headline metrics from execution_summary.json" in prompt
    assert "Do not substitute older public-memory values" in prompt
    assert "Use only IDs returned in `chart_ids`" in prompt
    assert "Scenario table format" in prompt
    assert "first-column row keys must be lowercase `base`, `bull`, and `bear`" in prompt
    assert "Do not call `read_file`, `ls`, `glob`, `grep`, `execute`, or `write_file`" in prompt
    assert "After `validate_research_report_file` returns `passes_gate: true`, stop immediately" in prompt
    assert "Do not add a prose summary" in prompt
    assert "`data_sources` must cite only providers evidenced" in prompt
    assert "World Bank Indicators API" in prompt
    assert "SEC EDGAR" in prompt
    assert "Do not cite OECD, BIS, IMF" in prompt
    assert "Company Filings" in prompt
    assert "explicitly supplied scenario probabilities" in prompt
    assert "do not invent probability weights" in prompt
