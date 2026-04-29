---
name: sandbox-environment
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

Keep `analysis.py` compact. Target fewer than 220 lines, use small helper functions,
and avoid verbose repeated chart-building blocks. Before writing, mentally lint for
syntax traps: no nested f-string dict literals, no chained ternaries with multiple
`if` clauses, and no giant one-line `print(json.dumps(...))`.

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
Do not use shell line-inspection commands such as `head`, `tail`, `cat`,
`grep`, `awk`, `sed`, or `wc` to infer the CSV shape. Trust the schema handoff
and use `pd.read_csv(..., usecols=["date", "value"])` inside the analysis
script.

Always align thresholds with the raw FRED units before scoring signals. If a
series uses raw `Number` counts, such as IC4WSA initial claims around `210750`,
compare a "300k" threshold as `300000` or convert both the series value and the
threshold to thousands before comparing. Do not compare raw counts to abbreviated
thresholds such as `> 300`.

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

Before writing `charts.json` or `execution_summary.json`, sanitize nested chart
objects so the JSON contains only plain Python strings, numbers, booleans,
lists, dicts, and `None`:

```python
def clean_json(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, pd.Period):
        return str(value)
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if pd.isna(value):
        return None
    return str(value)
```

Use `json.dump(clean_json(charts), f, indent=2)` and the same pattern for
`execution_summary.json`. This avoids repeated retries from `Timestamp`,
`Period`, `NaN`, or numpy scalar serialization failures inside chart data,
reference lines, reference areas, or summary metrics.

**FMP financial statement data** (e.g. income statement):
```python
df = pd.read_csv("/home/vorndranj/projects/DeepResearchAgent/backend/data/{job_id}/AAPL_income_statement_{job_id}.csv")
# Columns vary: date, revenue, netIncome, operatingIncome, eps, ...
# Numeric columns may contain strings like "1234567000" — cast with pd.to_numeric()
```

## Common Pitfall: NaN in Numeric Columns

FMP data occasionally has empty cells. Cast safely:
```python
df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
df = df.dropna(subset=["revenue"])
```
