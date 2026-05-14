---
name: quant-sandbox-environment
description: Linux sandbox path system and CSV data format from the data-engineer
triggers:
  - write_file
  - read_file
  - execute
  - analysis.py
  - read_csv
  - FileNotFoundError
  - path
  - /projects/
---

# Sandbox Environment Reference

## Path System

All tools use standard absolute Linux paths. There is only one path format.

| Tool | Required Format | Example |
|------|----------------|---------|
| `write_file`, `read_file`, `ls`, `glob`, `grep` | Absolute path, forward slashes | `/home/vorndranj/projects/DeepResearchAgent/backend/outputs/{job_id}/code/analysis.py` |
| `execute` | Absolute path, forward slashes | `/home/vorndranj/projects/DeepResearchAgent/backend/.venv/bin/python /home/vorndranj/projects/DeepResearchAgent/backend/outputs/{job_id}/code/analysis.py` |
| `pandas.read_csv()` inside scripts | Absolute path, forward slashes | `pd.read_csv("/home/vorndranj/projects/DeepResearchAgent/backend/data/{job_id}/AAPL_income.csv")` |

## Writing and Running analysis.py

Keep `analysis.py` compact. Target fewer than 180 lines and stay below the
hard 320-line / 28,000-character write limit. Use small helper functions and
avoid verbose repeated chart-building blocks. Before writing, mentally lint for
syntax traps: no nested f-string dict literals, no chained ternaries with
multiple `if` clauses, and no giant one-line `print(json.dumps(...))`.

For broad multi-source macro requests, the first draft should be
FRED/helper-centered: load the FRED recession-risk, unemployment,
consumer-stress, scenario, and regime inputs. When the user explicitly asks for
international peer, regional consumer, BLS verification, or company earnings-risk
comparisons and matching World Bank, Census, BLS, or SEC EDGAR CSVs are in the
handoff, load those files only for compact `execution_summary` rows. Keep
provider paths as `source_context_files` only when they are background context.
Do not build verbose provider-specific parsing branches in the initial script,
and do not leave explicitly requested provider sections as `not processed`
placeholders when source CSVs are available.

```
# Step 1 — write script:
write_file(
    file_path="/home/vorndranj/projects/DeepResearchAgent/backend/outputs/{job_id}/code/analysis.py",
    content="..."
)

# Step 2 — execute:
execute("/home/vorndranj/projects/DeepResearchAgent/backend/.venv/bin/python /home/vorndranj/projects/DeepResearchAgent/backend/outputs/{job_id}/code/analysis.py")

# Step 3 — verify output:
read_file("/home/vorndranj/projects/DeepResearchAgent/backend/outputs/{job_id}/charts.json")
```

Execute the script with the default sandbox timeout. Do not pass large timeout
values such as 120000; the sandbox maximum is 3600 seconds and timeout
negotiation is not part of the analysis.

After `execute` succeeds and this single `charts.json` read confirms the expected
chart IDs with non-empty data, stop and return the compact handoff. Do not run
additional `execute`, `read_file`, `ls`, `glob`, or shell probes to inspect
`execution_summary.json` or to second-guess valid-looking computed findings.
If a sliding-window method produces many overlapping periods, explain their
clustering in `execution_summary.json` during the script run rather than adding
post-success checks.

If `write_file` reports truncation, overwrite failure, or that the file already
exists, inspect the current file with `read_file` and patch the smallest exact
block with `edit_file`. Do not delete `analysis.py` with shell commands. If two
`edit_file` attempts fail, write a new compact script to
`/home/vorndranj/projects/DeepResearchAgent/backend/outputs/{job_id}/code/analysis_v2.py`,
execute that file, and still save `charts.json` to the original job output
directory.

## CSV Data Format from Data-Engineer

CSV files produced by `save_data` have one of two layouts:

**FRED time-series** (e.g. GDPC1, UNRATE):
```python
df = pd.read_csv("/home/vorndranj/projects/DeepResearchAgent/backend/data/{job_id}/GDPC1_real_gdp_quarterly_{job_id}.csv")
df["date"] = pd.to_datetime(df["date"])   # YYYY-MM-DD string → datetime
# Columns: date, value, series_id, title, units, frequency, ...
# Do NOT json.loads() any column — data is already flat rows
```

FRED `notes` fields can be long quoted text and may contain embedded newlines.
Saved FRED CSVs may contain long quoted `notes` fields with embedded newlines.
Do not use shell line-inspection commands such as `head`, `tail`, `cat`,
`grep`, `awk`, `sed`, or `wc` to infer the CSV shape. Trust the schema handoff
and use `pd.read_csv(..., usecols=["date", "value"])` inside the analysis
script.
Use `pd.read_csv(path, usecols=["date", "value"], parse_dates=["date"])` when
the script already has a local `path` variable for a FRED series.

Always align thresholds and display labels with the raw FRED units before
scoring signals. Initial-claims series such as `ICSA` and `IC4WSA` use raw
`Number` counts, so a value like `210750` means about 210.8 thousand claims.
Compare a "300k" threshold as `300000`, or create an explicit derived column
such as `ICSA_thousands = ICSA / 1000` and compare to `300`. If a value is
still raw counts, label it as `210,750` claims or divide first before using a
`k` suffix; never emit labels such as `210750k`.

When combining more than one FRED series, rename the generic `value` column
before merging so pandas does not create ambiguous `value_x` / `value_y`
columns:

```python
def load_fred(path, name):
    df = pd.read_csv(path, usecols=["date", "value"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df[name] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["date", name])[["date", name]]

def value_col(df):
    cols = [c for c in df.columns if c != "date"]
    if len(cols) != 1:
        raise ValueError(f"expected one value column, got {cols}")
    return cols[0]

def yoy(df, out_name, periods=12):
    col = value_col(df)
    out = df[["date", col]].copy()
    out[out_name] = out[col].pct_change(periods) * 100
    return out[["date", out_name]].dropna()

cpi = load_fred(".../CPIAUCSL_cpi_monthly_{job_id}.csv", "cpi")
unrate = load_fred(".../UNRATE_unemployment_rate_monthly_{job_id}.csv", "unrate")
merged = cpi.merge(unrate, on="date", how="outer").sort_values("date")
```

If a helper computes growth, spreads, peaks, or summaries after `load_fred`,
pass or infer the renamed column. Do not reference `df["value"]` after the
loader has renamed that column.

When FRED series have different native frequencies, do not merge resampled
month-end dates directly with month-start monthly series. Normalize every frame
to the same period key first:

```python
daily = load_fred(".../T10Y3M_treasury_spread_{job_id}.csv", "t10y3m")
daily["month"] = daily["date"].dt.to_period("M")
t10y3m_monthly = daily.groupby("month", as_index=False)["t10y3m"].mean()

unrate = load_fred(".../UNRATE_unemployment_rate_{job_id}.csv", "unrate")
unrate["month"] = unrate["date"].dt.to_period("M")

merged = t10y3m_monthly.merge(unrate[["month", "unrate"]], on="month", how="inner")
merged["date"] = merged["month"].dt.to_timestamp("M")
if merged.empty:
    raise ValueError("mixed-frequency FRED merge produced no rows; check period-key alignment")
```

For any task that combines daily FRED rates/yields with monthly or quarterly
macro series, use this period-key pattern in the first version of
`analysis.py`. Do not first try a `DatetimeIndex.join(...)`, `merge(...,
on="date")`, or broad `dropna()` alignment; those commonly create empty frames
because month-start FRED observations do not match month-end resample
timestamps.

Use pandas frequency aliases according to the operation: `.resample("ME")` and
`.resample("QE")` are valid for month-end and quarter-end resampling, but
Period keys use `.dt.to_period("M")` and `.dt.to_period("Q")`. Do not pass
`"ME"` or `"QE"` to `to_period(...)`.

Before writing `charts.json` or `execution_summary.json`, prefer the shared
artifact helper instead of hand-rolled serialization:

```python
from agents.quant_macro_stats import save_quant_outputs

handoff = save_quant_outputs(OUTPUT_DIR, charts, execution_summary)
print(json.dumps(handoff))
```

This avoids repeated retries from `Timestamp`, `Period`, `NaN`, numpy scalar
serialization failures, and stale `chart_ids` inside the final handoff. Never
import `agents.quant_utils`; that module does not exist.

**SEC EDGAR company-facts data**:
```python
df = pd.read_csv("/home/vorndranj/projects/DeepResearchAgent/backend/data/{job_id}/sec_edgar_company_facts_AAPL_{job_id}.csv")
# Prefer summarize_sec_company_facts(path) from agents.quant_macro_stats.
# If manually loading compact chart rows, sort by fiscal_year ascending first.
df = df.sort_values("fiscal_year").reset_index(drop=True)
```

FMP remains disabled and unavailable. Do not request paid/keyed provider data or
invent FMP-backed quote, market-data, estimate, or financial-statement fields.

## Common Pitfall: NaN in Numeric Columns

Provider CSVs may have empty numeric cells. Cast safely:
```python
df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
df = df.dropna(subset=["revenue"])
```
