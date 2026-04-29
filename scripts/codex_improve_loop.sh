#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAX_ITERS="${1:-5}"
CODEX_SANDBOX_MODE="${CODEX_SANDBOX_MODE:-danger-full-access}"

QUERIES=(
  "Compare US headline CPI inflation, core CPI inflation, and the effective federal funds rate since 2000. Identify periods where policy rates lagged inflation inflections. Use FRED for all data series."
  "Is the US labor market weakening right now? Use FRED data and explain what changed across the last few years."
  "Analyze the relationship between the US unemployment rate, labor force participation rate, and real average hourly earnings since 1990. Identify whether tight labor markets consistently translated into real wage gains. Use FRED for all data series."
  "Are consumers under stress? Use FRED macro data to build a concise evidence-based answer."
  "Analyze the relationship between the US 10-year minus 3-month Treasury yield spread, the US unemployment rate using the Sahm Rule, and Real Industrial Production over the last 40 years. Identify leading indicator patterns across the last 5 recessions. Use FRED for all data series."
  "Build a recession risk dashboard from FRED using rates, labor, credit, output, and inflation indicators. Decide which series are appropriate, justify the choices, and identify current risks versus prior cycles."
  "Compare the inflation-growth-policy mix in the 1970s, the 2001 recession, the 2008 financial crisis, the COVID shock, and the latest post-pandemic cycle. Use FRED series for inflation, unemployment, real output, industrial production, and policy rates."
  "Investigate whether the US economy is showing a soft landing, hard landing, or reacceleration pattern. Use at least six FRED macro series spanning labor, inflation, rates, credit, output, and consumption."
)

cd "$REPO_ROOT"

CODEX_MODEL_ARGS=()
if [[ -n "${CODEX_MODEL:-}" ]]; then
  CODEX_MODEL_ARGS=(--model "$CODEX_MODEL")
fi

printf 'Running FRED preflight outside Codex sandbox...\n'
(
  cd "$REPO_ROOT/backend"
  UV_CACHE_DIR=/tmp/uv-cache uv run python - <<'PY'
import asyncio

from dotenv import load_dotenv

from agents.data_engineer import get_data_engineer_subagent


async def main():
    load_dotenv(".env")
    await get_data_engineer_subagent()


asyncio.run(main())
PY
)
printf 'FRED preflight passed.\n'

for i in $(seq 1 "$MAX_ITERS"); do
  query_index=$(( (i - 1) % ${#QUERIES[@]} ))
  query="${QUERIES[$query_index]}"
  output_file="/tmp/codex-improver-pass-${i}.md"

  printf '\n=== Codex improvement pass %s/%s ===\n' "$i" "$MAX_ITERS"
  printf 'Query: %s\n\n' "$query"

  set +e
  codex exec \
    --cd "$REPO_ROOT" \
    --sandbox "$CODEX_SANDBOX_MODE" \
    --output-last-message "$output_file" \
    "${CODEX_MODEL_ARGS[@]}" \
    "Use the repo-local agent-improver skill.

Goal: improve the research agent flow centered on backend/agents/orchestrator.py.

Run exactly one execute-analyze-patch cycle:
1. From backend/, run:
   UV_CACHE_DIR=/tmp/uv-cache uv run python tests/runner.py --max-runtime-seconds 2400 --max-tool-calls 300 --max-identical-tool-calls 25 --max-fred-search-calls 100 --max-model-messages 5000 --query \"$query\"
2. Read the generated outputs/improver-*/agent_execution.log.
3. If the log contains WATCHDOG, STOPPED_EARLY, or STOP_REASON lines, treat that early-stop behavior as the primary issue to improve.
4. Otherwise, identify the highest-signal failure, unnecessary loop, unclear delegation, or flow inefficiency.
5. Patch only the smallest necessary files. Prefer backend/agents/orchestrator.py and existing prompt/skill files when justified.
6. FMP MCP is intentionally disabled because no paid FMP plan is available. Do not re-enable FMP or add integrations that require API keys, signup, OAuth, paid plans, or provisioned cloud resources.
7. Optional new tools/MCPs are allowed only when they are free, require no credentials or signup, have little overlap with existing FRED/local capabilities, degrade gracefully when unavailable, and directly address a report-quality gap from the trace.
8. Follow AGENTS.md. Before changes involving the Vercel AI SDK or LangChain DeepAgents, retrieve current documentation as required.
9. Run focused verification, at minimum tests relevant to the changed behavior when feasible.
10. Stop after one patch cycle and summarize changed files, reasoning, and tests.

Important:
- Do not loop inside this Codex session.
- Do not use codex resume.
- Do not stop early because of context usage; this script starts a fresh Codex process for the next test run.
- Do not touch secrets or .env files.
- Do not make unrelated refactors."
  codex_exit=$?
  set -e

  printf '\nCodex pass %s exited with status %s\n' "$i" "$codex_exit"
  printf 'Last Codex summary: %s\n' "$output_file"
  git status --short
done
