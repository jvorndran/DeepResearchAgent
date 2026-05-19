#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/codex_improve_loop.sh [--dry-run] [MAX_ITERS]

Runs the simplified agent improvement loop:
  run -> analyze -> plan -> build -> review -> fix/review until approved

Approved passes are committed and pushed so each iteration builds on the last
approved repository state.

Options:
  --dry-run, --prompt-only  Write stub artifacts and summaries without running the agent or Codex.
  -h, --help               Show this help text.
USAGE
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQUESTED_ITERS="${MAX_ITERS:-}"
DRY_RUN="${DRY_RUN:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run|--prompt-only)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ -z "$REQUESTED_ITERS" ]]; then
        REQUESTED_ITERS="$1"
        shift
      else
        printf 'Unexpected argument: %s\n\n' "$1" >&2
        usage >&2
        exit 2
      fi
      ;;
  esac
done

if [[ -n "${LOOP_MODE:-}" || -n "${LOOP_FOCUS:-}" ]]; then
  {
    printf 'scripts/codex_improve_loop.sh no longer supports LOOP_MODE or LOOP_FOCUS.\n'
    printf 'Use scripts/codex_refactor_loop.sh for dedicated refactor cleanup.\n'
    printf 'Chart checks now run from report artifacts inside the normal improve loop.\n'
  } >&2
  exit 2
fi

MAX_ITERS="${REQUESTED_ITERS:-5}"
START_ITER="${START_ITER:-1}"
MAX_FIX_ATTEMPTS="${MAX_FIX_ATTEMPTS:-3}"
CODEX_SANDBOX_MODE="${CODEX_SANDBOX_MODE:-danger-full-access}"
CODEX_REASONING_EFFORT="${CODEX_REASONING_EFFORT:-xhigh}"
LOG_ROOT="${LOG_ROOT:-$REPO_ROOT/logs/improve-loop}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
RUN_DIR="$LOG_ROOT/runs/$RUN_ID"
LATEST_SUMMARY="$LOG_ROOT/latest-summary.md"
MEMORY_FILE="$LOG_ROOT/memory.md"
QUERY_FILE="$REPO_ROOT/scripts/improve_loop/queries.txt"
PROMPT_DIR="$REPO_ROOT/scripts/improve_loop/prompts"

RUNNER_MAX_RUNTIME_SECONDS="${RUNNER_MAX_RUNTIME_SECONDS:-2400}"
RUNNER_MAX_TOOL_CALLS="${RUNNER_MAX_TOOL_CALLS:-300}"
RUNNER_MAX_IDENTICAL_TOOL_CALLS="${RUNNER_MAX_IDENTICAL_TOOL_CALLS:-25}"
RUNNER_MAX_FRED_SEARCH_CALLS="${RUNNER_MAX_FRED_SEARCH_CALLS:-100}"
RUNNER_MAX_MODEL_MESSAGES="${RUNNER_MAX_MODEL_MESSAGES:-5000}"

IMPROVE_LOOP_AUTO_COMMIT="${IMPROVE_LOOP_AUTO_COMMIT:-1}"
IMPROVE_LOOP_AUTO_PUSH="${IMPROVE_LOOP_AUTO_PUSH:-1}"
IMPROVE_LOOP_GIT_REMOTE="${IMPROVE_LOOP_GIT_REMOTE:-origin}"
IMPROVE_LOOP_STOP_ON_DIRTY_UNAPPROVED="${IMPROVE_LOOP_STOP_ON_DIRTY_UNAPPROVED:-1}"

if [[ -n "${PYTHON:-}" ]]; then
  PYTHON_BIN="$PYTHON"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  PYTHON_BIN="python3"
fi

for value_name in MAX_ITERS START_ITER; do
  value="${!value_name}"
  if ! [[ "$value" =~ ^[0-9]+$ ]] || [[ "$value" -lt 1 ]]; then
    printf '%s must be a positive integer, got %s\n' "$value_name" "$value" >&2
    exit 2
  fi
done

if ! [[ "$MAX_FIX_ATTEMPTS" =~ ^[0-9]+$ ]]; then
  printf 'MAX_FIX_ATTEMPTS must be a non-negative integer, got %s\n' "$MAX_FIX_ATTEMPTS" >&2
  exit 2
fi

CODEX_MODEL_ARGS=(
  -c "model_reasoning_effort=\"$CODEX_REASONING_EFFORT\""
  -c "plan_mode_reasoning_effort=\"$CODEX_REASONING_EFFORT\""
)
if [[ -n "${CODEX_MODEL:-}" ]]; then
  CODEX_MODEL_ARGS=(--model "$CODEX_MODEL" "${CODEX_MODEL_ARGS[@]}")
fi

cd "$REPO_ROOT"
CURRENT_GIT_BRANCH="$(git branch --show-current 2>/dev/null || true)"
if [[ -z "$CURRENT_GIT_BRANCH" ]]; then
  printf 'Cannot auto-commit improve loop passes from detached HEAD. Check out a branch first.\n' >&2
  exit 2
fi
mkdir -p "$RUN_DIR"

require_loop_files() {
  local missing=0
  local template
  [[ -s "$QUERY_FILE" ]] || { printf 'Missing query file: %s\n' "$QUERY_FILE" >&2; missing=1; }
  for template in analyze plan build review fix; do
    [[ -s "$PROMPT_DIR/$template.md" ]] || {
      printf 'Missing prompt template: %s\n' "$PROMPT_DIR/$template.md" >&2
      missing=1
    }
  done
  [[ "$missing" -eq 0 ]] || exit 2
}

select_query() {
  local pass_num="$1"
  local -a queries
  mapfile -t queries < <(awk 'NF && $1 !~ /^#/ {print}' "$QUERY_FILE")
  if [[ "${#queries[@]}" -eq 0 ]]; then
    printf 'No runnable queries found in %s\n' "$QUERY_FILE" >&2
    exit 2
  fi
  local index=$(( (pass_num - 1) % ${#queries[@]} ))
  printf '%s' "${queries[$index]}"
}

summary_value() {
  local key="$1"
  local file="$2"
  [[ -s "$file" ]] || return 0
  awk -v key="$key" '
    {
      line = $0
      sub(/\r$/, "", line)
      sub(/^[[:space:]]*/, "", line)
      sub(/^[-*][[:space:]]+/, "", line)
      prefix = key ":"
      if (index(line, prefix) == 1) {
        value = substr(line, length(prefix) + 1)
        sub(/^[[:space:]]*/, "", value)
        print value
        exit
      }
    }
  ' "$file"
}

json_field() {
  local file="$1"
  local dotted_key="$2"
  local default="${3:-}"
  [[ -s "$file" ]] || { printf '%s' "$default"; return 0; }
  "$PYTHON_BIN" - "$file" "$dotted_key" "$default" <<'PY'
import json
import sys

path, dotted_key, default = sys.argv[1:4]
try:
    data = json.loads(open(path, encoding="utf-8").read())
except Exception:
    print(default, end="")
    raise SystemExit(0)

value = data
for part in dotted_key.split("."):
    if isinstance(value, dict) and part in value:
        value = value[part]
    else:
        print(default, end="")
        raise SystemExit(0)

if value is None:
    print(default, end="")
elif isinstance(value, (dict, list)):
    print(json.dumps(value, sort_keys=True), end="")
else:
    print(str(value), end="")
PY
}

json_artifact_lines() {
  local file="$1"
  [[ -s "$file" ]] || { printf -- '- none\n'; return 0; }
  "$PYTHON_BIN" - "$file" <<'PY'
import json
import sys

try:
    data = json.loads(open(sys.argv[1], encoding="utf-8").read())
except Exception:
    print("- none")
    raise SystemExit(0)

artifacts = data.get("artifact_paths") or {}
if not artifacts:
    print("- none")
else:
    for key, value in sorted(artifacts.items()):
        print(f"- {key}: {value}")
PY
}

resolve_backend_path() {
  local path="$1"
  [[ -n "$path" && "$path" != "unknown" ]] || return 0
  case "$path" in
    /*)
      printf '%s' "$path"
      ;;
    backend/*)
      printf '%s/%s' "$REPO_ROOT" "$path"
      ;;
    *)
      printf '%s/%s' "$REPO_ROOT/backend" "$path"
      ;;
  esac
}

latest_trace_digest() {
  find "$REPO_ROOT/backend/outputs" -maxdepth 2 -type f -name trace-digest.md -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr \
    | awk 'NR==1 {print $2}'
}

extract_trace_digest_from_log() {
  local log_file="$1"
  [[ -s "$log_file" ]] || return 0
  awk -F'Trace digest: ' '/Trace digest:/ {path=$2} END {gsub(/\r/, "", path); print path}' "$log_file"
}

ensure_memory() {
  mkdir -p "$(dirname "$MEMORY_FILE")"
  if [[ ! -f "$MEMORY_FILE" ]]; then
    cat > "$MEMORY_FILE" <<'MEMORY'
# Improve Loop Memory

## Active Recurring Failure Signals
- none

## Last 10 Approved Targets / Files / Tests
- none

## Blocked Targets Needing Human Attention
- none

## Known Environment Blockers
- none

## Next Signal To Observe
- none
MEMORY
  fi
}

memory_lines() {
  local prefix="$1"
  local limit="$2"
  grep -E "^- ${prefix}:" "$MEMORY_FILE" 2>/dev/null | tail -n "$limit" || true
}

emit_or_none() {
  local lines="$1"
  if [[ -n "$lines" ]]; then
    printf '%s\n' "$lines"
  else
    printf -- '- none\n'
  fi
}

update_memory() {
  local pass_num="$1"
  local pass_dir="$2"
  local run_summary="$3"
  local analysis_summary="$4"
  local build_summary="$5"
  local final_review_summary="$6"

  local target files tests next_signal run_signal run_trace run_result review_result build_result
  target="$(summary_value "IMPROVE_TARGET" "$analysis_summary")"
  files="$(summary_value "IMPROVE_FILES_CHANGED" "$build_summary")"
  tests="$(summary_value "IMPROVE_TESTS_RUN" "$build_summary")"
  next_signal="$(summary_value "IMPROVE_NEXT_SIGNAL" "$final_review_summary")"
  [[ -n "$next_signal" ]] || next_signal="$(summary_value "IMPROVE_NEXT_SIGNAL" "$build_summary")"
  [[ -n "$next_signal" ]] || next_signal="$(summary_value "IMPROVE_NEXT_SIGNAL" "$analysis_summary")"
  run_signal="$(summary_value "RUN_PRIMARY_SIGNAL" "$run_summary")"
  run_trace="$(summary_value "RUN_TRACE_DIGEST" "$run_summary")"
  run_result="$(summary_value "RUN_RESULT" "$run_summary")"
  review_result="$(summary_value "IMPROVE_REVIEW_RESULT" "$final_review_summary")"
  build_result="$(summary_value "IMPROVER_RESULT" "$build_summary")"

  local old_signals old_approved old_blocked old_env
  old_signals="$(memory_lines "signal" 5)"
  old_approved="$(memory_lines "approved" 10)"
  old_blocked="$(memory_lines "blocked" 10)"
  old_env="$(memory_lines "env" 5)"

  local new_signal=""
  if [[ -n "$run_signal" && "$run_signal" != "unknown" ]]; then
    new_signal="- signal: ${run_signal} (trace=${run_trace:-unknown}, pass=${pass_num})"
  fi

  local new_approved=""
  if [[ "$review_result" == "approved" ]]; then
    new_approved="- approved: run=$RUN_ID pass=$pass_num target=${target:-unknown} files=${files:-see-build-summary} tests=${tests:-see-build-summary} summary=$pass_dir/summary.md"
  fi

  local new_blocked=""
  if [[ "$review_result" == "blocked" || "$build_result" == "blocked" ]]; then
    new_blocked="- blocked: run=$RUN_ID pass=$pass_num target=${target:-unknown} summary=$pass_dir/summary.md"
  fi

  local new_env=""
  if [[ "$run_result" == "failed" ]]; then
    new_env="- env: agent run failed in run=$RUN_ID pass=$pass_num summary=$run_summary"
  fi

  local approved_lines blocked_lines env_lines signal_lines
  signal_lines="$(printf '%s\n%s\n' "$old_signals" "$new_signal" | sed '/^[[:space:]]*$/d' | tail -n 5)"
  approved_lines="$(printf '%s\n%s\n' "$old_approved" "$new_approved" | sed '/^[[:space:]]*$/d' | tail -n 10)"
  blocked_lines="$(printf '%s\n%s\n' "$old_blocked" "$new_blocked" | sed '/^[[:space:]]*$/d' | tail -n 10)"
  env_lines="$(printf '%s\n%s\n' "$old_env" "$new_env" | sed '/^[[:space:]]*$/d' | tail -n 5)"

  {
    printf '# Improve Loop Memory\n\n'
    printf '## Active Recurring Failure Signals\n'
    emit_or_none "$signal_lines"
    printf '\n## Last 10 Approved Targets / Files / Tests\n'
    emit_or_none "$approved_lines"
    printf '\n## Blocked Targets Needing Human Attention\n'
    emit_or_none "$blocked_lines"
    printf '\n## Known Environment Blockers\n'
    emit_or_none "$env_lines"
    printf '\n## Next Signal To Observe\n'
    if [[ -n "$next_signal" ]]; then
      printf -- '- next: %s\n' "$next_signal"
    else
      printf -- '- none\n'
    fi
  } > "$MEMORY_FILE"
}

write_dry_run_artifacts() {
  local pass_dir="$1"
  local query_file="$2"
  local artifact_dir="$pass_dir/run-artifacts"
  mkdir -p "$artifact_dir"
  cat > "$artifact_dir/phoenix_spans.jsonl" <<'JSONL'
{"name":"runner.job","attributes":{"event_type":"job","job_id":"dry-run"}}
JSONL
  cat > "$artifact_dir/trace_diagnostics.json" <<JSON
{
  "artifact_paths": {},
  "duration_seconds": 0.0,
  "job_id": "dry-run",
  "primary_trace_signal": "dry-run signal",
  "span_count": 1,
  "status": "COMPLETED",
  "stop_reason": null,
  "trace_artifact_paths": {
    "phoenix_spans_jsonl": "$artifact_dir/phoenix_spans.jsonl",
    "runner_status_json": "$artifact_dir/runner_status.json",
    "trace_diagnostics_json": "$artifact_dir/trace_diagnostics.json",
    "trace_digest_md": "$artifact_dir/trace-digest.md"
  }
}
JSON
  cat > "$artifact_dir/runner_status.json" <<JSON
{
  "artifact_paths": {},
  "duration_seconds": 0.0,
  "job_id": "dry-run",
  "query": "$(sed 's/"/\\"/g' "$query_file")",
  "status": "COMPLETED",
  "stop_reason": null,
  "trace_artifacts": {
    "phoenix_spans_jsonl": "$artifact_dir/phoenix_spans.jsonl",
    "runner_status_json": "$artifact_dir/runner_status.json",
    "trace_diagnostics_json": "$artifact_dir/trace_diagnostics.json",
    "trace_digest_md": "$artifact_dir/trace-digest.md"
  }
}
JSON
  cat > "$artifact_dir/trace-digest.md" <<DIGEST
# Trace Digest: dry-run

- Status: COMPLETED
- Primary trace signal: dry-run signal
- Stop reason: none

## Trace Artifacts
- trace_digest_md: $artifact_dir/trace-digest.md
- trace_diagnostics_json: $artifact_dir/trace_diagnostics.json
- runner_status_json: $artifact_dir/runner_status.json

## Report Artifacts
- none discovered
DIGEST
  printf 'Dry run run phase\nTrace digest: %s\nCOMPLETED in 0.00s\n' "$artifact_dir/trace-digest.md" > "$pass_dir/run.log"
}

write_run_summary() {
  local pass_dir="$1"
  local query_file="$2"
  local runner_exit="$3"
  local trace_digest="$4"

  local trace_dir diagnostics_path status_path spans_path run_result runner_status primary_signal
  trace_dir=""
  if [[ -n "$trace_digest" ]]; then
    trace_dir="$(dirname "$trace_digest")"
  fi
  if [[ -n "$trace_dir" ]]; then
    diagnostics_path="$trace_dir/trace_diagnostics.json"
    status_path="$trace_dir/runner_status.json"
    spans_path="$trace_dir/phoenix_spans.jsonl"
  else
    diagnostics_path=""
    status_path=""
    spans_path=""
  fi

  if [[ -s "$trace_digest" && -s "$diagnostics_path" && -s "$status_path" ]]; then
    run_result="completed"
  else
    run_result="failed"
  fi
  runner_status="$(json_field "$status_path" "status" "unknown")"
  primary_signal="$(json_field "$diagnostics_path" "primary_trace_signal" "unknown")"

  {
    printf '# Run Summary\n\n'
    printf 'RUN_RESULT: %s\n' "$run_result"
    printf 'RUN_TRACE_DIGEST: %s\n' "${trace_digest:-unknown}"
    printf 'RUN_TRACE_DIAGNOSTICS: %s\n' "${diagnostics_path:-unknown}"
    printf 'RUN_RUNNER_STATUS: %s\n' "$runner_status"
    printf 'RUN_RUNNER_STATUS_JSON: %s\n' "${status_path:-unknown}"
    printf 'RUN_PHOENIX_SPANS: %s\n' "${spans_path:-unknown}"
    printf 'RUN_PRIMARY_SIGNAL: %s\n' "$primary_signal"
    printf 'RUN_RUNNER_EXIT: %s\n' "$runner_exit"
    printf 'RUN_REPORT_JSON: %s\n' "$(json_field "$status_path" "artifact_paths.report_json" "none")"
    printf 'RUN_EXECUTION_SUMMARY_JSON: %s\n' "$(json_field "$status_path" "artifact_paths.execution_summary_json" "none")"
    printf 'RUN_CHARTS_JSON: %s\n' "$(json_field "$status_path" "artifact_paths.charts_json" "none")"
    printf 'RUN_ANALYSIS_PY: %s\n' "$(json_field "$status_path" "artifact_paths.analysis_py" "none")"
    printf 'Query file: %s\n' "$query_file"
    printf 'Run log: %s\n' "$pass_dir/run.log"
    printf 'Runner stop policy: full agent run; tool/model budgets are not stop conditions.\n'
    printf '\n## Report Artifact Paths\n'
    json_artifact_lines "$status_path"
  } > "$pass_dir/run-summary.md"
}

run_agent_phase() {
  local pass_dir="$1"
  local query_file="$2"
  local pre_run_trace="$3"
  local query
  query="$(< "$query_file")"

  if [[ "$DRY_RUN" == "1" ]]; then
    write_dry_run_artifacts "$pass_dir" "$query_file"
    write_run_summary "$pass_dir" "$query_file" 0 "$pass_dir/run-artifacts/trace-digest.md"
    return 0
  fi

  set +e
  (
    cd "$REPO_ROOT/backend"
    UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}" uv run python tests/runner.py \
      --max-runtime-seconds "$RUNNER_MAX_RUNTIME_SECONDS" \
      --max-tool-calls "$RUNNER_MAX_TOOL_CALLS" \
      --max-identical-tool-calls "$RUNNER_MAX_IDENTICAL_TOOL_CALLS" \
      --max-fred-search-calls "$RUNNER_MAX_FRED_SEARCH_CALLS" \
      --max-model-messages "$RUNNER_MAX_MODEL_MESSAGES" \
      --query "$query"
  ) 2>&1 | tee "$pass_dir/run.log"
  local runner_exit=${PIPESTATUS[0]}
  set -e

  local trace_digest raw_digest latest_after
  raw_digest="$(extract_trace_digest_from_log "$pass_dir/run.log")"
  trace_digest="$(resolve_backend_path "$raw_digest")"
  if [[ ! -s "$trace_digest" ]]; then
    latest_after="$(latest_trace_digest || true)"
    if [[ -n "$latest_after" && "$latest_after" != "$pre_run_trace" ]]; then
      trace_digest="$latest_after"
    fi
  fi
  write_run_summary "$pass_dir" "$query_file" "$runner_exit" "$trace_digest"
  return 0
}

write_prompt() {
  local phase="$1"
  local output_file="$2"
  local pass_dir="$3"
  local template="$PROMPT_DIR/$phase.md"

  {
    printf '# Phase Context\n\n'
    printf -- '- Repository root: %s\n' "$REPO_ROOT"
    printf -- '- Pass directory: %s\n' "$pass_dir"
    printf -- '- Memory path: %s\n' "$MEMORY_FILE"
    printf '\nUse files from the pass directory. Do not expect artifact contents in this prompt.\n'
    printf 'The run summary is the artifact index; read it to find trace, diagnostics, runner status, report, chart, and analysis paths.\n'
    printf '\n## Files To Inspect\n\n'
    case "$phase" in
      analyze)
        printf -- '- `query.txt`\n'
        printf -- '- `run-summary.md`\n'
        printf -- '- `run.log` only when the summary is insufficient\n'
        printf -- '- artifact paths listed inside `run-summary.md`\n'
        ;;
      plan)
        printf -- '- `analysis-summary.md`\n'
        printf -- '- `run-summary.md`\n'
        printf -- '- artifact paths listed inside `run-summary.md` only as needed\n'
        printf -- '- relevant source files and nearby tests\n'
        ;;
      build)
        printf -- '- `plan-summary.md`\n'
        printf -- '- `analysis-summary.md`\n'
        printf -- '- `run-summary.md`\n'
        printf -- '- artifact paths listed inside `run-summary.md` only as needed\n'
        ;;
      review)
        printf -- '- `analysis-summary.md`\n'
        printf -- '- `plan-summary.md`\n'
        printf -- '- `build-summary.md` and the latest `fix-*-summary.md` if present\n'
        printf -- '- `current-diff.patch`\n'
        printf -- '- `current-status.txt`\n'
        printf -- '- `test-evidence.md`\n'
        ;;
      fix)
        printf -- '- latest `review-*-summary.md`\n'
        printf -- '- `plan-summary.md`\n'
        printf -- '- `analysis-summary.md`\n'
        printf -- '- `current-diff.patch`\n'
        printf -- '- `current-status.txt`\n'
        printf -- '- `test-evidence.md`\n'
        ;;
    esac
    printf '\n# Phase Instructions\n\n'
    cat "$template"
  } > "$output_file"
}

dry_run_review_result() {
  local attempt="$1"
  local sequence="${DRY_RUN_REVIEW_SEQUENCE:-changes_requested,approved}"
  local -a results
  IFS=',' read -r -a results <<< "$sequence"
  local index=$((attempt - 1))
  if [[ "$index" -ge "${#results[@]}" ]]; then
    index=$((${#results[@]} - 1))
  fi
  printf '%s' "${results[$index]}"
}

dry_run_phase_summary() {
  local phase="$1"
  local output_file="$2"
  local attempt="${3:-1}"
  case "$phase" in
    analyze)
      cat > "$output_file" <<'SUMMARY'
IMPROVE_ANALYSIS_RESULT: analysis_complete
IMPROVE_TARGET: dry-run-target
IMPROVE_QUALITY_CRITERIA: dry-run criteria
IMPROVE_ANALYSIS_FILES: none
IMPROVE_NEXT_SIGNAL: Dry-run review should request one fix, then approve.
SUMMARY
      ;;
    plan)
      cat > "$output_file" <<'SUMMARY'
IMPROVE_PLAN_RESULT: planned
IMPROVE_TARGET: dry-run-target
IMPROVE_PLAN_FILES: none
IMPROVE_PLAN_TESTS: none
IMPROVE_NEXT_SIGNAL: Dry-run build should implement the planned stub target.
SUMMARY
      ;;
    build)
      cat > "$output_file" <<'SUMMARY'
IMPROVER_RESULT: patched
IMPROVE_TARGET: dry-run-target
IMPROVE_FILES_CHANGED: none
IMPROVE_TESTS_RUN: none
IMPROVE_NEXT_SIGNAL: Dry-run review should inspect the stub diff.
SUMMARY
      ;;
    review)
      local result
      result="$(dry_run_review_result "$attempt")"
      cat > "$output_file" <<SUMMARY
IMPROVE_REVIEW_RESULT: $result
IMPROVE_REVIEW_FINDINGS: dry-run finding for attempt $attempt
IMPROVE_NEXT_SIGNAL: Dry-run review attempt $attempt returned $result.
SUMMARY
      ;;
    fix)
      cat > "$output_file" <<'SUMMARY'
IMPROVE_FIX_RESULT: patched
IMPROVE_TARGET: dry-run-target
IMPROVE_FILES_CHANGED: none
IMPROVE_TESTS_RUN: none
IMPROVE_NEXT_SIGNAL: Dry-run fix summary is ready for re-review.
SUMMARY
      ;;
  esac
}

run_codex_phase() {
  local phase="$1"
  local output_file="$2"
  local prompt_file="$3"
  local attempt="${4:-1}"

  if [[ "$DRY_RUN" == "1" ]]; then
    printf 'Dry run: writing %s summary to %s\n' "$phase" "$output_file"
    dry_run_phase_summary "$phase" "$output_file" "$attempt"
    return 0
  fi

  set +e
  codex exec \
    --cd "$REPO_ROOT" \
    --sandbox "$CODEX_SANDBOX_MODE" \
    --output-last-message "$output_file" \
    "${CODEX_MODEL_ARGS[@]}" \
    "$(cat "$prompt_file")"
  local status=$?
  set -e
  printf 'Codex %s exited with status %s; summary: %s\n' "$phase" "$status" "$output_file"
  return "$status"
}

write_skipped_summary() {
  local phase="$1"
  local output_file="$2"
  local reason="$3"
  case "$phase" in
    plan)
      {
        printf 'IMPROVE_PLAN_RESULT: blocked\n'
        printf 'IMPROVE_TARGET: unknown\n'
        printf 'IMPROVE_PLAN_FILES: unknown\n'
        printf 'IMPROVE_PLAN_TESTS: unknown\n'
        printf 'IMPROVE_NEXT_SIGNAL: %s\n' "$reason"
      } > "$output_file"
      ;;
    build)
      {
        printf 'IMPROVER_RESULT: blocked\n'
        printf 'IMPROVE_TARGET: unknown\n'
        printf 'IMPROVE_NEXT_SIGNAL: %s\n' "$reason"
      } > "$output_file"
      ;;
    review)
      {
        printf 'IMPROVE_REVIEW_RESULT: blocked\n'
        printf 'IMPROVE_REVIEW_FINDINGS: %s\n' "$reason"
        printf 'IMPROVE_NEXT_SIGNAL: %s\n' "$reason"
      } > "$output_file"
      ;;
    fix)
      {
        printf 'IMPROVE_FIX_RESULT: not_run\n'
        printf 'IMPROVE_NEXT_SIGNAL: %s\n' "$reason"
      } > "$output_file"
      ;;
  esac
}

write_current_diff() {
  local pass_dir="$1"
  git diff --no-ext-diff -- . > "$pass_dir/current-diff.patch" || true
  git status --short > "$pass_dir/current-status.txt" || true
}

write_test_evidence() {
  local output_file="$1"
  shift
  {
    printf '# Test Evidence\n\n'
    local summary tests
    for summary in "$@"; do
      [[ -s "$summary" ]] || continue
      tests="$(summary_value "IMPROVE_TESTS_RUN" "$summary")"
      [[ -n "$tests" ]] || tests="see phase summary"
      printf -- '- Summary: %s\n' "$summary"
      printf '  Tests: %s\n' "$tests"
    done
  } > "$output_file"
}

git_status_porcelain() {
  git status --porcelain --untracked-files=normal -- .
}

has_git_changes() {
  [[ -n "$(git_status_porcelain)" ]]
}

write_git_finalization() {
  local output_file="$1"
  local status="$2"
  local detail="$3"
  local commit_sha="${4:-}"

  {
    printf 'status: %s\n' "$status"
    printf 'detail: %s\n' "$detail"
    printf 'remote: %s\n' "$IMPROVE_LOOP_GIT_REMOTE"
    printf 'branch: %s\n' "$CURRENT_GIT_BRANCH"
    if [[ -n "$commit_sha" ]]; then
      printf 'commit: %s\n' "$commit_sha"
    fi
  } > "$output_file"
}

commit_and_push_pass() {
  local pass_num="$1"
  local pass_dir="$2"

  if [[ "$DRY_RUN" == "1" || "$IMPROVE_LOOP_AUTO_COMMIT" != "1" ]]; then
    write_git_finalization "$pass_dir/git-finalization.txt" "skipped" "Git auto-commit disabled for this run."
    return 0
  fi

  if ! has_git_changes; then
    write_git_finalization "$pass_dir/git-finalization.txt" "skipped" "No repository changes to commit."
    printf 'No repository changes to commit for approved pass %s.\n' "$pass_num"
    return 0
  fi

  local target tests title body commit_sha
  target="$(summary_value "IMPROVE_TARGET" "$pass_dir/analysis-summary.md")"
  [[ -n "$target" ]] || target="approved improvement"
  target="${target//$'\n'/ }"
  tests="$(summary_value "IMPROVE_TESTS_RUN" "$pass_dir/build-summary.md")"
  [[ -n "$tests" ]] || tests="see pass summary"

  title="codex improve pass ${pass_num}: ${target}"
  body="$(cat <<BODY
Run: $RUN_ID
Pass: $pass_num
Target: $target
Summary: $pass_dir/summary.md
Tests: $tests
BODY
)"

  git add -A -- .
  if git diff --cached --quiet -- .; then
    write_git_finalization "$pass_dir/git-finalization.txt" "skipped" "No staged changes after git add."
    printf 'No staged changes to commit for approved pass %s.\n' "$pass_num"
    return 0
  fi

  git commit -m "$title" -m "$body"
  commit_sha="$(git rev-parse HEAD)"
  printf '%s\n' "$commit_sha" > "$pass_dir/git-commit.txt"

  if [[ "$IMPROVE_LOOP_AUTO_PUSH" == "1" ]]; then
    git push "$IMPROVE_LOOP_GIT_REMOTE" "HEAD:$CURRENT_GIT_BRANCH"
    write_git_finalization "$pass_dir/git-finalization.txt" "pushed" "Committed and pushed approved pass." "$commit_sha"
    printf 'Committed and pushed approved pass %s: %s\n' "$pass_num" "$commit_sha"
  else
    write_git_finalization "$pass_dir/git-finalization.txt" "committed" "Committed approved pass; push disabled." "$commit_sha"
    printf 'Committed approved pass %s without push: %s\n' "$pass_num" "$commit_sha"
  fi
}

finalize_git_for_pass() {
  local pass_num="$1"
  local pass_dir="$2"
  local final_review_result="$3"

  if [[ "$final_review_result" == "approved" ]]; then
    commit_and_push_pass "$pass_num" "$pass_dir"
    return 0
  fi

  write_git_finalization "$pass_dir/git-finalization.txt" "skipped" "Pass was not approved; no commit attempted."
  if [[ "$IMPROVE_LOOP_STOP_ON_DIRTY_UNAPPROVED" == "1" ]] && has_git_changes; then
    {
      printf 'Pass %s ended with review result %s and left uncommitted changes.\n' "$pass_num" "$final_review_result"
      printf 'Stopping before the next pass so unapproved work is not overwritten or built upon.\n'
      printf 'Inspect: %s/current-diff.patch\n' "$pass_dir"
    } >&2
    return 1
  fi
}

write_pass_summary() {
  local pass_dir="$1"
  local pass_num="$2"
  local started="$3"
  local ended="$4"
  local final_review_summary="$5"
  local final_review_result="$6"
  local fix_attempts="$7"

  {
    printf '# Improve Loop Pass %s\n\n' "$pass_num"
    printf 'Started: %s\n' "$started"
    printf 'Ended: %s\n' "$ended"
    printf 'Run: %s\n' "$RUN_ID"
    printf 'Run directory: %s\n' "$RUN_DIR"
    printf 'Memory: %s\n' "$MEMORY_FILE"
    printf 'Query file: %s\n' "$pass_dir/query.txt"
    printf 'Final review result: %s\n' "$final_review_result"
    printf 'Fix attempts: %s\n' "$fix_attempts"
    printf 'RUN_TRACE_DIGEST: %s\n' "$(summary_value "RUN_TRACE_DIGEST" "$pass_dir/run-summary.md")"
    printf 'IMPROVE_ANALYSIS_RESULT: %s\n' "$(summary_value "IMPROVE_ANALYSIS_RESULT" "$pass_dir/analysis-summary.md")"
    printf 'IMPROVE_TARGET: %s\n' "$(summary_value "IMPROVE_TARGET" "$pass_dir/analysis-summary.md")"
    printf 'IMPROVE_PLAN_RESULT: %s\n' "$(summary_value "IMPROVE_PLAN_RESULT" "$pass_dir/plan-summary.md")"
    printf 'IMPROVER_RESULT: %s\n' "$(summary_value "IMPROVER_RESULT" "$pass_dir/build-summary.md")"
    printf 'IMPROVE_REVIEW_RESULT: %s\n' "$final_review_result"
    if [[ -s "$pass_dir/fix-${fix_attempts}-summary.md" ]]; then
      printf 'IMPROVE_FIX_RESULT: %s\n' "$(summary_value "IMPROVE_FIX_RESULT" "$pass_dir/fix-${fix_attempts}-summary.md")"
    else
      printf 'IMPROVE_FIX_RESULT: not_run\n'
    fi
    printf 'IMPROVE_NEXT_SIGNAL: %s\n' "$(summary_value "IMPROVE_NEXT_SIGNAL" "$final_review_summary")"
    printf '\n## Artifact Paths\n\n'
    printf -- '- Run summary: %s\n' "$pass_dir/run-summary.md"
    printf -- '- Run log: %s\n' "$pass_dir/run.log"
    printf -- '- Analysis prompt: %s\n' "$pass_dir/analysis-prompt.md"
    printf -- '- Analysis summary: %s\n' "$pass_dir/analysis-summary.md"
    printf -- '- Plan prompt: %s\n' "$pass_dir/plan-prompt.md"
    printf -- '- Plan summary: %s\n' "$pass_dir/plan-summary.md"
    printf -- '- Build prompt: %s\n' "$pass_dir/build-prompt.md"
    printf -- '- Build summary: %s\n' "$pass_dir/build-summary.md"
    printf -- '- Current diff: %s\n' "$pass_dir/current-diff.patch"
    printf -- '- Current status: %s\n' "$pass_dir/current-status.txt"
    printf -- '- Test evidence: %s\n' "$pass_dir/test-evidence.md"
    printf '\n## Run Summary\n\n'
    cat "$pass_dir/run-summary.md"
    printf '\n## Analysis Summary\n\n'
    cat "$pass_dir/analysis-summary.md"
    printf '\n## Plan Summary\n\n'
    cat "$pass_dir/plan-summary.md"
    printf '\n## Build Summary\n\n'
    cat "$pass_dir/build-summary.md"
    local file
    for file in "$pass_dir"/review-*-summary.md "$pass_dir"/fix-*-summary.md; do
      [[ -s "$file" ]] || continue
      printf '\n## %s\n\n' "$(basename "$file" .md)"
      cat "$file"
    done
  } > "$pass_dir/summary.md"
}

update_latest_summary() {
  local pass_files
  mapfile -t pass_files < <(find "$RUN_DIR" -maxdepth 2 -type f -name summary.md 2>/dev/null | sort -V)
  {
    printf '# Codex Improve Loop Summary\n\n'
    printf 'Run: %s\n' "$RUN_ID"
    printf 'Run directory: %s\n' "$RUN_DIR"
    printf 'Memory: %s\n' "$MEMORY_FILE"
    printf 'Codex reasoning effort: %s\n' "$CODEX_REASONING_EFFORT"
    printf 'Dry run: %s\n' "$DRY_RUN"
    printf 'Updated: %s\n\n' "$(date -Is)"
    printf '## Passes\n\n'
    local file pass
    for file in "${pass_files[@]}"; do
      pass="$(basename "$(dirname "$file")")"
      printf -- '- %s: summary=%s\n' "$pass" "$file"
    done
    printf '\n## How To Review\n\n'
    printf -- '- Start with the newest pass summary, then open run-summary.md and trace-digest.md.\n'
    printf -- '- Review/fix summaries are separate files so the approval loop remains auditable.\n'
    printf -- '- Memory stores paths and compact signals only; it intentionally omits raw logs, spans, reports, prompts, and diffs.\n'
  } > "$LATEST_SUMMARY"
}

require_loop_files
ensure_memory

end_iter=$((START_ITER + MAX_ITERS - 1))

printf 'Improve loop run directory: %s\n' "$RUN_DIR"
printf 'Memory: %s\n' "$MEMORY_FILE"
printf 'Codex reasoning effort: %s\n' "$CODEX_REASONING_EFFORT"
printf 'Dry run: %s\n' "$DRY_RUN"
printf 'Git auto-commit: %s\n' "$IMPROVE_LOOP_AUTO_COMMIT"
printf 'Git auto-push: %s\n' "$IMPROVE_LOOP_AUTO_PUSH"
printf 'Git push target: %s/%s\n' "$IMPROVE_LOOP_GIT_REMOTE" "$CURRENT_GIT_BRANCH"
printf 'Latest rollup: %s\n' "$LATEST_SUMMARY"

for i in $(seq "$START_ITER" "$end_iter"); do
  pass_dir="$RUN_DIR/pass-${i}"
  mkdir -p "$pass_dir"
  started="$(date -Is)"
  export LOOP_RUN_ID="$RUN_ID"
  export LOOP_PASS="$i"

  query="$(select_query "$i")"
  printf '%s\n' "$query" > "$pass_dir/query.txt"

  printf '\n=== Run pass %s/%s ===\n' "$i" "$end_iter"
  printf 'Query file: %s\n' "$pass_dir/query.txt"
  pre_run_trace="$(latest_trace_digest || true)"
  run_agent_phase "$pass_dir" "$pass_dir/query.txt" "$pre_run_trace"
  printf 'Run summary: %s\n' "$pass_dir/run-summary.md"

  write_prompt analyze "$pass_dir/analysis-prompt.md" "$pass_dir"

  printf '\n=== Analysis pass %s/%s ===\n' "$i" "$end_iter"
  if run_codex_phase analyze "$pass_dir/analysis-summary.md" "$pass_dir/analysis-prompt.md"; then
    analysis_exit=0
  else
    analysis_exit=$?
  fi
  printf 'Analysis phase exit: %s\n' "$analysis_exit"

  analysis_result="$(summary_value "IMPROVE_ANALYSIS_RESULT" "$pass_dir/analysis-summary.md")"
  if [[ "$analysis_result" == "analysis_complete" ]]; then
    write_prompt plan "$pass_dir/plan-prompt.md" "$pass_dir"

    printf '\n=== Plan pass %s/%s ===\n' "$i" "$end_iter"
    if run_codex_phase plan "$pass_dir/plan-summary.md" "$pass_dir/plan-prompt.md"; then
      plan_exit=0
    else
      plan_exit=$?
    fi
  else
    plan_exit=99
    write_skipped_summary plan "$pass_dir/plan-summary.md" "Analysis did not return IMPROVE_ANALYSIS_RESULT: analysis_complete."
  fi
  printf 'Plan phase exit: %s\n' "$plan_exit"

  plan_result="$(summary_value "IMPROVE_PLAN_RESULT" "$pass_dir/plan-summary.md")"
  if [[ "$plan_result" == "planned" ]]; then
    write_prompt build "$pass_dir/build-prompt.md" "$pass_dir"

    printf '\n=== Build pass %s/%s ===\n' "$i" "$end_iter"
    if run_codex_phase build "$pass_dir/build-summary.md" "$pass_dir/build-prompt.md"; then
      build_exit=0
    else
      build_exit=$?
    fi
  else
    build_exit=99
    write_skipped_summary build "$pass_dir/build-summary.md" "Plan did not return IMPROVE_PLAN_RESULT: planned."
  fi
  printf 'Build phase exit: %s\n' "$build_exit"

  write_current_diff "$pass_dir"
  write_test_evidence "$pass_dir/test-evidence.md" "$pass_dir/build-summary.md"

  build_result="$(summary_value "IMPROVER_RESULT" "$pass_dir/build-summary.md")"
  if [[ "$build_result" == "blocked" ]]; then
    write_skipped_summary review "$pass_dir/review-1-summary.md" "Build phase was blocked."
    final_review_summary="$pass_dir/review-1-summary.md"
    final_review_result="blocked"
    fix_attempts=0
  else
    review_attempt=1
    fix_attempts=0
    while true; do
      write_prompt review "$pass_dir/review-${review_attempt}-prompt.md" "$pass_dir"

      printf '\n=== Review pass %s/%s attempt %s ===\n' "$i" "$end_iter" "$review_attempt"
      if run_codex_phase review "$pass_dir/review-${review_attempt}-summary.md" "$pass_dir/review-${review_attempt}-prompt.md" "$review_attempt"; then
        review_exit=0
      else
        review_exit=$?
      fi
      printf 'Review phase exit: %s\n' "$review_exit"

      final_review_summary="$pass_dir/review-${review_attempt}-summary.md"
      final_review_result="$(summary_value "IMPROVE_REVIEW_RESULT" "$final_review_summary")"
      [[ -n "$final_review_result" ]] || final_review_result="blocked"

      if [[ "$final_review_result" != "changes_requested" ]]; then
        break
      fi
      if [[ "$fix_attempts" -ge "$MAX_FIX_ATTEMPTS" ]]; then
        final_review_result="blocked"
        break
      fi

      fix_attempts=$((fix_attempts + 1))
      write_prompt fix "$pass_dir/fix-${fix_attempts}-prompt.md" "$pass_dir"

      printf '\n=== Fix pass %s/%s attempt %s ===\n' "$i" "$end_iter" "$fix_attempts"
      if run_codex_phase fix "$pass_dir/fix-${fix_attempts}-summary.md" "$pass_dir/fix-${fix_attempts}-prompt.md" "$fix_attempts"; then
        fix_exit=0
      else
        fix_exit=$?
      fi
      printf 'Fix phase exit: %s\n' "$fix_exit"

      write_current_diff "$pass_dir"
      write_test_evidence "$pass_dir/test-evidence.md" "$pass_dir/build-summary.md" "$pass_dir/fix-${fix_attempts}-summary.md"
      review_attempt=$((review_attempt + 1))
    done
  fi

  if [[ "$fix_attempts" -eq 0 && ! -s "$pass_dir/fix-0-summary.md" ]]; then
    write_skipped_summary fix "$pass_dir/fix-0-summary.md" "No fix phase was needed."
  fi

  ended="$(date -Is)"
  write_pass_summary "$pass_dir" "$i" "$started" "$ended" "$final_review_summary" "$final_review_result" "$fix_attempts"
  update_memory "$i" "$pass_dir" "$pass_dir/run-summary.md" "$pass_dir/analysis-summary.md" "$pass_dir/build-summary.md" "$pass_dir/summary.md"
  update_latest_summary
  finalize_git_for_pass "$i" "$pass_dir" "$final_review_result"

  printf '\nPass %s final review result: %s\n' "$i" "$final_review_result"
  printf 'Pass summary: %s\n' "$pass_dir/summary.md"
  printf 'Latest rollup: %s\n' "$LATEST_SUMMARY"
  git status --short
done
