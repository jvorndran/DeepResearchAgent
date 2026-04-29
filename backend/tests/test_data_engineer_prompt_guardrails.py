from agents.data_engineer.prompts import build_system_prompt


def test_data_engineer_prompt_blocks_chatter_and_manual_csv_cleanup():
    prompt = build_system_prompt()

    assert "Assistant message content must be empty whenever you call tools" in prompt
    assert "Never call `execute`" in prompt
    assert "NO MANUAL CSV CLEANUP" in prompt
    assert "`fred_get_series` auto-saves usable CSVs" in prompt
    assert "do not call `save_data`" in prompt
    assert "Do not make job-folder copies" in prompt
    assert "the returned auto-save path is canonical" in prompt
    assert "data_files` as a machine-readable map" in prompt
    assert "rediscover paths with `glob`" in prompt
    assert "Do not include sample rows" in prompt
    assert "markdown fences" in prompt
    assert "After `extract_schema`, compress the tool result into `schema_summary` yourself" in prompt
    assert "Never paste the `extract_schema` tool result" in prompt
    assert "No ```json fences and no text before or after the JSON object" in prompt
    assert "NO IMPLIED EXPORT REQUESTS" in prompt
    assert "not user-requested data-export filenames" in prompt
    assert "original research query explicitly asks for them" in prompt


def test_data_engineer_prompt_has_labor_series_identity_guardrail():
    prompt = build_system_prompt()

    assert "LNS14000060" in prompt
    assert "Never label `LNS14000003`" in prompt
    assert "title contradicts the concept" in prompt


def test_data_engineer_prompt_requires_real_wage_source_fidelity():
    prompt = build_system_prompt()

    assert "Real wage/earnings requests" in prompt
    assert "Do not treat nominal earnings series such as `AHETPI`" in prompt
    assert "`CPIAUCSL`" in prompt
    assert "quant-developer must" in prompt
