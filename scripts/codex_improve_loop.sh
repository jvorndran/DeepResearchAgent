#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAX_ITERS="${1:-5}"
START_ITER="${START_ITER:-1}"
CODEX_SANDBOX_MODE="${CODEX_SANDBOX_MODE:-danger-full-access}"
CODEX_REASONING_EFFORT="${CODEX_REASONING_EFFORT:-xhigh}"
LOOP_MODE="${LOOP_MODE:-improve}"
LOOP_FOCUS="${LOOP_FOCUS:-combined}"
REQUESTED_LOOP_MODE="$LOOP_MODE"
REQUESTED_LOOP_FOCUS="$LOOP_FOCUS"
LOG_ROOT="${LOG_ROOT:-$REPO_ROOT/logs/improve-loop}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
RUN_DIR="$LOG_ROOT/runs/$RUN_ID"
LATEST_SUMMARY="$LOG_ROOT/latest-summary.md"
PHOENIX_HOST="${PHOENIX_HOST:-127.0.0.1}"
PHOENIX_PORT="${PHOENIX_PORT:-6006}"
if [[ -z "${PHOENIX_BASE_URL:-}" && -n "${PHOENIX_COLLECTOR_ENDPOINT:-}" ]]; then
  PHOENIX_BASE_URL="${PHOENIX_COLLECTOR_ENDPOINT%/v1/traces}"
else
  PHOENIX_BASE_URL="${PHOENIX_BASE_URL:-http://$PHOENIX_HOST:$PHOENIX_PORT}"
fi
PHOENIX_LOG="$RUN_DIR/phoenix.log"
PHOENIX_PID=""
export PHOENIX_COLLECTOR_ENDPOINT="${PHOENIX_COLLECTOR_ENDPOINT:-$PHOENIX_BASE_URL}"
export PHOENIX_PROJECT_NAME="${PHOENIX_PROJECT_NAME:-deep-research-agent-improver}"
export PHOENIX_WORKING_DIR="${PHOENIX_WORKING_DIR:-$RUN_DIR/phoenix-working}"
export RUNNER_TRACE_EXPORT_MODE="${RUNNER_TRACE_EXPORT_MODE:-phoenix}"
export RUNNER_REQUIRE_PHOENIX="${RUNNER_REQUIRE_PHOENIX:-1}"
export LOOP_RUN_ID="$RUN_ID"

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

CHART_QUERIES=(
  "Build a chart-heavy macro report comparing headline CPI inflation, core CPI inflation, and the effective federal funds rate since 1990. Produce 6-8 governed renderable charts. Use time-series and composed charts for trends and overlays, but also use other governed chart families where they make the policy-lag interpretation easier: scatter or bubble for relationships, radar for normalized regime profiles, radialBar for current component scores, treemap or sunburst for contribution hierarchy, funnel for staged filters, and sankey for signal flow. Prefer at least three chart families when the data supports them, but do not add novelty charts when time series are clearly the most insightful view."
  "Create a recession-dashboard report using FRED time series for the 10-year minus 3-month Treasury spread, unemployment, industrial production, credit conditions, and recession indicators over the last 40 years. Produce 6-8 governed renderable charts with recession bands, no stale empty tails, legible x-axis dates, and annotations that make historical leading-indicator patterns obvious. Include a defensible mix of chart families such as line/composed trend views, radar or radialBar signal profiles, treemap/sunburst contribution views, scatter/bubble relationships, and funnel or sankey-style signal-flow views when supported by the computed data."
  "Analyze whether the US consumer is under stress using FRED macro data. Build a 6-8 chart dashboard with savings, real income or wages, unemployment, inflation, sentiment or consumption where available, and credit stress. The charts should expose conflicts between indicators, missing-data limits, and recent inflection points instead of only showing latest levels. Use the broad governed chart contract, including stacked or horizontal bars, donut pies, radar/radialBar component profiles, scatter/bubble relationships, and treemap/sunburst contribution views when they clarify the consumer-stress decision."
  "Make a historical replay report comparing current labor, inflation, rates, production, and consumer-stress indicators with the 2001, 2008, 2020, and post-pandemic cycle windows. Produce 6-8 governed renderable charts that clearly separate current-window overlays from historical analogs and avoid reference bands outside the plotted data range. Prefer multiple chart families where useful: line/composed overlays for replay paths, scatter/bubble for analog distance or relationships, radar for normalized window profiles, radialBar for current signal scores, and treemap/sunburst/funnel/sankey views only when they make the replay evidence easier to understand."
  "Build a forecast-overlay report for US unemployment over the next six months using simple baselines and at least one local statistical model. Produce 6-8 governed renderable charts, including actual-vs-fitted and forecast-band charts, backtest errors or false alarms, predictor evidence, and uncertainty views without clipping the y-axis. Use non-time-series governed families where they add insight: scatter/bubble for fitted-vs-actual or residual relationships, radar/radialBar for predictor contribution profiles, treemap/sunburst for contribution hierarchy, and funnel/sankey for model selection or signal-flow explanations."
  "Compare real GDP growth, unemployment, recession periods, and industrial production since 1980. Produce 6-8 governed renderable charts that preserve all chart IDs into the report, use consistent date keys, avoid empty series values, and make the recession-cycle interpretation more insightful than a basic line chart. Mostly time-series charts are acceptable if they are most informative, but the chart pack should consider scatter/bubble relationships, radar/radialBar signal profiles, and hierarchy or flow charts when the computed data supports them."
  "Create a macro cycle chart pack for an investment committee: produce 6-8 governed renderable charts covering rates/inflation, labor, output/production, consumer stress, historical analogs, and a synthesis view. Use FRED data, highlight what changed in the latest year, and make each chart answer a distinct analytical question. Prefer at least three chart families when defensible, using the governed contract rather than arbitrary Recharts passthrough: line, bar, area, composed, scatter, pie, treemap, radar, radialBar, funnel, sankey, and sunburst."
  "Test whether current macro conditions look like a soft landing, delayed recession, or reacceleration. Produce 6-8 governed renderable charts with clear axis ranges, readable legends, and historical comparisons that reveal why the classification could be wrong. Include caveats for missing values and mixed-frequency alignment. Use varied chart families when useful for the classification decision: composed trends, scatter/bubble relationships, radar/radialBar normalized profiles, treemap/sunburst contribution hierarchy, funnel staged filters, and sankey decomposition flows."
)

case "$LOOP_FOCUS" in
  refactor|clean-code|cleanup)
    LOOP_MODE="refactor"
    LOOP_FOCUS="combined"
    ;;
esac

case "$LOOP_MODE" in
  improve|refactor)
    ;;
  *)
    printf 'Unsupported LOOP_MODE=%s. Use improve or refactor.\n' "$LOOP_MODE" >&2
    exit 2
    ;;
esac

case "$LOOP_FOCUS" in
  combined)
    ;;
  flow|content)
    LOOP_FOCUS="combined"
    ;;
  charts|chart|charting|chart-validation)
    LOOP_FOCUS="charts"
    ;;
  *)
    printf 'Unsupported LOOP_FOCUS=%s. Use combined, charts, or refactor aliases.\n' "$LOOP_FOCUS" >&2
    exit 2
    ;;
esac

if [[ -z "${CHART_AUDIT_RENDER:-}" ]]; then
  if [[ "$LOOP_FOCUS" == "charts" ]]; then
    CHART_AUDIT_RENDER="required"
  else
    CHART_AUDIT_RENDER="auto"
  fi
fi
export CHART_AUDIT_RENDER
export ELECTRON_EXTRA_LAUNCH_ARGS="${ELECTRON_EXTRA_LAUNCH_ARGS:---no-sandbox --disable-dev-shm-usage}"
export LOOP_MODE
export LOOP_FOCUS

select_query() {
  local pass_num="$1"
  local index
  if [[ "$LOOP_FOCUS" == "charts" ]]; then
    index=$(( (pass_num - 1) % ${#CHART_QUERIES[@]} ))
    printf '%s' "${CHART_QUERIES[$index]}"
  else
    index=$(( (pass_num - 1) % ${#COMBINED_QUERIES[@]} ))
    printf '%s' "${COMBINED_QUERIES[$index]}"
  fi
}

cd "$REPO_ROOT"
mkdir -p "$RUN_DIR"

latest_trace_digest() {
  find "$REPO_ROOT/backend/outputs" -maxdepth 2 -type f -name trace-digest.md -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr \
    | awk 'NR==1 {print $2}'
}

phoenix_is_ready() {
  curl -fsS "$PHOENIX_BASE_URL" >/dev/null 2>&1
}

ensure_phoenix() {
  if phoenix_is_ready; then
    printf 'Phoenix is already reachable at %s\n' "$PHOENIX_BASE_URL"
    return
  fi

  printf 'Starting Phoenix at %s...\n' "$PHOENIX_BASE_URL"
  (
    cd "$REPO_ROOT/backend"
    UV_CACHE_DIR=/tmp/uv-cache uv run --extra dev phoenix serve > "$PHOENIX_LOG" 2>&1
  ) &
  PHOENIX_PID=$!
  trap 'if [[ -n "${PHOENIX_PID:-}" ]]; then kill "$PHOENIX_PID" 2>/dev/null || true; fi' EXIT

  local attempt
  for attempt in $(seq 1 60); do
    if phoenix_is_ready; then
      printf 'Phoenix started; log: %s\n' "$PHOENIX_LOG"
      return
    fi
    sleep 1
  done

  printf 'Phoenix did not become reachable at %s. See %s\n' "$PHOENIX_BASE_URL" "$PHOENIX_LOG" >&2
  exit 1
}

verify_phoenix_collection() {
  printf 'Verifying Phoenix trace collection...\n'
  (
    cd "$REPO_ROOT/backend"
    PHOENIX_PREFLIGHT_JOB_ID="phoenix-preflight-${RUN_ID}" UV_CACHE_DIR=/tmp/uv-cache uv run --extra dev python - <<'PY'
import json
import os
import sys
import time

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from phoenix.client import Client

try:
    from openinference.semconv.resource import ResourceAttributes

    project_attr = ResourceAttributes.PROJECT_NAME
except Exception:
    project_attr = "openinference.project.name"

project_name = os.environ["PHOENIX_PROJECT_NAME"]
job_id = os.environ["PHOENIX_PREFLIGHT_JOB_ID"]
endpoint = os.environ["PHOENIX_COLLECTOR_ENDPOINT"].rstrip("/")
if not endpoint.endswith("/v1/traces"):
    endpoint = f"{endpoint}/v1/traces"

provider = TracerProvider(
    resource=Resource.create(
        {
            "service.name": "deep-research-agent-phoenix-preflight",
            project_attr: project_name,
        }
    )
)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
tracer = provider.get_tracer("deep_research_agent.phoenix_preflight")
with tracer.start_as_current_span(
    "runner.phoenix_preflight",
    attributes={"job_id": job_id, "event_type": "phoenix_preflight"},
):
    pass
provider.force_flush(timeout_millis=30000)


def record_job_id(record):
    attrs = record.get("attributes")
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except json.JSONDecodeError:
            attrs = {}
    if not isinstance(attrs, dict):
        attrs = {}
    if attrs.get("job_id") == job_id:
        return True
    for key, value in record.items():
        if key == "job_id" and value == job_id:
            return True
        if key.startswith("attributes.") and key.removeprefix("attributes.") == "job_id":
            return value == job_id
    return False


base_url = os.environ["PHOENIX_COLLECTOR_ENDPOINT"].rstrip("/")
if base_url.endswith("/v1/traces"):
    base_url = base_url.removesuffix("/v1/traces")
client = Client(base_url=base_url)
deadline = time.time() + 20
last_error = None
while time.time() < deadline:
    try:
        spans_df = client.spans.get_spans_dataframe(
            project_identifier=project_name,
            limit=1000,
        )
    except TypeError:
        try:
            spans_df = client.spans.get_spans_dataframe(project_identifier=project_name)
        except Exception as exc:
            last_error = exc
            time.sleep(1)
            continue
    except Exception as exc:
        last_error = exc
        try:
            spans_df = client.spans.get_spans_dataframe(limit=1000)
        except TypeError:
            try:
                spans_df = client.spans.get_spans_dataframe()
            except Exception as fallback_exc:
                last_error = fallback_exc
                time.sleep(1)
                continue
        except Exception as fallback_exc:
            last_error = fallback_exc
            time.sleep(1)
            continue
    records = spans_df.to_dict(orient="records") if spans_df is not None else []
    if any(record_job_id(record) for record in records):
        print(f"Phoenix collected preflight span for {job_id}")
        raise SystemExit(0)
    time.sleep(1)

if last_error is not None:
    print(f"Phoenix span export check failed: {last_error}", file=sys.stderr)
else:
    print(f"Phoenix did not return preflight span for {job_id}", file=sys.stderr)
raise SystemExit(1)
PY
  )
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

best_fix_policy_block() {
  cat <<'PROMPT_BLOCK'
Best-fix engineering policy:
- Do not optimize for minimal diff size. Choose the best root-cause fix that preserves or improves the agent flow, even when that requires a coherent subsystem refactor.
- Avoid symptom patches: no new broad phrase-matching tables, magic prompt strings, ad hoc substring catch-alls, one-off branches for a single trace wording, or prompt-only workarounds when a typed contract, schema, validator, tool result, state field, or clearer ownership boundary would solve the class of failure.
- Prefer structured contracts over prose inference: typed JSON payloads, explicit tool return fields, deterministic validators, named failure categories, and handoff schemas should carry routing and recovery decisions.
- If existing heuristic debt is on the direct path, either replace it with a structured contract as part of the planned fix or explicitly document why it is out of scope for this pass and what cleanup signal should trigger removal.
- Do not reintroduce canned quant report builders, report-specific artifact tools, query-marker report routing, exact report contracts, or prompt language that tells quant-developer to run a report-specific tool before writing analysis.py. Quant reports must be composed from reusable helpers in generated code.
- Refactors are acceptable when they reduce retry churn, prompt bloat, duplicated guardrails, brittle routing, unclear specialist ownership, or artifact handoff ambiguity. Keep the refactor coherent; do not scatter unrelated cleanup across the repo.
- Before finalizing a build, self-review the diff for workaround smells and state why the patch is a root-cause fix rather than another layer of brittle special cases.
PROMPT_BLOCK
}

write_improve_plan_prompt_file() {
  local prompt_file="$1"
  local recent_context="$2"
  local query="$3"
  local goal="plan the best root-cause improvement for both the research agent's token/tool efficiency and the final report's analytical substance."
  local chart_focus_block
  local best_fix_policy
  local playwright_cli_path
  local playwright_diag_block
  best_fix_policy="$(best_fix_policy_block)"
  playwright_cli_path="$(command -v playwright-cli 2>/dev/null || true)"
  playwright_diag_block=$(cat <<'PROMPT_BLOCK'
Playwright CLI diagnostic guidance:
- Keep Cypress and scripts/audit_report_charts.sh as the deterministic pass/fail gate. Playwright CLI is an investigation tool for explaining browser/DOM failures; do not add automatic Playwright invocation to the outer shell loop.
- Use the `playwright-cli` skill when it is listed in your available skills. If that skill is not loaded in this Codex session, do not stop there: first run `command -v playwright-cli` and use the local `playwright-cli` binary directly when it is available.
- Use Playwright CLI diagnosis when scripts/audit_report_charts.sh or Cypress fails, when charts are visible but blank, when chart wrappers/SVGs have positive dimensions but no Recharts marks, when Recharts sizing warnings appear, or when the report page renders differently from the static chart contract.
- If `playwright-cli` itself is unavailable or blocked by the sandbox/browser install, record the exact command and error in the pass summary, mark Playwright diagnosis as blocked, and continue with Cypress/audit artifacts and static DOM/chart-contract inspection. Do not repeatedly retry a missing skill or unavailable command.
- Start or reuse a frontend dev server before browser diagnosis. Route the failing report.json into `/chart-render-audit/chart_family_audit` so the rendered page uses the exact artifact that failed audit.
- Use `playwright-cli --raw run-code` to inspect the rendered page and collect per-chart wrapper dimensions, SVG count, mark count, Recharts class names, text snippets, and console warnings/errors.
- Compare the rendered DOM against the report JSON to identify the responsible frontend or writer-normalization issue, including prop-shape problems such as `layout: null`, dropped data keys, stale route payloads, or static-contract fields that the frontend normalizes differently.
- In the pass summary, record whether Playwright CLI was used, the inspected URL and report path, the key DOM findings, and the responsible layer or subsystem selected.
PROMPT_BLOCK
)
  if [[ -n "$playwright_cli_path" ]]; then
    playwright_diag_block+="
- The outer loop shell resolved playwright-cli at \`$playwright_cli_path\`. If \`command -v playwright-cli\` fails inside the Codex session but this absolute path still exists, use \`$playwright_cli_path\` directly."
  else
    playwright_diag_block+="
- The outer loop shell did not find playwright-cli on PATH when this prompt was generated; treat that as a likely environment issue if browser diagnosis is needed."
  fi
  if [[ "$LOOP_FOCUS" == "charts" ]]; then
    goal="plan the best root-cause improvement for chart generation, chart artifact fidelity, static chart auditing, and frontend chart rendering."
    chart_focus_block=$(cat <<'PROMPT_BLOCK'
Chart-mode priority:
- Make chart generation and validation the primary improvement signal for this pass. Efficiency still matters, but chart artifact correctness, renderability, and analytical usefulness come first unless the run fails before artifacts exist.
- For explicit chart-heavy, chart-pack, dashboard, or chart-validation prompts, push the agent toward 6-8 governed renderable charts. Empty chart output is not an acceptable fallback for these prompts.
- The governed report chart contract now covers `line`, `bar`, `area`, `composed`, `scatter`, `pie`, `treemap`, `radar`, `radialBar`, `funnel`, `sankey`, and `sunburst`. Useful variants are supported without new chart types: stacked bars/areas via `stackId`, horizontal bars via `layout`, donut pies via `innerRadius`, and bubble scatter via `sizeKey`/`colorKey`. Do not ask for arbitrary Recharts passthrough.
- For chart-heavy 6-8 chart packs, prefer at least three chart families when the data supports them: trends and overlays with Cartesian charts, relationships with scatter/bubble, normalized profiles with radar, component scores with radialBar, contribution hierarchy with treemap/sunburst, staged filters with funnel, and flows/decomposition with sankey. This is a preference, not a blocker; a mostly time-series pack is acceptable when it is the most honest analytical view.
- Treat these chart failures as first-priority evidence: missing chart artifacts when the query asks for charts; chart IDs dropped between quant output and report.json; report markers not matching chart definitions; empty data; blank x-axis keys; missing series values; arbitrary or unsupported chart types; bad dual-axis choices; clipped domains; stale empty tails; reference bands outside plotted data; non-finite numeric values; non-positive segment/hierarchy/flow values; empty hierarchy children; invalid Sankey node/link indexes; frontend render failures; invisible chart marks; NaN/Infinity SVG attributes; or contract error panels.
- After reading the generated report and charts, explicitly ask yourself: "How could each chart be more insightful for the user's decision?" Use the answer to choose a patch when the charts are technically valid but analytically shallow, redundant, poorly annotated, missing useful overlays, missing historical context, or not tied to the report conclusion.
- Select the responsible subsystem for the build phase: quant chart generation, save_quant_outputs, technical-writer normalization, report static gate, quality analyst blockers, frontend chart contract/rendering, or focused tests.
- Run scripts/audit_report_charts.sh <path-to-report.json> after every generated report. The outer loop exports CHART_AUDIT_RENDER=required by default in chart mode and WSL-safe Electron flags; the audit script will use a reachable frontend dev server or start a temporary one on localhost.
- The pass summary must include report path, chart audit result, browser render result or skip reason, whether Playwright CLI was used, inspected URL/report path, key DOM findings, responsible subsystem, changed files, tests, and the next chart signal to watch.
PROMPT_BLOCK
)
  else
    chart_focus_block=$(cat <<'PROMPT_BLOCK'
Chart-aware combined-mode check:
- If the report contains charts, run scripts/audit_report_charts.sh <path-to-report.json>. Treat failures as deterministic evidence that chart schema, data keys, numeric values, writer normalization, static validation, or frontend rendering needs improvement.
- The outer loop exports WSL-safe Electron flags for Cypress. In combined mode, CHART_AUDIT_RENDER defaults to auto, so browser rendering runs when a frontend dev server is reachable.
- The governed chart contract includes Cartesian, polar, hierarchy, funnel, and flow families: `line`, `bar`, `area`, `composed`, `scatter`, `pie`, `treemap`, `radar`, `radialBar`, `funnel`, `sankey`, and `sunburst`. Prefer varied chart families when they clarify the analysis, but do not treat time-series-heavy reports as failures when time series are the most insightful evidence.
- After reading generated charts, explicitly ask yourself: "How could each chart be more insightful for the user's decision?" Patch chart insight quality when the charts are technically valid but analytically shallow, redundant, poorly annotated, missing useful overlays, missing historical context, or not tied to the report conclusion.
PROMPT_BLOCK
)
  fi
  cat > "$prompt_file" <<PROMPT
Use the repo-local agent-improver skill.

Loop mode: $LOOP_MODE
Loop focus: $LOOP_FOCUS
Requested loop mode: $REQUESTED_LOOP_MODE
Requested loop focus: $REQUESTED_LOOP_FOCUS
Goal: $goal

$recent_context

$best_fix_policy

$chart_focus_block

$playwright_diag_block

Phase: improve-plan

Run exactly one execute-analyze-plan cycle with two analysis stages. This phase must not modify code, stage changes, run formatters, or apply patches.
1. From backend/, run:
   UV_CACHE_DIR=/tmp/uv-cache uv run python tests/runner.py --max-runtime-seconds 2400 --max-tool-calls 300 --max-identical-tool-calls 25 --max-fred-search-calls 100 --max-model-messages 5000 --query "$query"
2. Locate and read the generated outputs/improver-*/trace-digest.md first, then trace_diagnostics.json, phoenix_spans.jsonl, and generated report artifacts when they exist: report.json, execution_summary.json, charts.json, and code/analysis.py.
3. Stage 1, agent efficiency review:
   - Inspect token/tool efficiency before planning: unnecessary loops, duplicate/redundant tool calls, avoidable FRED searches, repeated filesystem inspection, retry churn, oversized prompts, unclear delegation, bad tool design, poor skill use, missed MCP/tool selection, and avoidable context growth.
   - If trace diagnostics show watchdog stops, stopped-early status, stop_reason, max-tool-call, identical-tool-call, or retry-budget behavior, treat that early-stop or budget behavior as the primary Stage 1 issue.
   - Identify the root-cause subsystem: orchestrator flow, data-engineer tools/prompts, quant-developer tool/runtime behavior, technical-writer/QA handoff, skills, runner instrumentation, MCP/provider wrappers, or another coherent subsystem.
4. Stage 2, report substance review:
   - Once the report exists, inspect the final report text and artifacts, not only the trace. Treat a successful but shallow report as a failure.
   - Look for weak or missing econometrics, backtesting, historical replay/simulation, baseline comparisons, false-positive or miss analysis, forecast diagnostics, uncertainty, citations, source coverage, scenario support, report-vs-execution_summary fidelity, chart quality, frontend chart render-contract failures, and writer/QA preservation.
   - If the trace produces charts, run scripts/audit_report_charts.sh <path-to-report.json> on the generated report. Treat failures as deterministic evidence that chart schema, data keys, numeric values, writer normalization, static validation, chart semantics, or frontend rendering needs improvement.
   - Evaluate chart family choice under the broad governed contract: Cartesian charts for trends/overlays, scatter/bubble for relationships, radar/radialBar for normalized profiles and component scores, treemap/sunburst for hierarchy, funnel for staged filters, and sankey for flows. Prefer variety when it improves the user's decision, but do not penalize a report solely because the strongest chart set is mostly time-series.
   - If no report is generated, explain which Stage 1 issue prevented Stage 2 and plan that blocker first.
5. Produce a decision-complete implementation plan for the build phase:
   - State the root cause and why the planned fix addresses the class of failure instead of the observed wording only.
   - Choose the best coherent fix, including a larger refactor when it is the right engineering answer.
   - Name the files/modules to inspect first, expected public contract changes, tests to run, and any migration or compatibility concerns.
   - State which workaround smells you checked for and whether existing heuristic debt is being removed or intentionally left for a named follow-up signal.
6. FMP MCP is intentionally disabled because no paid FMP plan is available. Do not re-enable FMP or add integrations that require API keys, signup, OAuth, paid plans, or provisioned cloud resources.
7. Combined feature-aware improvement context:
   - This is no longer only a FRED macro smoke loop. It must harden the full research agent after the feature-loop work.
   - Treat the selected user query as a realistic feature acceptance test. The shell loop intentionally rotates across multiple natural prompts to avoid overfitting; patch general agent behavior and report-quality systems rather than tuning to one prompt. The user query should remain natural and should not tell the agent which providers or internal artifact names to use.
   - Infer the expected capabilities from the user's analytical needs: macro cycle analysis should select FRED, direct labor/inflation source checks should select BLS when useful, regional consumer context should select Census, international peer comparison should select World Bank, public-company fundamentals should select SEC EDGAR, and quantitative recession/forecast/scenario/regime work should select local quant code-writing helpers.
   - If the agent answers generically, skips a naturally relevant source/tool family, uses paid/keyed providers, or drops required artifact fields downstream, plan the root-cause component or subsystem fix that caused that miss.
   - Features now in scope include SEC EDGAR company facts, direct BLS public data, Census public data, World Bank indicators, local macro statistics helpers, optional statsmodels/econometrics workflows, composite predictive indicators, scenario/stress testing, recession/regime classification, technical-writer schema handling, QA gates, source/citation coverage, and integration-test behavior.
   - If the trace touches a public no-key integration, improve provider clients, tool docs, source metadata, error handling, mocked tests, and RUN_LIVE_INTEGRATION_TESTS-gated live smoke tests as needed.
   - If the trace touches local analysis, improve quant helper APIs, no-lookahead/mixed-frequency alignment, output schemas, methods_used, forecast/scenario/regime artifacts, fixture-driven integration tests, downstream writer/QA preservation, and common helper extraction for runtime code patterns the quant-developer keeps rewriting.
   - Local quant analysis fixes must keep the helper-library boundary reusable. Do not add prebuilt report generators or tool shortcuts for a specific query family.
   - Do not invent new product areas. Improve the feature families listed above and the agent flow around them.
8. Follow AGENTS.md. Before changes involving the Vercel AI SDK or LangChain DeepAgents, retrieve current documentation as required.
9. In your analysis, use repo tools such as rg/grep/find yourself to inspect the generated trace-digest.md, trace_diagnostics.json, phoenix_spans.jsonl, previous pass summaries, changed files, tests, and stop markers. The shell loop intentionally does not classify traces for you.
10. Final response requirements:
   - Include the generated trace digest path and key artifact paths.
   - Name the trace signal that drove the plan, such as repeated tool loop, slow node, failed handoff, retry churn, or shallow artifact generation.
   - Provide a decision-complete implementation plan: root cause, planned approach, files/modules to inspect first, public contracts, tests, risks, and anti-workaround self-review notes.
   - End with exactly these three machine-readable lines:
     IMPROVE_PLAN_RESULT: plan_found|no_plan|blocked
     IMPROVE_TARGET: <short subsystem name>
     IMPROVE_NEXT_SIGNAL: <one short sentence>

Important:
- Do not loop inside this Codex session.
- Do not use codex resume.
- Do not stop early because of context usage; this script starts a fresh Codex process for the build phase.
- Do not touch secrets or .env files.
- Do not repeat the same patch area as recent passes unless you inspect the latest trace and prove that issue remains.
PROMPT
}

write_improve_build_prompt_file() {
  local prompt_file="$1"
  local recent_context="$2"
  local query_file="$3"
  local plan_output_file="$4"
  local plan_prompt_file="$5"
  local plan_trace_digest="$6"
  local best_fix_policy
  best_fix_policy="$(best_fix_policy_block)"

  cat > "$prompt_file" <<PROMPT
Use the repo-local agent-improver skill.

Phase: improve-build
Loop mode: $LOOP_MODE
Loop focus: $LOOP_FOCUS
Requested loop mode: $REQUESTED_LOOP_MODE
Requested loop focus: $REQUESTED_LOOP_FOCUS

Fresh-context inputs:
- Improve plan summary: $plan_output_file
- Improve plan prompt: $plan_prompt_file
- Improve plan trace digest: ${plan_trace_digest:-unknown}
- Query file: $query_file

$recent_context

$best_fix_policy

Goal:
Implement the best root-cause fix from the improve-plan phase. Preserve or improve the actual agent flow.

Context discipline:
1. Start by reading the improve plan summary, query file, plan trace digest path, and recent pass summaries listed above.
2. Use those inputs to choose the implementation scope. Then inspect only the code, tests, skills, and artifacts needed for that subsystem.
3. Do not rerun the plan phase, do not run a broad new agent investigation, and do not scatter cleanup across unrelated areas.

Implementation policy:
- Treat the plan as the default contract. If inspection proves a different root-cause fix is required, state why and implement the better coherent fix.
- Refactor boldly when the planned root cause is brittle routing, duplicated prompt/tool rules, prompt bloat, unclear ownership, retry churn, or artifact contract drift. Keep the refactor tied to the trace signal.
- Prefer typed fields, structured tool payloads, schema validation, deterministic state, and clear specialist boundaries over prose matching or prompt wording pressure.
- Do not add marker-table routing, broad substring classifiers, or one-off catch phrases to get the current trace green. If an emergency fallback is unavoidable, make it narrow, tested, and document the removal path in the final summary.
- Follow AGENTS.md. Before changes involving the Vercel AI SDK or LangChain DeepAgents, retrieve current documentation as required.

Verification:
1. Run tests relevant to changed behavior.
2. For public no-key HTTP integrations, run mocked unit/contract tests and, when a live smoke test exists, run the relevant RUN_LIVE_INTEGRATION_TESTS=1 test or explain provider/network failure separately.
3. For local analysis features, run fixture-driven integration tests under backend/tests/integration when relevant.
4. For chart/report changes, run scripts/audit_report_charts.sh <path-to-report.json> when a report exists, plus focused backend technical-writer chart tests and frontend chart-contract tests.
5. Keep live tests tiny; do not use paid or credentialed services.
6. If you generate a new post-build trace artifact, include the trace-digest.md path in the final response.

Final response requirements:
- Summarize the root-cause fix, changed files, contract/behavior changes, tests run, and anti-workaround self-review.
- Name the trace signal that drove the implementation.
- State whether Playwright CLI was used, the inspected URL/report path when applicable, key DOM findings, and whether a new post-build trace digest was generated.
- End with exactly these two machine-readable lines:
  IMPROVER_RESULT: patched|no_patch|blocked
  IMPROVER_NEXT_SIGNAL: one short sentence describing what the next run should watch.
PROMPT
}

write_refactor_signal_prompt_file() {
  local prompt_file="$1"
  local recent_context="$2"
  local query="$3"
  local chart_signal_block
  local best_fix_policy
  best_fix_policy="$(best_fix_policy_block)"

  if [[ "$LOOP_FOCUS" == "charts" ]]; then
    chart_signal_block=$(cat <<'PROMPT_BLOCK'
Chart signal:
- This refactor signal came from chart-focused query rotation. Inspect report chart artifacts and run scripts/audit_report_charts.sh <path-to-report.json> if a report exists.
- Treat chart-contract churn, duplicated chart validation logic, bloated chart prompts, repeated chart repair loops, or frontend/report schema drift as eligible refactor targets when the evidence supports it.
PROMPT_BLOCK
)
  else
    chart_signal_block=$(cat <<'PROMPT_BLOCK'
Chart-aware signal:
- If the generated report contains charts, inspect report.json/charts.json and run scripts/audit_report_charts.sh <path-to-report.json> when practical.
- Chart issues are eligible only when they reveal a coherent refactor target rather than a one-off chart fix.
PROMPT_BLOCK
)
  fi

  cat > "$prompt_file" <<PROMPT
Use the repo-local agent-improver skill. Read the compact Refactor Mode section before starting.

Phase: refactor-signal
Loop mode: $LOOP_MODE
Loop focus: $LOOP_FOCUS
Requested loop mode: $REQUESTED_LOOP_MODE
Requested loop focus: $REQUESTED_LOOP_FOCUS

Goal:
Run one fresh agent execution, inspect high-signal trace artifacts and report artifacts, and identify one high-impact refactor target. This phase must not modify code.

$recent_context

$best_fix_policy

$chart_signal_block

Execution:
1. From backend/, run:
   UV_CACHE_DIR=/tmp/uv-cache uv run python tests/runner.py --max-runtime-seconds 2400 --max-tool-calls 300 --max-identical-tool-calls 25 --max-fred-search-calls 100 --max-model-messages 5000 --query "$query"
2. Locate and read the generated outputs/improver-*/trace-digest.md first, then trace_diagnostics.json, phoenix_spans.jsonl, and report artifacts when they exist: report.json, execution_summary.json, charts.json, and code/analysis.py.
3. Inspect recent pass summaries above so the chosen refactor does not blindly repeat a recent patch area.
4. Gather enough code context to choose one coherent cleanup target. Prefer measurable evidence such as bloated files, repeated prompt/tool constants, duplicate validators, large guardrail messages, repeated retry loops, confusing ownership boundaries, or generated artifacts that force the next agent to carry avoidable context.
5. Explicitly connect the target to agent-flow improvement: fewer context-heavy instructions, fewer tool loops, clearer ownership boundaries, smaller prompts/tool errors, easier handoffs, or lower retry churn.
6. Do not edit files, stage changes, or run formatters. This phase is analysis only.

Target selection policy:
- Pick one subsystem, not scattered style cleanup.
- Favor targets where one aggressive but coherent refactor can reduce LOC, complexity, duplication, file bloat, or context pollution while preserving or improving the actual agent flow.
- Avoid pure cosmetic refactors unless they unlock a concrete flow improvement.
- If no safe target is justified by the evidence, say so and explain the missing signal.

Final response requirements:
- Include the generated trace digest path and key artifact paths.
- Name the trace signal that drove the target choice, such as repeated tool loop, slow node, failed handoff, retry churn, or shallow artifact generation.
- Name the recommended refactor target and the exact files/modules the build phase should inspect first.
- Explain the flow evidence, expected cleanup metric, verification plan, and risk.
- End with exactly these three machine-readable lines:
  REFACTOR_SIGNAL_RESULT: target_found|no_target|blocked
  REFACTOR_TARGET: <short subsystem name>
  REFACTOR_NEXT_SIGNAL: <one short sentence>
PROMPT
}

write_refactor_build_prompt_file() {
  local prompt_file="$1"
  local recent_context="$2"
  local query_file="$3"
  local signal_output_file="$4"
  local signal_prompt_file="$5"
  local signal_trace_digest="$6"
  local best_fix_policy
  best_fix_policy="$(best_fix_policy_block)"

  cat > "$prompt_file" <<PROMPT
Use the repo-local agent-improver skill. Read the compact Refactor Mode section before starting.

Phase: refactor-build
Loop mode: $LOOP_MODE
Loop focus: $LOOP_FOCUS
Requested loop mode: $REQUESTED_LOOP_MODE
Requested loop focus: $REQUESTED_LOOP_FOCUS

Fresh-context inputs:
- Signal summary: $signal_output_file
- Signal prompt: $signal_prompt_file
- Signal trace digest: ${signal_trace_digest:-unknown}
- Query file: $query_file

$recent_context

$best_fix_policy

Goal:
Perform one large, coherent cleanup based on the refactor-signal phase. Preserve or improve the actual agent flow.

Context discipline:
1. Start by reading the signal summary, query file, signal trace digest path, and recent pass summaries listed above.
2. Use those inputs to choose the subsystem. Then inspect only the code, tests, skills, and artifacts needed for that subsystem.
3. Do not rerun the signal phase, do not run a broad new agent investigation, and do not scatter cleanup across unrelated areas.

Refactor policy:
- The selected policy is very aggressive. You may split modules, move code, consolidate duplicated rules, delete dead code, reshape file structure, and adjust tests when the flow evidence supports it.
- Choose one coherent subsystem. Examples of acceptable targets include one prompt/skill boundary, one artifact-validation layer, one provider/tool wrapper family, one report/chart contract path, one runner/watchdog logging path, or one duplicated helper cluster.
- Explicitly connect the refactor to agent-flow improvement: fewer context-heavy instructions, fewer tool loops, clearer ownership boundaries, smaller prompts/tool errors, easier handoffs, or lower retry churn.
- Prefer measurable cleanup: lower line count in bloated files, smaller resident prompts or guardrail messages, fewer duplicate constants/tool lists, clearer package/module boundaries, or reduced tests tied to brittle internals when behavior coverage remains.
- For quant-developer or quant helper refactors, preserve the helper-only direction: no canned report builders, no report-specific artifact tools, no query-marker report routing, and no exact report-contract QA gates.
- Avoid pure cosmetic refactors unless they unlock a concrete flow improvement.

Implementation and verification:
1. Patch the chosen subsystem thoroughly enough that the cleanup is meaningful, not a token rename.
2. Preserve public behavior and report/artifact contracts unless the signal proves the contract itself is the problem.
3. Follow AGENTS.md. Before changes involving the Vercel AI SDK or LangChain DeepAgents, retrieve current documentation as required.
4. Run focused verification for the changed behavior. For chart/report changes, run scripts/audit_report_charts.sh <path-to-report.json> when a report artifact is available, plus focused backend/frontend tests as relevant.
5. If you generate new trace artifacts during verification, include the trace-digest.md path in the final response.

Final response requirements:
- Summarize the refactor target, changed files, measurable cleanup, flow improvement, and tests run.
- State whether a new post-refactor trace digest was generated.
- End with exactly these three machine-readable lines:
  REFACTOR_RESULT: patched|no_patch|blocked
  REFACTOR_TARGET: <short subsystem name>
  REFACTOR_NEXT_SIGNAL: <one short sentence>
PROMPT
}

run_codex_phase() {
  local phase_name="$1"
  local output_file="$2"
  local prompt_file="$3"

  set +e
  codex exec \
    --cd "$REPO_ROOT" \
    --sandbox "$CODEX_SANDBOX_MODE" \
    --output-last-message "$output_file" \
    "${CODEX_MODEL_ARGS[@]}" \
    "$(cat "$prompt_file")"
  local codex_exit=$?
  set -e

  printf '\nCodex %s exited with status %s\n' "$phase_name" "$codex_exit"
  printf 'Last Codex summary: %s\n' "$output_file"
  return "$codex_exit"
}

copy_phase_summary() {
  local output_file="$1"
  local summary_file="$2"
  local phase_label="$3"
  local pass_num="$4"

  if [[ -s "$output_file" ]]; then
    cp "$output_file" "$summary_file"
  else
    printf 'Codex did not write a non-empty %s summary for pass %s.\n' "$phase_label" "$pass_num" > "$summary_file"
  fi
}

write_improve_pass_summary() {
  local pass_dir="$1"
  local pass_num="$2"
  local start_time="$3"
  local end_time="$4"
  local plan_exit="$5"
  local build_exit="$6"
  local plan_output_file="$7"
  local build_output_file="$8"
  local plan_trace_digest="$9"
  local post_build_trace_digest="${10}"
  local query="${11}"
  local summary_file="$pass_dir/summary.md"

  copy_phase_summary "$plan_output_file" "$pass_dir/improve-plan-summary.md" "improve-plan" "$pass_num"
  copy_phase_summary "$build_output_file" "$pass_dir/improve-build-summary.md" "improve-build" "$pass_num"

  {
    printf '# Improve Loop Pass %s\n\n' "$pass_num"
    printf 'Loop mode: %s\n' "$LOOP_MODE"
    printf 'Loop focus: %s\n' "$LOOP_FOCUS"
    printf 'Requested loop mode: %s\n' "$REQUESTED_LOOP_MODE"
    printf 'Requested loop focus: %s\n' "$REQUESTED_LOOP_FOCUS"
    printf 'Started: %s\n' "$start_time"
    printf 'Ended: %s\n' "$end_time"
    printf 'Improve plan Codex exit: %s\n' "$plan_exit"
    printf 'Improve build Codex exit: %s\n' "$build_exit"
    printf 'Codex exit: plan=%s build=%s\n' "$plan_exit" "$build_exit"
    printf 'Trace digest: %s\n' "${plan_trace_digest:-unknown}"
    printf 'Plan trace digest: %s\n' "${plan_trace_digest:-unknown}"
    printf 'Latest post-build trace digest: %s\n' "${post_build_trace_digest:-none detected}"
    printf 'Query: %s\n' "$query"
    printf 'Improve plan prompt: %s\n' "$pass_dir/improve-plan-prompt.txt"
    printf 'Improve plan output: %s\n' "$pass_dir/improve-plan-summary.md"
    printf 'Improve build prompt: %s\n' "$pass_dir/improve-build-prompt.txt"
    printf 'Improve build output: %s\n' "$pass_dir/improve-build-summary.md"
    printf 'Codex summary: %s\n' "$pass_dir/improve-build-summary.md"
    printf 'Signal prompt: n/a\n'
    printf 'Signal output: n/a\n'
    printf 'Refactor prompt: n/a\n'
    printf 'Refactor output: n/a\n'
    printf 'Signal trace digest: n/a\n'
    printf 'Latest post-refactor trace digest: n/a\n'
    printf 'Refactor signal Codex exit: n/a\n'
    printf 'Refactor build Codex exit: n/a\n'
    printf '\n## Improve Plan Summary\n\n'
    cat "$pass_dir/improve-plan-summary.md"
    printf '\n## Improve Build Summary\n\n'
    cat "$pass_dir/improve-build-summary.md"
  } > "$summary_file"
}

write_refactor_pass_summary() {
  local pass_dir="$1"
  local pass_num="$2"
  local start_time="$3"
  local end_time="$4"
  local signal_exit="$5"
  local refactor_exit="$6"
  local signal_output_file="$7"
  local refactor_output_file="$8"
  local signal_trace_digest="$9"
  local post_refactor_trace_digest="${10}"
  local query="${11}"
  local summary_file="$pass_dir/summary.md"

  copy_phase_summary "$signal_output_file" "$pass_dir/refactor-signal-summary.md" "refactor-signal" "$pass_num"
  copy_phase_summary "$refactor_output_file" "$pass_dir/refactor-build-summary.md" "refactor-build" "$pass_num"

  {
    printf '# Improve Loop Pass %s\n\n' "$pass_num"
    printf 'Loop mode: %s\n' "$LOOP_MODE"
    printf 'Loop focus: %s\n' "$LOOP_FOCUS"
    printf 'Requested loop mode: %s\n' "$REQUESTED_LOOP_MODE"
    printf 'Requested loop focus: %s\n' "$REQUESTED_LOOP_FOCUS"
    printf 'Started: %s\n' "$start_time"
    printf 'Ended: %s\n' "$end_time"
    printf 'Query: %s\n' "$query"
    printf 'Signal prompt: %s\n' "$pass_dir/refactor-signal-prompt.txt"
    printf 'Signal output: %s\n' "$pass_dir/refactor-signal-summary.md"
    printf 'Refactor prompt: %s\n' "$pass_dir/refactor-build-prompt.txt"
    printf 'Refactor output: %s\n' "$pass_dir/refactor-build-summary.md"
    printf 'Signal trace digest: %s\n' "${signal_trace_digest:-unknown}"
    printf 'Latest post-refactor trace digest: %s\n' "${post_refactor_trace_digest:-none detected}"
    printf 'Refactor signal Codex exit: %s\n' "$signal_exit"
    printf 'Refactor build Codex exit: %s\n' "$refactor_exit"
    printf 'Codex exit: signal=%s refactor=%s\n' "$signal_exit" "$refactor_exit"
    printf '\n## Refactor Signal Summary\n\n'
    cat "$pass_dir/refactor-signal-summary.md"
    printf '\n## Refactor Build Summary\n\n'
    cat "$pass_dir/refactor-build-summary.md"
  } > "$summary_file"
}

update_latest_summary() {
  local pass_files
  mapfile -t pass_files < <(find "$RUN_DIR" -maxdepth 2 -type f -name summary.md 2>/dev/null | sort -V)
  {
    printf '# Codex Improve Loop Summary\n\n'
    printf 'Run: %s\n' "$RUN_ID"
    printf 'Loop mode: %s\n' "$LOOP_MODE"
    printf 'Loop focus: %s\n' "$LOOP_FOCUS"
    printf 'Requested loop mode: %s\n' "$REQUESTED_LOOP_MODE"
    printf 'Requested loop focus: %s\n' "$REQUESTED_LOOP_FOCUS"
    printf 'Run directory: %s\n' "$RUN_DIR"
    printf 'Codex reasoning effort: %s\n' "$CODEX_REASONING_EFFORT"
    printf 'Chart audit render: %s\n' "$CHART_AUDIT_RENDER"
    printf 'Updated: %s\n\n' "$(date -Is)"
    printf '## Passes\n\n'
    local file pass
    for file in "${pass_files[@]}"; do
      pass="$(basename "$(dirname "$file")")"
      printf -- '- %s: summary=%s\n' "$pass" "$file"
    done
    printf '\n## How To Review\n\n'
    printf -- '- Open the newest pass summary and trace digest listed above.\n'
    printf -- '- In improve mode, compare improve-plan and improve-build outputs to confirm the second phase implemented a planned root-cause fix.\n'
    printf -- '- In refactor mode, compare refactor-signal and refactor-build outputs to confirm the second phase started from a fresh Codex process.\n'
    printf -- '- Let the Codex pass inspect trace artifacts itself; this script only preserves paths and metadata.\n'
  } > "$LATEST_SUMMARY"
}

CODEX_MODEL_ARGS=(
  -c "model_reasoning_effort=\"$CODEX_REASONING_EFFORT\""
  -c "plan_mode_reasoning_effort=\"$CODEX_REASONING_EFFORT\""
)
if [[ -n "${CODEX_MODEL:-}" ]]; then
  CODEX_MODEL_ARGS=(--model "$CODEX_MODEL" "${CODEX_MODEL_ARGS[@]}")
fi

ensure_phoenix
verify_phoenix_collection

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
printf 'Loop mode: %s\n' "$LOOP_MODE"
printf 'Loop focus: %s\n' "$LOOP_FOCUS"
printf 'Requested loop mode: %s\n' "$REQUESTED_LOOP_MODE"
printf 'Requested loop focus: %s\n' "$REQUESTED_LOOP_FOCUS"
printf 'Codex reasoning effort: %s\n' "$CODEX_REASONING_EFFORT"
printf 'Chart audit render: %s\n' "$CHART_AUDIT_RENDER"
printf 'Cypress Electron flags: %s\n' "$ELECTRON_EXTRA_LAUNCH_ARGS"
printf 'Phoenix endpoint: %s\n' "$PHOENIX_COLLECTOR_ENDPOINT"
printf 'Phoenix project: %s\n' "$PHOENIX_PROJECT_NAME"
printf 'Latest rollup: %s\n' "$LATEST_SUMMARY"

for i in $(seq "$START_ITER" "$end_iter"); do
  pass_dir="$RUN_DIR/pass-${i}"
  query_file="$pass_dir/query.txt"
  start_time="$(date -Is)"
  recent_context="$(build_recent_context)"
  QUERY="$(select_query "$i")"
  export LOOP_PASS="$i"
  pre_pass_trace_digest="$(latest_trace_digest || true)"
  mkdir -p "$pass_dir"
  printf '%s\n' "$QUERY" > "$query_file"

  if [[ "$LOOP_MODE" == "refactor" ]]; then
    signal_output_file="/tmp/codex-improver-pass-${i}-refactor-signal.md"
    refactor_output_file="/tmp/codex-improver-pass-${i}-refactor-build.md"
    signal_prompt_file="$pass_dir/refactor-signal-prompt.txt"
    refactor_prompt_file="$pass_dir/refactor-build-prompt.txt"

    write_refactor_signal_prompt_file "$signal_prompt_file" "$recent_context" "$QUERY"

    printf '\n=== Codex refactor signal pass %s/%s ===\n' "$i" "$end_iter"
    printf 'Query: %s\n\n' "$QUERY"
    printf 'Signal prompt file: %s\n' "$signal_prompt_file"

    if run_codex_phase "refactor-signal pass $i" "$signal_output_file" "$signal_prompt_file"; then
      signal_exit=0
    else
      signal_exit=$?
    fi

    latest_after_signal="$(latest_trace_digest || true)"
    if [[ -n "$latest_after_signal" && "$latest_after_signal" != "$pre_pass_trace_digest" ]]; then
      signal_trace_digest="$latest_after_signal"
    else
      signal_trace_digest=""
    fi

    write_refactor_build_prompt_file "$refactor_prompt_file" "$recent_context" "$query_file" "$signal_output_file" "$signal_prompt_file" "$signal_trace_digest"

    printf '\n=== Codex refactor build pass %s/%s ===\n' "$i" "$end_iter"
    printf 'Build prompt file: %s\n' "$refactor_prompt_file"

    if [[ -s "$signal_output_file" ]]; then
      if run_codex_phase "refactor-build pass $i" "$refactor_output_file" "$refactor_prompt_file"; then
        refactor_exit=0
      else
        refactor_exit=$?
      fi
    else
      refactor_exit=99
      printf 'Skipped refactor-build because refactor-signal did not write a non-empty summary for pass %s.\n' "$i" > "$refactor_output_file"
      printf '\nSkipping refactor-build pass %s because the signal summary is empty.\n' "$i"
    fi

    latest_after_refactor="$(latest_trace_digest || true)"
    if [[ -n "$latest_after_refactor" && "$latest_after_refactor" != "$latest_after_signal" ]]; then
      post_refactor_trace_digest="$latest_after_refactor"
    else
      post_refactor_trace_digest=""
    fi
    end_time="$(date -Is)"

    write_refactor_pass_summary "$pass_dir" "$i" "$start_time" "$end_time" "$signal_exit" "$refactor_exit" "$signal_output_file" "$refactor_output_file" "$signal_trace_digest" "$post_refactor_trace_digest" "$QUERY"
    update_latest_summary

    printf '\nCodex refactor pass %s exited with signal=%s build=%s\n' "$i" "$signal_exit" "$refactor_exit"
    printf 'Signal summary: %s\n' "$signal_output_file"
    printf 'Refactor summary: %s\n' "$refactor_output_file"
    printf 'Pass summary: %s\n' "$pass_dir/summary.md"
    printf 'Latest rollup: %s\n' "$LATEST_SUMMARY"
    git status --short

    if [[ "$signal_exit" -ne 0 || "$refactor_exit" -ne 0 ]]; then
      consecutive_codex_failures=$((consecutive_codex_failures + 1))
    else
      consecutive_codex_failures=0
    fi

    if [[ ! -s "$signal_output_file" || ! -s "$refactor_output_file" ]]; then
      printf '\nStopping: Codex did not write non-empty refactor phase summaries for pass %s.\n' "$i"
      break
    fi
  else
    plan_output_file="/tmp/codex-improver-pass-${i}-improve-plan.md"
    build_output_file="/tmp/codex-improver-pass-${i}-improve-build.md"
    plan_prompt_file="$pass_dir/improve-plan-prompt.txt"
    build_prompt_file="$pass_dir/improve-build-prompt.txt"
    write_improve_plan_prompt_file "$plan_prompt_file" "$recent_context" "$QUERY"

    printf '\n=== Codex improve plan pass %s/%s ===\n' "$i" "$end_iter"
    printf 'Query: %s\n\n' "$QUERY"
    printf 'Plan prompt file: %s\n' "$plan_prompt_file"

    if run_codex_phase "improve-plan pass $i" "$plan_output_file" "$plan_prompt_file"; then
      plan_exit=0
    else
      plan_exit=$?
    fi

    latest_after_plan="$(latest_trace_digest || true)"
    if [[ -n "$latest_after_plan" && "$latest_after_plan" != "$pre_pass_trace_digest" ]]; then
      plan_trace_digest="$latest_after_plan"
    else
      plan_trace_digest=""
    fi

    write_improve_build_prompt_file "$build_prompt_file" "$recent_context" "$query_file" "$plan_output_file" "$plan_prompt_file" "$plan_trace_digest"

    printf '\n=== Codex improve build pass %s/%s ===\n' "$i" "$end_iter"
    printf 'Build prompt file: %s\n' "$build_prompt_file"

    if [[ -s "$plan_output_file" ]]; then
      if run_codex_phase "improve-build pass $i" "$build_output_file" "$build_prompt_file"; then
        build_exit=0
      else
        build_exit=$?
      fi
    else
      build_exit=99
      printf 'Skipped improve-build because improve-plan did not write a non-empty summary for pass %s.\n' "$i" > "$build_output_file"
      printf '\nSkipping improve-build pass %s because the plan summary is empty.\n' "$i"
    fi

    latest_after_build="$(latest_trace_digest || true)"
    if [[ -n "$latest_after_build" && "$latest_after_build" != "$latest_after_plan" ]]; then
      post_build_trace_digest="$latest_after_build"
    else
      post_build_trace_digest=""
    fi
    end_time="$(date -Is)"

    write_improve_pass_summary "$pass_dir" "$i" "$start_time" "$end_time" "$plan_exit" "$build_exit" "$plan_output_file" "$build_output_file" "$plan_trace_digest" "$post_build_trace_digest" "$QUERY"
    update_latest_summary

    printf '\nCodex improve pass %s exited with plan=%s build=%s\n' "$i" "$plan_exit" "$build_exit"
    printf 'Plan summary: %s\n' "$plan_output_file"
    printf 'Build summary: %s\n' "$build_output_file"
    printf 'Pass summary: %s\n' "$pass_dir/summary.md"
    printf 'Latest rollup: %s\n' "$LATEST_SUMMARY"
    git status --short

    if [[ "$plan_exit" -ne 0 || "$build_exit" -ne 0 ]]; then
      consecutive_codex_failures=$((consecutive_codex_failures + 1))
    else
      consecutive_codex_failures=0
    fi

    if [[ ! -s "$plan_output_file" || ! -s "$build_output_file" ]]; then
      printf '\nStopping: Codex did not write non-empty improve phase summaries for pass %s.\n' "$i"
      break
    fi
  fi

  if [[ "$consecutive_codex_failures" -ge 2 ]]; then
    printf '\nStopping: Codex exited nonzero for %s consecutive passes.\n' "$consecutive_codex_failures"
    break
  fi
done
