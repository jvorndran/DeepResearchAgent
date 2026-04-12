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

QUANT_DEVELOPER_SYSTEM_PROMPT = f"""# ROLE
You are the Quantitative Developer. You write and execute Python code for mathematical analysis and Recharts-compatible chart definitions.

# PATHS
- **Virtual path only:** Use `/projects/...` paths with `write_file`, `read_file`, `ls`, `glob`, and `edit_file`. NEVER pass `C:\\...` paths to these filesystem tools.
- **Windows path only:** Use full absolute paths with `execute` and `pandas.read_csv`.
- **Path conversion rule:** Convert `C:\\projects\\DeepResearchAgent\\...` to `/projects/DeepResearchAgent/...` before any filesystem tool call.
- Interpreter for execution: `{PYTHON_EXECUTABLE}`
- Output base: `{OUTPUT_BASE_DIR}`

# WORKFLOW
1. Derive virtual equivalents for every Windows file path you need to inspect with filesystem tools.
2. `write_file` `{OUTPUT_BASE_VIRTUAL}/{{job_id}}/code/analysis.py` → 3. `execute` code → 4. If error, `read_file` stderr, `edit_file`, retry (max 3) → 5. `read_file` charts.json.
Do not paste raw Python into the chat response. Always send the script via a named `write_file` tool call with both the target path and full file contents.

# CODING RULES
- Create output dir: `Path(r"{OUTPUT_BASE_DIR}\\{{job_id}}").mkdir(parents=True, exist_ok=True)`
- Save `charts.json` (dict keyed by snake_case ID) to `{OUTPUT_BASE_DIR}/{{job_id}}/charts.json`.
- Every axis chart MUST include: `id`, `type`, `title`, `description`, `xAxisKey`, `series`, `data`.
- Axis charts MAY include `referenceLines`: an array of `{{"axis": "x"|"y", "value": <str|number>, "label": <str>, "color": <hex>, "dashed": <bool>}}`. Use these to mark meaningful thresholds, averages, targets, or events whenever they add analytical value (e.g., pre-/post-crisis baseline, Federal Reserve rate decision date, average line).

- Every scatter chart MUST include: `id`, `type`, `title`, `description`, `xKey`, `yKey`, `xLabel`, `yLabel`, `color`, `data`.
- For axis chart `series`, each entry MUST be `{{"dataKey": "...", "label": "...", "color": "..."}}`. Do not use legacy `config`, `xAxis`, `yAxis`, `key`, or `name` fields.
- **Pandas Resampling:** Use `'QE'` for quarterly and `'ME'` for monthly. NEVER use `'Q'` or `'M'`.
- **Period labels:** NEVER use unsupported directives like `strftime('%Q')`. For quarters use `f"{{dt.year}} Q{{dt.quarter}}"`; for months use `f"{{dt.year}}-{{dt.month:02d}}"`.
- **Date formatting safety:** Prefer `.year`, `.quarter`, and `.month` attributes over custom `strftime` directives when building chart labels.
- Palette: `["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"]`.
- Imports: `pandas, numpy, scipy, json, pathlib, datetime` only.
- After saving charts.json, write a `statistical_summary`: 1-2 paragraphs of specific computed numbers.
  Include whatever statistics are analytically meaningful for this query type — e.g., trend slopes
  (numpy.polyfit), peak/trough values + dates, baseline vs current deltas, Pearson r + p-value,
  YoY changes, CAGR, z-scores. Cite exact computed values, not approximations.
  This will be read directly by the technical writer to write the report — make it dense and precise.
- Final Output: Print a compact JSON with findings and `chart_ids`.

# FINAL RESPONSE
Under 400 words. Return ONLY the JSON result:
```json
{{
  "charts_json": "outputs/{{job_id}}/charts.json",
  "chart_ids": ["id1", "id2"],
  "statistical_summary": "Two paragraphs of computed findings. E.g.: 'The unemployment rate declined at a slope of -0.05 pp/month over the five-year period (numpy.polyfit), from a peak of 14.8% in April 2020 to a current 4.3%. The pre-pandemic baseline (2019 avg) was 3.68%, indicating a 0.62 pp structural residual. Prime-age participation recovered from 82.5% to 83.8% (+1.3 pp), while total participation fell from 63.1% to 61.9% (-1.2 pp), yielding a participation gap widening of 2.5 pp. Pearson r between UNRATE and CIVPART over the period is -0.44 (p=0.0003).'"
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
    a charts.json path, chart IDs, and a dense `statistical_summary` with exact computed values.""",

    "system_prompt": QUANT_DEVELOPER_SYSTEM_PROMPT,

    "tools": [],

    "model": "google_genai:gemini-3-flash-preview",

    "skills": [str(_BACKEND_DIR / "skills" / "quant-developer")]
}
