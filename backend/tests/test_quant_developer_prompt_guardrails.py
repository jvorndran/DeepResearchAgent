from agents.quantitative_developer import QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_constrains_script_size_and_rewrite_recovery():
    assert "SCRIPT BUDGET & RECOVERY" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "target under 220 lines" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "no nested f-string dict literals" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "do not delete/rewrite with shell" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "analysis_v2.py" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Assistant message content must be empty whenever you call tools" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Once `execute` succeeds and one validation signal confirms" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "read execution_summary.json" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "stdout already reports valid `charts_json`, `execution_summary_json`, and `chart_ids`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "A successful script stdout that includes `charts_json`, `execution_summary_json`, and `chart_ids` is already a validation signal" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "A surprising but valid-looking computed result" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "do not launch post-success shell probes" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "execution_summary.json" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Never copy the full `execute` stdout into your final response" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "statistical_summary_excerpt" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do not edit a successful script merely to make a conclusion field more positive" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "supportive but not consistent/guaranteed" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do not wrap it in markdown fences" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do not append narrative findings after the JSON" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Supported report chart types" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert 'Do not create `"radar"`' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Every pie chart MUST include" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert '"value": <number>' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do not use `size` for pie charts" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do NOT emit legacy top-level fields such as `chartType`, `xKey`, `yKeys`" in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_blocks_shell_csv_probe_loops():
    assert "Your first tool call MUST be `write_file`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do not call `ls`, `glob`, `read_file`, `execute`, or any other inspection tool before the initial script is written" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Trust the data-engineer schema/file-path handoff" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do not use `execute` for shell-based CSV inspection" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "head" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "tail" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "one-off pandas snippets" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Put all data loading, cleaning, latest-date checks, and validation inside `analysis.py`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Saved FRED CSVs may contain long quoted `notes` fields with embedded newlines" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert 'pd.read_csv(path, usecols=["date", "value"], parse_dates=["date"])' in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_aligns_fred_thresholds_to_raw_units():
    assert "FRED unit/threshold safety" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "IC4WSA initial claims" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "300000" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do not compare raw counts to abbreviated thresholds" in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_covers_pandas_scalar_date_safety():
    assert "Pandas scalar date safety" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "numpy.datetime64" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "pd.Timestamp(value).date()" in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_requires_period_key_for_mixed_frequency_fred_merges():
    assert "FRED frequency alignment" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "daily FRED series such as Treasury yields" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert 'date.dt.to_period("M")' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert 'quarter = date.dt.to_period("Q")' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "merge on `quarter`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "quarter-start GDP dates directly against quarter-end resample timestamps" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do not merge month-end dates from resampling directly against month-start FRED dates" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Mixed-frequency first draft requirement" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "the initial `analysis.py` must use period-key merges from the start" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "mixed-frequency FRED merge produced no rows" in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_covers_derived_column_subset_ordering():
    assert "Derived-column ordering" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "before taking filtered `.copy()` subsets" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "rebuild the subset or explicitly assign the column" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "trace which dataframe actually owns the missing column" in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_covers_fred_helper_and_json_serialization_safety():
    assert "FRED helper consistency" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do not write helpers that still reference `df[\"value\"]`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "JSON serialization safety" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "recursively convert pandas/numpy values" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "referenceLines" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "referenceAreas" in QUANT_DEVELOPER_SYSTEM_PROMPT
