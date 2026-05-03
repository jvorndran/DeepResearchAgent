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
    assert "BLS public data" in prompt
    assert "`bls_get_series` saves BLS CSVs" in prompt
    assert "Census public data" in prompt
    assert "`census_get_table` saves Census CSVs" in prompt
    assert "World Bank annual indicators" in prompt
    assert "`worldbank_get_indicator` saves World Bank CSVs" in prompt
    assert "may be long enough to include every required saved path" in prompt
    assert "do not try to compress `data_files` into prose" in prompt
    assert "Return the JSON handoff immediately after the final useful fetch/schema call" in prompt


def test_data_engineer_prompt_preserves_nonretryable_provider_errors():
    prompt = build_system_prompt()

    assert '"retryable": false' in prompt
    assert "preserve the compact error in `metadata.fetch_errors`" in prompt
    assert "do not retry the same provider objective" in prompt
    assert "Retry only when the payload is retryable" in prompt


def test_data_engineer_prompt_allows_direct_bls_source_checks():
    prompt = build_system_prompt()

    assert "Direct BLS labor, wage, CPI/PPI, employment, productivity source checks" in prompt
    assert "`bls_search_known_series`, `bls_get_series`" in prompt
    assert "source reconciliation" in prompt
    assert "requires no key" in prompt
    assert "10-year-or-smaller window" in prompt
    assert "do not call `save_data` afterward" in prompt


def test_data_engineer_prompt_allows_census_regional_context():
    prompt = build_system_prompt()

    assert "State/county demographics, income, population, and housing context" in prompt
    assert "`census_get_table`" in prompt
    assert "dataset `2023/acs/acs5/profile`" in prompt
    assert "geography `state` or `county`" in prompt
    assert "50 variables per query" in prompt
    assert "500 queries per IP per day" in prompt
    assert "source\": \"FRED, BLS, World Bank, Census, or SEC EDGAR" in prompt
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
    assert "do not replace the peer-country request with guessed FRED/OECD series" in prompt


def test_data_engineer_prompt_stops_after_census_regional_context_for_consumer_stress():
    prompt = build_system_prompt()

    assert "Census state income/population/housing data is the regional context" in prompt
    assert "state-level FRED income/demographic series" in prompt
    assert "unless the user explicitly asked for a named" in prompt
    assert "small national FRED macro set" in prompt
    assert "downstream merge/analysis" in prompt
    assert "regional-data caveat" in prompt
    assert "do not replace the failed Census" in prompt
    assert "broad state-level FRED unemployment" in prompt


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


def test_data_engineer_prompt_has_consumer_stress_known_ids():
    prompt = build_system_prompt()

    assert "Common consumer-stress IDs" in prompt
    assert "`PSAVERT` = personal saving rate" in prompt
    assert "`UMCSENT` = University of" in prompt
    assert "`TOTALSL` = total consumer credit owned and securitized" in prompt
    assert "`DRCLACBS` = delinquency rate on consumer loans" in prompt
    assert "`DRCCLACBS` = credit-card delinquency rate" in prompt
    assert "Do not use `TOTCI`" in prompt
    assert "Do not use `DRBLACBS` for credit-card" in prompt
    assert "consumer credit" in prompt


def test_data_engineer_prompt_stops_sp500_search_churn_after_known_fetch():
    prompt = build_system_prompt()

    assert "`SP500` = S&P 500 daily close" in prompt
    assert "FRED starts this series in 2016" in prompt
    assert "accept that limited-history proxy" in prompt
    assert "do not spend extra `fred_search`/`fred_browse` calls" in prompt


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
    assert "state geography does not accept a state filter" in prompt
    assert 'Use `state="SS"` only when narrowing county geography' in prompt


def test_data_engineer_prompt_requires_fresh_current_macro_fetches():
    prompt = build_system_prompt()

    assert "Current/latest macro freshness" in prompt
    assert "do not set `observation_end`" in prompt
    assert "unless the user explicitly gives a historical cutoff date" in prompt
    assert "backtests before earlier downturns" in prompt
    assert "`DGS2` = 2-year Treasury yield" in prompt
    assert "Do not use `TC2Y`" in prompt
