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

## CSV Data Format from Data-Engineer

CSV files produced by `save_data` have one of two layouts:

**FRED time-series** (e.g. GDPC1, UNRATE):
```python
df = pd.read_csv("/home/vorndranj/projects/DeepResearchAgent/backend/data/{job_id}/GDPC1_real_gdp_quarterly_{job_id}.csv")
df["date"] = pd.to_datetime(df["date"])   # YYYY-MM-DD string → datetime
# Columns: date, value, series_id, title, units, frequency, ...
# Do NOT json.loads() any column — data is already flat rows
```

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
