---
name: code-execution-errors
description: Recovery procedures for Python execution errors in analysis.py — ModuleNotFoundError, FileNotFoundError, KeyError, shape mismatches, JSON errors
triggers:
  - error
  - traceback
  - failed
  - ModuleNotFoundError
  - FileNotFoundError
  - KeyError
  - ValueError
  - stderr
  - SyntaxError
  - execution failed
  - exit code 1
---

# Code Execution Error Recovery

## Before Retrying: Always Read stderr

```
execute("C:\\...\\python.exe C:\\...\\analysis.py")
# → if stdout is empty and exit code is non-zero:
read_file("/projects/.../outputs/{job_id}/code/analysis.py")   # check the script
```

Use `edit_file` for targeted fixes (preferred over rewriting the whole script).

---

## ModuleNotFoundError

```
ModuleNotFoundError: No module named 'scipy'
```

**Fix**: Only use these imports: `pandas`, `numpy`, `scipy`, `json`, `pathlib`, `datetime`.
If you tried to import anything else, remove it. All five listed modules are installed in the venv.

---

## FileNotFoundError — Input Data

```
FileNotFoundError: [Errno 2] No such file or directory: 'C:\...\AAPL_income.csv'
```

**Cause**: Wrong path. Data files use Windows absolute paths.
**Fix**: Check the exact path from the orchestrator's task instructions. Use raw strings:
```python
df = pd.read_csv(r"C:\projects\DeepResearchAgent\backend\data\{job_id}\AAPL_income_statement_{job_id}.csv")
```

---

## FileNotFoundError — Output Directory

```
FileNotFoundError: [Errno 2] No such file or directory: 'C:\...\outputs\{job_id}\charts.json'
```

**Fix**: Create the output directory before writing:
```python
from pathlib import Path
Path(r"C:\projects\DeepResearchAgent\backend\outputs\{job_id}").mkdir(parents=True, exist_ok=True)
```

---

## KeyError — Missing Column

```
KeyError: 'revenue'
```

**Fix**: Print available columns first (this is the ONE time printing a small thing is allowed):
```python
print(df.columns.tolist())
```
Then re-check the schema the orchestrator provided. FMP column names are camelCase: `netIncome`, `operatingExpenses`, `totalRevenue` — not snake_case.

---

## ValueError / Shape Mismatch in Correlation

```
ValueError: x and y must have same first dimension
```

**Fix**: Align DataFrames by date before correlating:
```python
merged = pd.merge(df1[["date","value"]], df2[["date","value"]], on="date", suffixes=("_a","_b"))
merged = merged.dropna()
r, p = scipy.stats.pearsonr(merged["value_a"], merged["value_b"])
```

---

## JSON Serialization Error in charts.json

```
TypeError: Object of type float32 is not JSON serializable
```

**Fix**: Cast numpy types before dumping:
```python
import numpy as np
def _to_python(obj):
    if isinstance(obj, (np.integer,)): return int(obj)
    if isinstance(obj, (np.floating,)): return float(obj)
    if isinstance(obj, np.ndarray): return obj.tolist()
    return obj

with open(charts_path, "w") as f:
    json.dump(charts, f, default=_to_python)
```

---

## Retry Limit

Maximum **3 attempts** per script. If still failing after 3 tries:
1. Return the exact stderr to the orchestrator
2. Include the last working partial output if any
3. Do not loop further
