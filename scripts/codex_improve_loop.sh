#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAX_ITERS="${1:-5}"
START_ITER="${START_ITER:-1}"
CODEX_SANDBOX_MODE="${CODEX_SANDBOX_MODE:-danger-full-access}"
LOOP_FOCUS="${LOOP_FOCUS:-combined}"
REQUESTED_LOOP_FOCUS="$LOOP_FOCUS"
LOG_ROOT="${LOG_ROOT:-$REPO_ROOT/logs/improve-loop}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
RUN_DIR="$LOG_ROOT/runs/$RUN_ID"
LATEST_SUMMARY="$LOG_ROOT/latest-summary.md"

COMBINED_QUERIES=(
  "I am preparing for an investment committee meeting next week and need a rigorous view on whether the US economy is entering a recession, still on a soft-landing path, or starting to reaccelerate. Please build an institutional-quality report that connects the macro cycle to consumer stress and the earnings risk for Apple and Microsoft. I need the analysis to compare the current cycle with prior downturns, explain whether labor, inflation, credit, production, consumption, and policy signals are confirming or contradicting each other, show how US conditions compare with several major international peers, and highlight whether regional consumer conditions in large US states change the national story. Include a quantitative recession-risk framework, a short-term unemployment outlook, base/upside/downside scenarios, a clear regime classification, charts and tables that an investment committee can scan quickly, careful source citations, and explicit caveats about data quality, timing, and what cannot be concluded."
  "A portfolio manager is worried that the US consumer is quietly weakening even though headline growth still looks fine. Build a report that separates national macro conditions from household stress, compares several large states with the national picture, checks whether labor and inflation data agree with the consumer signal, and explains what this means for large-cap technology earnings sensitivity. Include charts, tables, citations, scenario triggers, and caveats about stale or conflicting data."
  "I need a board-level macro risk memo on whether higher-for-longer policy is still the main risk or whether growth weakness is becoming more important. Compare rates, labor, production, credit, inflation, and consumption signals; add international context for major peers; connect the result to Apple and Microsoft fundamentals; and make the final answer clear enough for non-technical executives without hiding uncertainty."
  "Prepare a research report that tests whether the current US cycle looks more like 1995, 2001, 2008, 2020, or something different. Use appropriate public data sources, build a compact quant framework, show where the analogy breaks, include company earnings-risk context for Apple and Microsoft, and make charts that will render cleanly in the final report."
  "I am going into an investment committee debate where several people think the soft-landing story is already consensus and no longer useful. I need a report that tests that view instead of just narrating it: assess whether current macro and consumer conditions are more consistent with soft landing, delayed recession, or renewed acceleration, and explain how much confidence we should have. Compare today with prior cycles, show what a simple signal framework would have said before earlier downturns and false alarms, evaluate whether a short-horizon unemployment forecast adds useful information versus simple baselines, and stress-test what would have to change for Apple and Microsoft earnings risk to become meaningfully worse. Make the report useful for a skeptical committee: include the model evidence, backtest or historical simulation evidence where possible, what the models get wrong, readable charts/tables, source citations, and clear limits on what the data can and cannot prove."
  "I need a skeptical forecast review for the next six months of US unemployment. Do not just give a point forecast: explain whether the model beats simple baselines, where it would have failed historically, which predictors are doing the work, how prior false alarms should affect confidence, and what charts or tables an investment committee should rely on."
  "Build a recession-risk report for a risk committee that cares more about false positives than headline drama. I want to know what a simple signal stack would have said before earlier downturns, how often it cried wolf, which current signals are confirming or contradicting the risk call, and how much the conclusion changes under base, upside, and downside cases."
  "Create an evidence-heavy report on whether current macro conditions imply rising earnings risk for Apple and Microsoft. The report should connect macro and consumer indicators to company fundamentals, use historical replay or backtesting where possible, compare against naive explanations, and be explicit about what the quantitative evidence cannot prove."
  "Prepare a stock-specific research report on NVIDIA. I want to understand whether the business fundamentals support the current growth narrative, what the major revenue, margin, cash-flow, and balance-sheet trends show, and how sensitive the company looks to a macro slowdown or higher-for-longer rates. Use public filings and no-key public data where available, build charts and tables that render cleanly, compare recent performance with the company's own history rather than giving generic market commentary, include base/upside/downside risk scenarios, and be explicit about what cannot be concluded without paid market data or management guidance."
  "I want a historical simulation style report: take today's mix of labor, rates, inflation, credit, production, and consumer stress, compare it to prior cycle windows, and explain what happened next in those windows. Include model diagnostics, backtest evidence when available, charts that render correctly, and a plain-English conclusion that does not overstate causality."
)

case "$LOOP_FOCUS" in
  combined)
    ;;
  flow|content)
    LOOP_FOCUS="combined"
    ;;
  *)
    printf 'Unsupported LOOP_FOCUS=%s. Use combined.\n' "$LOOP_FOCUS" >&2
    exit 2
    ;;
esac

select_query() {
  local pass_num="$1"
  local index
  index=$(( (pass_num - 1) % ${#COMBINED_QUERIES[@]} ))
  printf '%s' "${COMBINED_QUERIES[$index]}"
}

cd "$REPO_ROOT"
mkdir -p "$RUN_DIR"

latest_agent_log() {
  find "$REPO_ROOT/backend/outputs" -maxdepth 2 -type f -name agent_execution.log -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr \
    | awk 'NR==1 {print $2}'
}

build_recent_context() {
  local context=""
  local count=0
  local pass_summary
  while IFS= read -r pass_summary; do
    [[ -f "$pass_summary" ]] || continue
    context+="- $pass_summary"$'\n'
    count=$((count + 1))
    [[ "$count" -ge 3 ]] && break
  done < <(find "$RUN_DIR" -maxdepth 2 -type f -name summary.md 2>/dev/null | sort -Vr)

  if [[ -n "$context" ]]; then
    printf 'Recent pass summaries from this script run. Read these files if useful before choosing a patch target:\n%s' "$context"
  else
    printf 'Recent pass summaries from this script run: none yet.'
  fi
}

write_prompt_file() {
  local prompt_file="$1"
  local recent_context="$2"
  local goal="improve both the research agent's token/tool efficiency and the final report's analytical substance in one two-stage pass."
  cat > "$prompt_file" <<PROMPT
Use the repo-local agent-improver skill.

Loop mode: $LOOP_FOCUS
Requested loop focus: $REQUESTED_LOOP_FOCUS
Goal: $goal

$recent_context

Run exactly one execute-analyze-patch cycle with two analysis stages:
1. From backend/, run:
   UV_CACHE_DIR=/tmp/uv-cache uv run python tests/runner.py --max-runtime-seconds 2400 --max-tool-calls 300 --max-identical-tool-calls 25 --max-fred-search-calls 100 --max-model-messages 5000 --query "$QUERY"
2. Locate and read the generated outputs/improver-*/agent_execution.log plus the generated report artifacts when they exist: report.json, execution_summary.json, charts.json, and code/analysis.py.
3. Stage 1, agent efficiency review:
   - Inspect token/tool efficiency before patching: unnecessary loops, duplicate/redundant tool calls, avoidable FRED searches, repeated filesystem inspection, retry churn, oversized prompts, unclear delegation, bad tool design, poor skill use, missed MCP/tool selection, and avoidable context growth.
   - If the log contains WATCHDOG, STOPPED_EARLY, STOP_REASON, max-tool-call, identical-tool-call, or retry-budget lines, treat that early-stop or budget behavior as the primary Stage 1 issue.
   - Identify whether the smallest fix belongs in orchestrator flow, data-engineer tools/prompts, quant-developer tool/runtime behavior, technical-writer/QA handoff, skills, runner instrumentation, or MCP/provider wrappers.
4. Stage 2, report substance review:
   - Once the report exists, inspect the final report text and artifacts, not only the trace. Treat a successful but shallow report as a failure.
   - Look for weak or missing econometrics, backtesting, historical replay/simulation, baseline comparisons, false-positive or miss analysis, forecast diagnostics, uncertainty, citations, source coverage, scenario support, report-vs-execution_summary fidelity, chart quality, frontend chart render-contract failures, and writer/QA preservation.
   - If the trace produces charts, run scripts/validate_report_charts.sh <path-to-report.json> on the generated report. Treat failures as deterministic evidence that chart schema, data keys, numeric values, writer normalization, or frontend rendering needs improvement.
   - If no report is generated, explain which Stage 1 issue prevented Stage 2 and patch that blocker first.
5. Patch only the smallest necessary files. If Stage 1 and Stage 2 reveal small, related fixes, patch both in the same pass. If they conflict or the Stage 1 issue prevents report generation, patch the blocker and summarize the Stage 2 signal to watch next.
6. FMP MCP is intentionally disabled because no paid FMP plan is available. Do not re-enable FMP or add integrations that require API keys, signup, OAuth, paid plans, or provisioned cloud resources.
7. Combined feature-aware improvement context:
   - This is no longer only a FRED macro smoke loop. It must harden the full research agent after the feature-loop work.
   - Treat the selected user query as a realistic feature acceptance test. The shell loop intentionally rotates across multiple natural prompts to avoid overfitting; patch general agent behavior and report-quality systems rather than tuning to one prompt. The user query should remain natural and should not tell the agent which providers or internal artifact names to use.
   - Infer the expected capabilities from the user's analytical needs: macro cycle analysis should select FRED, direct labor/inflation source checks should select BLS when useful, regional consumer context should select Census, international peer comparison should select World Bank, public-company fundamentals should select SEC EDGAR, and quantitative recession/forecast/scenario/regime work should select local quant code-writing helpers.
   - If the agent answers generically, skips a naturally relevant source/tool family, uses paid/keyed providers, or drops required artifact fields downstream, patch the smallest component that caused that miss.
   - Features now in scope include SEC EDGAR company facts, direct BLS public data, Census public data, World Bank indicators, local macro statistics helpers, optional statsmodels/econometrics workflows, composite predictive indicators, scenario/stress testing, recession/regime classification, technical-writer schema handling, QA gates, source/citation coverage, and integration-test behavior.
   - If the trace touches a public no-key integration, improve provider clients, tool docs, source metadata, error handling, mocked tests, and RUN_LIVE_INTEGRATION_TESTS-gated live smoke tests as needed.
   - If the trace touches local analysis, improve quant helper APIs, no-lookahead/mixed-frequency alignment, output schemas, methods_used, forecast/scenario/regime artifacts, fixture-driven integration tests, downstream writer/QA preservation, and common helper extraction for runtime code patterns the quant-developer keeps rewriting.
   - Do not invent new product areas. Improve the feature families listed above and the agent flow around them.
8. Follow AGENTS.md. Before changes involving the Vercel AI SDK or LangChain DeepAgents, retrieve current documentation as required.
9. Run focused verification:
   - Always run tests relevant to changed behavior.
   - For public no-key HTTP integrations, run mocked unit/contract tests and, when a live smoke test exists, run the relevant RUN_LIVE_INTEGRATION_TESTS=1 test or explain provider/network failure separately.
   - For local analysis features, run fixture-driven integration tests under backend/tests/integration when relevant.
   - For chart/report changes, run scripts/validate_report_charts.sh <path-to-report.json> when a report exists, plus focused backend technical-writer chart tests and frontend chart-contract tests.
   - Keep live tests tiny; do not use paid or credentialed services.
10. Stop after one patch cycle and summarize changed files, reasoning, tests, and whether the affected feature acceptance signal now looks stronger.
11. In your analysis, use repo tools such as rg/grep/find yourself to inspect the generated agent_execution.log, previous pass summaries, changed files, tests, and stop markers. The shell loop intentionally does not classify logs for you.
12. End your final answer with exactly these two machine-readable lines:
    IMPROVER_RESULT: patched|no_patch|blocked
    IMPROVER_NEXT_SIGNAL: one short sentence describing what the next run should watch.

Important:
- Do not loop inside this Codex session.
- Do not use codex resume.
- Do not stop early because of context usage; this script starts a fresh Codex process for the next test run.
- Do not touch secrets or .env files.
- Do not make unrelated refactors.
- Do not repeat the same patch area as recent passes unless you inspect the latest trace and prove that issue remains.
PROMPT
}

write_pass_summary() {
  local pass_dir="$1"
  local pass_num="$2"
  local start_time="$3"
  local end_time="$4"
  local codex_exit="$5"
  local output_file="$6"
  local agent_log="$7"
  local query="$8"
  local summary_file="$pass_dir/summary.md"

  if [[ -s "$output_file" ]]; then
    cp "$output_file" "$pass_dir/codex-summary.md"
  else
    printf 'Codex did not write a non-empty summary for pass %s.\n' "$pass_num" > "$pass_dir/codex-summary.md"
  fi

  {
    printf '# Improve Loop Pass %s\n\n' "$pass_num"
    printf 'Started: %s\n' "$start_time"
    printf 'Ended: %s\n' "$end_time"
    printf 'Codex exit: %s\n' "$codex_exit"
    printf 'Agent log: %s\n' "${agent_log:-unknown}"
    printf 'Query: %s\n' "$query"
    printf 'Codex summary: %s\n' "$pass_dir/codex-summary.md"
    printf '\n## Codex Summary\n\n'
    cat "$pass_dir/codex-summary.md"
  } > "$summary_file"
}

update_latest_summary() {
  local pass_files
  mapfile -t pass_files < <(find "$RUN_DIR" -maxdepth 2 -type f -name summary.md 2>/dev/null | sort -V)
  {
    printf '# Codex Improve Loop Summary\n\n'
    printf 'Run: %s\n' "$RUN_ID"
    printf 'Loop mode: %s\n' "$LOOP_FOCUS"
    printf 'Requested loop focus: %s\n' "$REQUESTED_LOOP_FOCUS"
    printf 'Run directory: %s\n' "$RUN_DIR"
    printf 'Updated: %s\n\n' "$(date -Is)"
    printf '## Passes\n\n'
    local file pass
    for file in "${pass_files[@]}"; do
      pass="$(basename "$(dirname "$file")")"
      printf -- '- %s: summary=%s\n' "$pass" "$file"
    done
    printf '\n## How To Review\n\n'
    printf -- '- Open the newest pass summary and agent log listed above.\n'
    printf -- '- Let the Codex pass inspect logs itself; this script only preserves paths and metadata.\n'
  } > "$LATEST_SUMMARY"
}

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

end_iter=$((START_ITER + MAX_ITERS - 1))
consecutive_codex_failures=0

printf 'Improve loop run directory: %s\n' "$RUN_DIR"
printf 'Loop mode: %s\n' "$LOOP_FOCUS"
printf 'Requested loop focus: %s\n' "$REQUESTED_LOOP_FOCUS"
printf 'Latest rollup: %s\n' "$LATEST_SUMMARY"

for i in $(seq "$START_ITER" "$end_iter"); do
  output_file="/tmp/codex-improver-pass-${i}.md"
  pass_dir="$RUN_DIR/pass-${i}"
  prompt_file="$pass_dir/prompt.txt"
  query_file="$pass_dir/query.txt"
  start_time="$(date -Is)"
  recent_context="$(build_recent_context)"
  QUERY="$(select_query "$i")"
  mkdir -p "$pass_dir"
  printf '%s\n' "$QUERY" > "$query_file"
  write_prompt_file "$prompt_file" "$recent_context"

  printf '\n=== Codex improvement pass %s/%s ===\n' "$i" "$end_iter"
  printf 'Query: %s\n\n' "$QUERY"
  printf 'Prompt file: %s\n' "$prompt_file"

  set +e
  codex exec \
    --cd "$REPO_ROOT" \
    --sandbox "$CODEX_SANDBOX_MODE" \
    --output-last-message "$output_file" \
    "${CODEX_MODEL_ARGS[@]}" \
    "$(cat "$prompt_file")"
  codex_exit=$?
  set -e
  end_time="$(date -Is)"
  agent_log="$(latest_agent_log || true)"

  write_pass_summary "$pass_dir" "$i" "$start_time" "$end_time" "$codex_exit" "$output_file" "$agent_log" "$QUERY"
  update_latest_summary

  printf '\nCodex pass %s exited with status %s\n' "$i" "$codex_exit"
  printf 'Last Codex summary: %s\n' "$output_file"
  printf 'Pass summary: %s\n' "$pass_dir/summary.md"
  printf 'Latest rollup: %s\n' "$LATEST_SUMMARY"
  git status --short

  if [[ "$codex_exit" -ne 0 ]]; then
    consecutive_codex_failures=$((consecutive_codex_failures + 1))
  else
    consecutive_codex_failures=0
  fi

  if [[ ! -s "$output_file" ]]; then
    printf '\nStopping: Codex did not write a non-empty summary for pass %s.\n' "$i"
    break
  fi

  if [[ "$consecutive_codex_failures" -ge 2 ]]; then
    printf '\nStopping: Codex exited nonzero for %s consecutive passes.\n' "$consecutive_codex_failures"
    break
  fi
done
