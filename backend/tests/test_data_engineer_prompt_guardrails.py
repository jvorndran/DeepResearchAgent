from agents.data_engineer.prompts import (
    DATA_ENGINEER_CORE_PROMPT,
    PROVIDER_PROMPT_SECTIONS,
    PROVIDER_SKILL_FILES,
    build_system_prompt,
)


def test_data_engineer_build_system_prompt_selects_only_fred_section():
    prompt = build_system_prompt(["fred"])

    assert "FRED PROVIDER RULES" in prompt
    assert "Common consumer-stress IDs" in prompt
    assert "BLS PROVIDER RULES" not in prompt
    assert "BEA PROVIDER RULES" not in prompt
    assert "CENSUS PROVIDER RULES" not in prompt
    assert "WORLD BANK PROVIDER RULES" not in prompt
    assert "SEC PROVIDER RULES" not in prompt


def test_data_engineer_build_system_prompt_selects_only_sec_section():
    prompt = build_system_prompt(["sec"])

    assert "SEC PROVIDER RULES" in prompt
    assert "SEC COMPANY FACTS" in prompt
    assert "FRED PROVIDER RULES" not in prompt
    assert "Current/latest macro freshness" not in prompt
    assert "Common consumer-stress IDs" not in prompt


def test_data_engineer_build_system_prompt_avoids_inactive_provider_names():
    fred_prompt = build_system_prompt(["fred"])
    sec_prompt = build_system_prompt(["sec"])

    assert "SEC EDGAR" not in fred_prompt
    assert "BLS DIRECT SOURCE CHECKS" not in fred_prompt
    assert "BEA NATIONAL ACCOUNTS" not in fred_prompt
    assert "WORLD BANK CROSS-COUNTRY MACRO" not in fred_prompt

    assert "FRED" not in sec_prompt
    assert "BLS" not in sec_prompt
    assert "BEA" not in sec_prompt
    assert "World Bank" not in sec_prompt
    assert "Census" not in sec_prompt


def test_data_engineer_build_system_prompt_broad_fallback_includes_all_provider_sections():
    prompt = build_system_prompt()

    assert "FRED PROVIDER RULES" in prompt
    assert "BLS PROVIDER RULES" in prompt
    assert "BEA PROVIDER RULES" in prompt
    assert "CENSUS PROVIDER RULES" in prompt
    assert "WORLD BANK PROVIDER RULES" in prompt
    assert "SEC PROVIDER RULES" in prompt


def test_data_engineer_provider_details_are_not_in_core_prompt():
    assert "Common consumer-stress IDs" not in DATA_ENGINEER_CORE_PROMPT
    assert "BLS DIRECT SOURCE CHECKS" not in DATA_ENGINEER_CORE_PROMPT
    assert "BEA NATIONAL ACCOUNTS" not in DATA_ENGINEER_CORE_PROMPT
    assert "CENSUS REGIONAL CONTEXT" not in DATA_ENGINEER_CORE_PROMPT
    assert "WORLD BANK CROSS-COUNTRY MACRO" not in DATA_ENGINEER_CORE_PROMPT
    assert "SEC COMPANY FACTS" not in DATA_ENGINEER_CORE_PROMPT

    assert "Common consumer-stress IDs" in PROVIDER_PROMPT_SECTIONS["fred"]
    assert "BLS DIRECT SOURCE CHECKS" in PROVIDER_PROMPT_SECTIONS["bls"]
    assert "BEA NATIONAL ACCOUNTS" in PROVIDER_PROMPT_SECTIONS["bea"]
    assert "CENSUS REGIONAL CONTEXT" in PROVIDER_PROMPT_SECTIONS["census"]
    assert "WORLD BANK CROSS-COUNTRY MACRO" in PROVIDER_PROMPT_SECTIONS["worldbank"]
    assert "SEC COMPANY FACTS" in PROVIDER_PROMPT_SECTIONS["sec"]


def test_data_engineer_core_prompt_stays_compact_and_routes_provider_details():
    assert len(DATA_ENGINEER_CORE_PROMPT) < 3_300
    assert "Provider rules are appended at runtime" in DATA_ENGINEER_CORE_PROMPT
    assert "FMP remains disabled and unavailable" in DATA_ENGINEER_CORE_PROMPT
    assert "SEC EDGAR" not in DATA_ENGINEER_CORE_PROMPT
    assert "FRED, BLS, World Bank, Census" not in DATA_ENGINEER_CORE_PROMPT
    for provider_tool in (
        "fred_get_series",
        "bls_get_series",
        "bea_get_nipa_table",
        "census_get_table",
        "worldbank_get_indicator",
        "sec_fetch_company_facts",
    ):
        assert provider_tool not in DATA_ENGINEER_CORE_PROMPT


def test_data_engineer_provider_sections_are_loaded_from_skill_files():
    assert PROVIDER_SKILL_FILES == {
        "fred": "fred-macro-fetch.md",
        "bls": "bls-public-data.md",
        "bea": "bea-national-accounts.md",
        "census": "census-regional-context.md",
        "worldbank": "worldbank-indicators.md",
        "sec": "sec-edgar-company-facts.md",
    }
    for provider, skill_file in PROVIDER_SKILL_FILES.items():
        assert skill_file.endswith(".md")
        assert PROVIDER_PROMPT_SECTIONS[provider].startswith(
            f"# {'WORLD BANK' if provider == 'worldbank' else ('SEC' if provider == 'sec' else provider.upper())} PROVIDER RULES"
        )


def test_data_engineer_fmp_skill_files_are_disabled():
    from pathlib import Path

    skills_dir = Path(__file__).resolve().parents[1] / "skills" / "data-engineer"
    for filename in ("fmp-data-fetch.md", "fmp-api-errors.md"):
        text = (skills_dir / filename).read_text(encoding="utf-8")
        assert "FMP remains disabled and unavailable" in text
        assert "Do not call FMP tools" in text or "Do not recover FMP errors" in text
        assert "enable_toolset" not in text
        assert "getIncomeStatement" not in text


def test_data_engineer_prompt_blocks_chatter_and_manual_csv_cleanup():
    prompt = build_system_prompt()

    assert "Assistant message content must be empty whenever you call tools" in prompt
    assert "Never call" in prompt
    assert "`execute`" in prompt
    assert "NO MANUAL CSV CLEANUP" in prompt
    assert "`fred_get_series` auto-saves usable CSVs" in prompt
    assert "do not call `save_data`" in prompt
    assert "make job-folder copies" in prompt
    assert "the returned auto-save" in prompt
    assert "path is canonical" in prompt
    assert "`data_files`" in prompt
    assert "machine-readable" in prompt
    assert "rediscover paths" in prompt
    assert "with `glob`" in prompt
    assert "Do not include sample rows" in prompt
    assert "markdown fences" in prompt
    assert "After `extract_schema`, compress" in prompt
    assert "tool result into `schema_summary` yourself" in prompt
    assert "paste the `extract_schema`" in prompt
    assert "No ```json fences" in prompt
    assert "after the JSON object" in prompt
    assert "NO IMPLIED EXPORT REQUESTS" in prompt
    assert "not user-requested" in prompt
    assert "data-export filenames" in prompt
    assert "research query explicitly asks for them" in prompt
    assert "BLS" in prompt
    assert "public data" in prompt
    assert "BEA National Accounts" in prompt
    assert "`bea_get_nipa_table` saves BEA CSVs" in prompt
    assert "`bls_get_series` saves BLS CSVs" in prompt
    assert "Census public data" in prompt
    assert "`census_get_table`" in prompt
    assert "saves" in prompt
    assert "Census CSVs" in prompt
    assert "World Bank annual indicators" in prompt
    assert "`worldbank_get_indicator` saves World Bank CSVs" in prompt
    assert "long enough to include every required" in prompt
    assert "try to compress `data_files` into prose" in prompt
    assert "JSON handoff immediately after the final useful fetch/schema call" in prompt


def test_data_engineer_prompt_preserves_nonretryable_provider_errors():
    prompt = build_system_prompt()

    assert '"retryable": false' in prompt
    assert "preserve the compact error" in prompt
    assert "`metadata.fetch_errors`" in prompt
    assert "do not retry the same provider objective" in prompt
    assert "Retry only when the payload is retryable" in prompt


def test_data_engineer_prompt_allows_direct_bls_source_checks():
    prompt = build_system_prompt()

    assert "Direct BLS labor, wage, CPI/PPI, employment, productivity source checks" in prompt
    assert "`bls_search_known_series`, `bls_get_series`" in prompt
    assert "reconciliation against FRED" in prompt
    assert "requires no key" in prompt
    assert "10-year-or-smaller direct-source check" in prompt
    assert "normalizes partial or over-wide no-key year windows" in prompt
    assert "versus applied window" in prompt
    assert "Do not retry the same BLS objective" in prompt
    assert "do not call `save_data` afterward" in prompt


def test_data_engineer_prompt_allows_bea_national_accounts():
    prompt = build_system_prompt()

    assert "First-party national-accounts evidence" in prompt
    assert "`bea_get_nipa_table`" in prompt
    assert "`T10105` current-dollar" in prompt
    assert "`T20305` PCE" in prompt
    assert "`T61600D` corporate" in prompt
    assert "Supported frequencies are `Q` and `A`" in prompt
    assert "`BEA_API_KEY` or `BEA_USER_ID`" in prompt
    assert "`metadata.fetch_errors`" in prompt
    assert "Preserve BEA source descriptors" in prompt
    assert "`release_cadence`" in prompt
    assert "`revision_policy`" in prompt


def test_data_engineer_prompt_includes_unemployment_forecast_fetch_set():
    prompt = build_system_prompt(["fred"])

    assert "Common unemployment-forecast IDs" in prompt
    for series_id in ("UNRATE", "PAYEMS", "ICSA", "U6RATE", "DGS10", "FEDFUNDS", "NROU"):
        assert f"`{series_id}`" in prompt
    assert "forecast-band" in prompt
    assert "historical miss" in prompt


def test_data_engineer_prompt_allows_census_regional_context():
    prompt = build_system_prompt()

    assert "State/county demographics, income, population, and housing context" in prompt
    assert "`census_get_table`" in prompt
    assert "dataset `2023/acs/acs5/profile`" in prompt
    assert "geography `state`" in prompt
    assert "`county`" in prompt
    assert "50 variables per query" in prompt
    assert "500 queries per IP" in prompt
    assert "per day" in prompt
    assert "Use metadata source" in prompt
    assert "providers evidenced by active" in prompt
    assert "sections and fetched files" in prompt
    assert "never" in prompt
    assert "name inactive providers" in prompt
    assert "error_type:provider_payload_unusable" in prompt
    assert "terminal for the current data objective" in prompt
    assert "do not retry with a narrower variable set" in prompt
    assert "do not switch to paid providers" in prompt


def test_data_engineer_prompt_allows_worldbank_cross_country_macro():
    prompt = build_system_prompt()

    assert "Cross-country annual inflation and GDP growth" in prompt
    assert "`worldbank_get_indicator`" in prompt
    assert "`USA`, `CAN`, `DEU`, `JPN`" in prompt
    assert "`inflation`/`FP.CPI.TOTL.ZG`" in prompt
    assert "`gdp_growth`/`NY.GDP.MKTP.KD.ZG`" in prompt
    assert "World Bank data is" in prompt
    assert "annual" in prompt
    assert "align frequencies" in prompt
    assert "do not switch to paid providers" in prompt
    assert "peer-country request" in prompt
    assert "guessed FRED/OECD series" in prompt


def test_data_engineer_prompt_stops_after_census_regional_context_for_consumer_stress():
    prompt = build_system_prompt()

    assert "Census state income/population/housing data is the regional context" in prompt
    assert "state-level FRED income/demographic series" in prompt
    assert "unless the user explicitly asked for a named" in prompt
    assert "small national FRED macro set" in prompt
    assert "downstream merge/analysis" in prompt
    assert "regional-data caveat" in prompt
    assert "failed Census context" in prompt
    assert "broad state-level FRED unemployment" in prompt


def test_data_engineer_prompt_has_labor_series_identity_guardrail():
    prompt = build_system_prompt()

    assert "LNS14000060" in prompt
    assert "Never label `LNS14000003`" in prompt
    assert "title contradicts the concept" in prompt


def test_data_engineer_prompt_requires_real_wage_source_fidelity():
    prompt = build_system_prompt()

    assert "Real wage/earnings requests" in prompt
    assert "Do not treat nominal earnings" in prompt
    assert "such as `AHETPI`" in prompt
    assert "`CPIAUCSL`" in prompt
    assert "quant-developer must" in prompt


def test_data_engineer_prompt_has_consumer_stress_known_ids():
    prompt = build_system_prompt()

    assert "Common consumer-stress IDs" in prompt
    assert "`PSAVERT` = personal saving rate" in prompt
    assert "`UMCSENT` = University of" in prompt
    assert "`TOTALSL` = total consumer credit owned and securitized" in prompt
    assert "`DRCLACBS` = delinquency rate on consumer loans" in prompt
    assert "`DRCCLACBS`" in prompt
    assert "credit-card" in prompt
    assert "delinquency rate" in prompt
    assert "`DPCERA3M086SBEA`" in prompt
    assert "`PCEC96` = real personal consumption expenditures" in prompt
    assert "`PCE` = nominal consumption" in prompt
    assert "Do not" in prompt
    assert "`TOTCI`" in prompt
    assert "`DRBLACBS`" in prompt
    assert "credit-card" in prompt
    assert "consumer credit" in prompt


def test_data_engineer_prompt_stops_sp500_search_churn_after_known_fetch():
    prompt = build_system_prompt()

    assert "`SP500` = S&P 500 daily close" in prompt
    assert "FRED starts `SP500` in 2016" in prompt
    assert "accept that" in prompt
    assert "limited-history proxy" in prompt
    assert "do not spend extra" in prompt
    assert "`fred_search`/`fred_browse` calls" in prompt


def test_data_engineer_prompt_has_large_state_labor_known_ids():
    prompt = build_system_prompt()

    assert "Common large-state labor IDs" in prompt
    for series_id in ("CAUR", "TXUR", "FLUR", "NYUR", "ILUR"):
        assert series_id in prompt
    for series_id in ("CANA", "TXNA", "FLNA", "NYNA", "ILNA"):
        assert series_id in prompt
    assert "Do not call nonexistent IDs" in prompt
    assert "CANURN" in prompt
    assert "CES0600000001" in prompt


def test_data_engineer_prompt_avoids_invalid_census_state_filter():
    prompt = build_system_prompt()

    assert 'geography="state"` once with no `state` filter' in prompt
    assert "State geography" in prompt
    assert "does not accept a state filter" in prompt
    assert 'Use `state="SS"` only when narrowing' in prompt
    assert "county geography" in prompt


def test_data_engineer_prompt_requires_fresh_current_macro_fetches():
    prompt = build_system_prompt()

    assert "Current/latest macro freshness" in prompt
    assert "do not set `observation_end`" in prompt
    assert "unless the user explicitly gives" in prompt
    assert "historical cutoff date" in prompt
    assert "backtests before earlier downturns" in prompt
    assert "`DGS2` = 2-year Treasury yield" in prompt
    assert "Do not use `TC2Y`" in prompt
