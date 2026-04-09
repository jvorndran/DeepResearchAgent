---
name: sandbox-environment
description: Windows sandbox path systems (virtual vs Windows paths) and CSV data format from the data-engineer
triggers:
  - write_file
  - read_file
  - execute
  - virtual path
  - Windows path
  - analysis.py
  - read_csv
  - FileNotFoundError
  - path
  - C:\
  - /projects/
---

# Sandbox Environment Reference

## Two Path Systems

The sandbox has TWO path systems. Using the wrong one for the wrong tool causes immediate errors.

| Tool | Required Format | Example |
|------|----------------|---------|
| `write_file`, `read_file`, `ls`, `glob`, `grep` | **Virtual path** — strip drive letter, forward slashes | `/projects/DeepResearchAgent/backend/outputs/{job_id}/code/analysis.py` |
| `execute` | **Windows absolute path** | `C:\projects\DeepResearchAgent\backend\.venv\Scripts\python.exe C:\...\analysis.py` |
| `pandas.read_csv()` inside scripts | **Windows absolute path** | `pd.read_csv(r"C:\projects\DeepResearchAgent\backend\data\{job_id}\AAPL_income.csv")` |

**Conversion rule**: Strip the drive letter and colon from a Windows path.
`C:\projects\DeepResearchAgent\backend\outputs\{job_id}` → `/projects/DeepResearchAgent/backend/outputs/{job_id}`

**Data files from data-engineer** arrive as Windows paths (e.g. `C:\...\data\job123\AAPL_income.csv`).
- To pass to `read_file` → strip `C:` → use `/projects/...`
- To use inside `analysis.py` with `pandas.read_csv()` → use the Windows path as-is

## Writing and Running analysis.py

```
# Step 1 — write script (VIRTUAL PATH):
write_file(
    file_path="/projects/DeepResearchAgent/backend/outputs/{job_id}/code/analysis.py",
    content="..."
)

# Step 2 — execute (WINDOWS PATH):
execute("C:\\projects\\DeepResearchAgent\\backend\\.venv\\Scripts\\python.exe C:\\projects\\DeepResearchAgent\\backend\\outputs\\{job_id}\\code\\analysis.py")

# Step 3 — verify output (VIRTUAL PATH):
read_file("/projects/DeepResearchAgent/backend/outputs/{job_id}/charts.json")
```

## CSV Data Format from Data-Engineer

CSV files produced by `save_fmp_data` have one of two layouts:

**FRED time-series** (e.g. GDPC1, UNRATE):
```python
df = pd.read_csv(r"C:\...\GDPC1_real_gdp_quarterly_{job_id}.csv")
df["date"] = pd.to_datetime(df["date"])   # YYYY-MM-DD string → datetime
# Columns: date, value, series_id, title, units, frequency, ...
# Do NOT json.loads() any column — data is already flat rows
```

**FMP financial statement data** (e.g. income statement):
```python
df = pd.read_csv(r"C:\...\AAPL_income_statement_{job_id}.csv")
# Columns vary: date, revenue, netIncome, operatingIncome, eps, ...
# Numeric columns may contain strings like "1234567000" — cast with pd.to_numeric()
```

## Common Pitfall: NaN in Numeric Columns

FMP data occasionally has empty cells. Cast safely:
```python
df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
df = df.dropna(subset=["revenue"])
```
