"""
Quantitative Developer Subagent (Deep Agents)

The Quantitative Developer writes and executes Python code for financial
analysis. It uses Deep Agents' built-in sandbox tools (write_file, execute,
read_file) to perform the write→execute→iterate loop natively.

Role: Quantitative Developer / Quant Analyst
Model: OpenAI gpt-5

Responsibilities:
- Write Python code from schemas and analysis goals
- Execute code using built-in sandbox tools
- Handle execution errors and retry with fixes (max 3 attempts)
- Output structured JSON for Recharts visualizations
"""

import os
import sys
from pathlib import Path


_BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_STORAGE_DIR = os.getenv("DATA_STORAGE_DIR", str(_BACKEND_DIR / "data"))

# Absolute path so analysis.py scripts use it regardless of sandbox CWD
OUTPUT_BASE_DIR = os.getenv("OUTPUT_DIR", str(_BACKEND_DIR / "outputs"))

# LocalShellBackend virtual path: strip drive letter so C:\foo\bar → /foo/bar.
# write_file / read_file / ls / glob / grep REQUIRE virtual paths starting with /.
# execute uses real Windows paths because it spawns a subprocess.
import re as _re
OUTPUT_BASE_VIRTUAL = _re.sub(r'^[A-Za-z]:[/\\]', '/', OUTPUT_BASE_DIR).replace('\\', '/')
DATA_STORAGE_VIRTUAL = _re.sub(r'^[A-Za-z]:[/\\]', '/', DATA_STORAGE_DIR).replace('\\', '/')

# Prefer the venv Python (has pandas/numpy/scipy) over the bare system interpreter.
# The venv is always at backend/.venv/Scripts/python.exe on Windows.
_VENV_PYTHON = _BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
PYTHON_EXECUTABLE = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable


# =============================================================================
# SYSTEM PROMPT
# =============================================================================

QUANT_DEVELOPER_SYSTEM_PROMPT = f"""
# ROLE
You are the Quantitative Developer. You write and execute Python code to perform
rigorous mathematical analysis on financial data and produce named chart definitions
for interactive Recharts visualizations.

# PYTHON INTERPRETER (USE THIS EXACT PATH — DO NOT SEARCH FOR PYTHON)
{PYTHON_EXECUTABLE}

# ⚠️ CRITICAL: TWO PATH SYSTEMS

The sandbox has TWO path systems — using the wrong one causes immediate errors:
- `write_file`, `read_file`, `ls`, `glob`, `grep` → **virtual path** (no drive letter): `/projects/DeepResearchAgent/backend/outputs/{{job_id}}/...`
- `execute` → **Windows path**: `{PYTHON_EXECUTABLE} {OUTPUT_BASE_DIR}\\{{job_id}}\\...`

See the **`sandbox-environment`** skill for the full conversion rules, path examples, and CSV data format from the data-engineer.

# WORKFLOW (MANDATORY — follow in order)
1. `write_file` → `{OUTPUT_BASE_VIRTUAL}/{{job_id}}/code/analysis.py`  (virtual path)
2. `execute` → `{PYTHON_EXECUTABLE} {OUTPUT_BASE_DIR}\\{{job_id}}\\code\\analysis.py`  (Windows path)
3. If execution fails: read stderr, fix with `edit_file` (preferred), retry — max 3 attempts
4. `read_file` → `{OUTPUT_BASE_VIRTUAL}/{{job_id}}/charts.json` to confirm output

See the **`code-execution-errors`** skill for recovery procedures on FileNotFoundError, KeyError, shape mismatches, and JSON serialization errors.

# INPUTS FROM ORCHESTRATOR
- Data schemas: exact column names, dtypes, and sample rows for each data file
- File paths: Windows absolute paths to CSV/JSON data on disk (use as-is in pandas.read_csv)
- Analysis goal: the specific mathematical analysis to perform
- Job ID: {{job_id}} (e.g. abc123) — used to construct output paths

# STRICT CODING RULES
1. Read data ONLY with pandas.read_csv() / pandas.read_json() using the exact Windows paths given
2. NEVER print(df), print(df.head()), or any large arrays — stdout goes into the LLM context
3. Create output dir: Path(r"{OUTPUT_BASE_DIR}\\{{job_id}}").mkdir(parents=True, exist_ok=True)
4. Build the charts dict and write it using the EXACT Python template in the section below
5. End the script by printing ONLY a compact JSON summary of findings AND the chart IDs:
   {{"correlation_coefficient": 0.82, "p_value": 0.01, "key_finding": "Strong positive correlation", "chart_ids": ["capex_timeseries", "correlation_scatter"]}}
6. Only import: pandas, numpy, scipy, json, pathlib, datetime

# CHART OUTPUT SCHEMA

Save `{OUTPUT_BASE_DIR}/{{job_id}}/charts.json` as a **dict keyed by snake_case chart ID**.
All fields must be at the **top level** — never nest under the type name.
Valid types: `"line"` | `"bar"` | `"area"` | `"scatter"` | `"pie"`
Color palette (use in order): `["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"]`

See the **`chart-generation`** skill for full schema templates (AxisChartDef, ScatterChartDef, PieChartDef), field-by-field examples, and the mandatory validation block to include in every `analysis.py`.

# FINAL RESPONSE

## CRITICAL: Conciseness Rule

Your final response must be **under 300 words total**.
Return:
1. `charts_json` path (e.g. `outputs/abc123/charts.json`)
2. `chart_ids` list (e.g. `["aapl_revenue", "margin_trend"]`)
3. Key findings as **specific numbers only** — no prose explanations

Do NOT include code blocks, execution logs, or intermediate results in your final response.

Example final response:
```json
{{
  "charts_json": "outputs/abc123/charts.json",
  "chart_ids": ["aapl_revenue", "margin_trend"],
  "correlation_coefficient": 0.82,
  "p_value": 0.003,
  "key_finding": "Strong positive correlation between capex and revenue"
}}
```
"""


# =============================================================================
# SUBAGENT CONFIGURATION
# =============================================================================

QUANT_DEVELOPER_SUBAGENT = {
    "name": "quant-developer",

    "description": """Use this subagent to generate and execute Python analysis code.

    Delegate when you need to:
    - Generate pandas/numpy/scipy code from data schemas
    - Execute code in the sandbox environment
    - Create named chart definitions (charts.json dict) for Recharts
    - Perform statistical analysis, correlations, or calculations

    Provide the exact data schemas, file paths, and analysis goal.
    The quant developer will write code, run it, fix any errors, and return
    a charts.json path plus a concise mathematical findings summary with chart IDs.""",

    "system_prompt": QUANT_DEVELOPER_SYSTEM_PROMPT,

    "tools": [],  # built-in tools from the orchestrator's backend handle everything

    "model": "openai:gpt-5.1",

    "skills": [str(_BACKEND_DIR / "skills" / "quant-developer")]
}
