#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/codex_refactor_loop.sh [--dry-run] [MAX_ITERS]

Runs a static backend quant helper-library cleanup loop:
  helper-plan -> helper-build -> helper-review -> helper-fix as needed

Options:
  --dry-run, --prompt-only  Write stub Markdown summaries without launching Codex.
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

MAX_ITERS="${REQUESTED_ITERS:-5}"
START_ITER="${START_ITER:-1}"
CODEX_SANDBOX_MODE="${CODEX_SANDBOX_MODE:-danger-full-access}"
CODEX_REASONING_EFFORT="${CODEX_REASONING_EFFORT:-xhigh}"
LOG_ROOT="${LOG_ROOT:-$REPO_ROOT/logs/helper-cleanup-loop}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
RUN_DIR="$LOG_ROOT/runs/$RUN_ID"
LATEST_SUMMARY="$LOG_ROOT/latest-summary.md"

for value_name in MAX_ITERS START_ITER; do
  value="${!value_name}"
  if ! [[ "$value" =~ ^[0-9]+$ ]] || [[ "$value" -lt 1 ]]; then
    printf '%s must be a positive integer, got %s\n' "$value_name" "$value" >&2
    exit 2
  fi
done

CODEX_MODEL_ARGS=(
  -c "model_reasoning_effort=\"$CODEX_REASONING_EFFORT\""
  -c "plan_mode_reasoning_effort=\"$CODEX_REASONING_EFFORT\""
)
if [[ -n "${CODEX_MODEL:-}" ]]; then
  CODEX_MODEL_ARGS=(--model "$CODEX_MODEL" "${CODEX_MODEL_ARGS[@]}")
fi

cd "$REPO_ROOT"
mkdir -p "$RUN_DIR"

BANNED_PATTERN='build_.*_outputs|build_.*_artifacts|deterministic_artifact|chart_pack_outputs|company_fundamental_contract|signal_stack_contract|macro_cycle_chart_pack'
FOCUSED_TESTS='cd backend && UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_quant_macro_stats.py tests/test_quant_developer_prompt_guardrails.py
cd backend && UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_technical_writer_flow_boundaries.py tests/test_quality_analyst_subagent.py
cd backend && UV_CACHE_DIR=/tmp/uv-cache uv run ruff check agents tests'

recent_context() {
  local count=0
  local file
  while IFS= read -r file; do
    [[ -f "$file" ]] || continue
    printf -- '- %s\n' "$file"
    count=$((count + 1))
    [[ "$count" -ge 5 ]] && return
  done < <(find "$RUN_DIR" -maxdepth 2 -type f -name summary.md 2>/dev/null | sort -Vr)
  [[ "$count" -gt 0 ]] || printf 'none\n'
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

dry_run_summary() {
  local phase="$1"
  local output_file="$2"
  case "$phase" in
    helper-plan)
      cat > "$output_file" <<'SUMMARY'
HELPER_PLAN_RESULT: target_found
HELPER_TARGET: dry-run-placeholder
HELPER_PLAN_FILES: none
HELPER_NEXT_SIGNAL: Run without --dry-run to select a real cleanup target.
SUMMARY
      ;;
    helper-build)
      cat > "$output_file" <<'SUMMARY'
HELPER_BUILD_RESULT: patched
HELPER_TARGET: dry-run-placeholder
HELPER_FILES_CHANGED: none
HELPER_METRIC_BEFORE: dry-run
HELPER_METRIC_AFTER: dry-run
HELPER_TESTS_RUN: none
HELPER_NEXT_SIGNAL: Run without --dry-run to implement cleanup.
SUMMARY
      ;;
    helper-review)
      cat > "$output_file" <<'SUMMARY'
HELPER_REVIEW_RESULT: approved
HELPER_REVIEW_TARGET: dry-run-placeholder
HELPER_REVIEW_TESTS_RUN: none
HELPER_REVIEW_FINDINGS: dry-run
HELPER_NEXT_SIGNAL: Run without --dry-run for real review.
SUMMARY
      ;;
    helper-fix)
      cat > "$output_file" <<'SUMMARY'
HELPER_FIX_RESULT: patched
HELPER_FIX_TARGET: dry-run-placeholder
HELPER_FIX_FILES_CHANGED: none
HELPER_FIX_TESTS_RUN: none
HELPER_NEXT_SIGNAL: Run without --dry-run to fix findings.
SUMMARY
      ;;
  esac
}

run_codex_phase() {
  local phase="$1"
  local output_file="$2"
  local prompt="$3"

  if [[ "$DRY_RUN" == "1" ]]; then
    printf 'Dry run: writing %s\n' "$output_file"
    dry_run_summary "$phase" "$output_file"
    return 0
  fi

  set +e
  codex exec \
    --cd "$REPO_ROOT" \
    --sandbox "$CODEX_SANDBOX_MODE" \
    --output-last-message "$output_file" \
    "${CODEX_MODEL_ARGS[@]}" \
    "$prompt"
  local status=$?
  set -e
  printf 'Codex %s exited with status %s; summary: %s\n' "$phase" "$status" "$output_file"
  return "$status"
}

plan_prompt() {
  local recent="$1"
  cat <<PROMPT
Use the repo-local agent-improver skill, Refactor Mode.

Phase: helper-plan. Static-only; do not edit files, format, start Phoenix, or run backend/tests/runner.py.

Goal: choose one coherent backend quant helper-library cleanup target. The library must expose reusable helpers only. Remove canned report/output logic and update prompts/tests so quant-developer composes reports from analysis.py helpers.

Banned active surfaces:
$BANNED_PATTERN

Required inspection:
- Run: rg "$BANNED_PATTERN" backend/agents backend/skills backend/tests scripts .agents/skills/agent-improver/SKILL.md
- Inspect only the relevant quant helper, quant-developer, writer, QA, skill, script, or test files.
- Pick one target that deletes/replaces a canned surface. Do not pick pure renames, code moves, query-specific routing, new report generators, or compatibility wrappers.

Recent summaries:
$recent

Final response:
- Target, evidence, first files to inspect, APIs/contracts/prompts/tests to delete or rewrite, helper-only API to keep, and focused verification commands:
$FOCUSED_TESTS
- End exactly with:
HELPER_PLAN_RESULT: target_found|no_target|blocked
HELPER_TARGET: <short target name>
HELPER_PLAN_FILES: <comma-separated files/modules>
HELPER_NEXT_SIGNAL: <one short sentence>
PROMPT
}

build_prompt() {
  local recent="$1"
  local plan_file="$2"
  cat <<PROMPT
Use the repo-local agent-improver skill, Refactor Mode.

Phase: helper-build. Read the plan summary first: $plan_file

Implement only that cleanup target. Preserve unrelated dirty worktree changes.

Hard rules:
- Backend quant library exposes reusable helpers only.
- Delete/rewrite public build_*_outputs APIs, build_*_artifacts tools, deterministic_artifact registries, deterministic chart packs, query-marker report routing, exact company/recession/macro-cycle contracts, and prompts requiring a report-specific tool before analysis.py.
- Quant-developer writes analysis.py and composes helpers.
- Writer/QA use generic evidence validation: numeric_facts, sources, methods, chart IDs, tables, diagnostics, limitations, and source coverage.
- Update related skills/tests; delete tests that only preserve the canned shape.

Recent summaries:
$recent

Verification to run when relevant:
$FOCUSED_TESTS

End exactly with:
HELPER_BUILD_RESULT: patched|no_patch|blocked
HELPER_TARGET: <short target name>
HELPER_FILES_CHANGED: <comma-separated files>
HELPER_METRIC_BEFORE: <short metric or unknown>
HELPER_METRIC_AFTER: <short metric or unknown>
HELPER_TESTS_RUN: <commands or none>
HELPER_NEXT_SIGNAL: <one short sentence>
PROMPT
}

review_prompt() {
  local recent="$1"
  local plan_file="$2"
  local build_file="$3"
  local previous_review="${4:-none}"
  local fix_file="${5:-none}"
  cat <<PROMPT
Use the repo-local agent-improver skill, Refactor Mode.

Phase: helper-review. Read-only; do not edit, format, start Phoenix, or run backend/tests/runner.py.

Inputs:
- Plan: $plan_file
- Build/fix summary: $build_file
- Previous review: $previous_review
- Latest fix: $fix_file

Review the diff against the helper-only contract. Request changes if the patch preserves canned exact-report APIs, adds query-specific routing, keeps deterministic chart packs/tools, keeps prompts requiring report-specific tools before analysis.py, only moves code, or leaves writer/QA exact-contract gates instead of generic evidence validation.

Run read-only checks when practical:
rg "$BANNED_PATTERN" backend/agents backend/skills
$FOCUSED_TESTS

Recent summaries:
$recent

End exactly with:
HELPER_REVIEW_RESULT: approved|changes_requested|blocked
HELPER_REVIEW_TARGET: <short target name>
HELPER_REVIEW_TESTS_RUN: <commands or none>
HELPER_REVIEW_FINDINGS: <short finding summary>
HELPER_NEXT_SIGNAL: <one short sentence>
PROMPT
}

fix_prompt() {
  local recent="$1"
  local plan_file="$2"
  local build_file="$3"
  local review_file="$4"
  cat <<PROMPT
Use the repo-local agent-improver skill, Refactor Mode.

Phase: helper-fix. Fix only review findings, then stop.

Inputs:
- Plan: $plan_file
- Build: $build_file
- Review findings: $review_file

Do not add report-specific routing, canned output builders, exact-report API shims, or prompt-only workarounds. Rerun relevant focused checks. Do not run Phoenix or backend/tests/runner.py.

Recent summaries:
$recent

End exactly with:
HELPER_FIX_RESULT: patched|no_patch|blocked
HELPER_FIX_TARGET: <short target name>
HELPER_FIX_FILES_CHANGED: <comma-separated files>
HELPER_FIX_TESTS_RUN: <commands or none>
HELPER_NEXT_SIGNAL: <one short sentence>
PROMPT
}

write_pass_summary() {
  local pass_dir="$1"
  local pass_num="$2"
  local plan_file="$3"
  local build_file="$4"
  local review_file="$5"
  local fix_file="${6:-}"
  local summary_file="$pass_dir/summary.md"

  {
    printf '# Helper Cleanup Pass %s\n\n' "$pass_num"
    printf 'Plan result: %s\n' "$(summary_value HELPER_PLAN_RESULT "$plan_file")"
    printf 'Build result: %s\n' "$(summary_value HELPER_BUILD_RESULT "$build_file")"
    printf 'Review result: %s\n' "$(summary_value HELPER_REVIEW_RESULT "$review_file")"
    if [[ -n "$fix_file" && -s "$fix_file" ]]; then
      printf 'Fix result: %s\n' "$(summary_value HELPER_FIX_RESULT "$fix_file")"
    else
      printf 'Fix result: not_run\n'
    fi
    printf '\n## Plan\n\n'
    cat "$plan_file"
    printf '\n## Build\n\n'
    cat "$build_file"
    if [[ -n "$fix_file" && -s "$fix_file" ]]; then
      printf '\n## Fix\n\n'
      cat "$fix_file"
    fi
    printf '\n## Review\n\n'
    cat "$review_file"
  } > "$summary_file"
}

update_latest_summary() {
  {
    printf '# Helper Cleanup Loop Summary\n\n'
    printf 'Run: %s\n' "$RUN_ID"
    printf 'Run directory: %s\n' "$RUN_DIR"
    printf 'Dry run: %s\n' "$DRY_RUN"
    printf '\n## Passes\n\n'
    find "$RUN_DIR" -maxdepth 2 -type f -name summary.md 2>/dev/null | sort -V | while read -r file; do
      printf -- '- %s: %s\n' "$(basename "$(dirname "$file")")" "$file"
    done
  } > "$LATEST_SUMMARY"
}

printf 'Helper cleanup loop run directory: %s\n' "$RUN_DIR"
printf 'Dry run: %s\n' "$DRY_RUN"
printf 'Latest rollup: %s\n' "$LATEST_SUMMARY"

end_iter=$((START_ITER + MAX_ITERS - 1))
overall_exit=0

for i in $(seq "$START_ITER" "$end_iter"); do
  pass_dir="$RUN_DIR/pass-${i}"
  mkdir -p "$pass_dir"

  recent="$(recent_context)"

  plan_file="$pass_dir/helper-plan-summary.md"
  build_file="$pass_dir/helper-build-summary.md"
  review_file="$pass_dir/helper-review-summary.md"
  fix_file=""

  printf '\n=== helper-plan pass %s/%s ===\n' "$i" "$end_iter"
  run_codex_phase helper-plan "$plan_file" "$(plan_prompt "$recent")" || overall_exit=$?

  plan_result="$(summary_value HELPER_PLAN_RESULT "$plan_file")"
  if [[ "$plan_result" != "target_found" ]]; then
    printf 'No target for pass %s: %s\n' "$i" "${plan_result:-unknown}"
    continue
  fi

  recent="$(recent_context)"
  printf '\n=== helper-build pass %s/%s ===\n' "$i" "$end_iter"
  run_codex_phase helper-build "$build_file" "$(build_prompt "$recent" "$plan_file")" || overall_exit=$?

  recent="$(recent_context)"
  printf '\n=== helper-review pass %s/%s ===\n' "$i" "$end_iter"
  run_codex_phase helper-review "$review_file" "$(review_prompt "$recent" "$plan_file" "$build_file")" || overall_exit=$?

  review_result="$(summary_value HELPER_REVIEW_RESULT "$review_file")"
  fix_attempt=1
  while [[ "$review_result" == "changes_requested" && "$fix_attempt" -le 3 ]]; do
    fix_file="$pass_dir/helper-fix-${fix_attempt}-summary.md"

    recent="$(recent_context)"
    printf '\n=== helper-fix pass %s attempt %s ===\n' "$i" "$fix_attempt"
    run_codex_phase helper-fix "$fix_file" "$(fix_prompt "$recent" "$plan_file" "$build_file" "$review_file")" || overall_exit=$?

    previous_review="$review_file"
    review_file="$pass_dir/helper-review-after-fix-${fix_attempt}-summary.md"
    recent="$(recent_context)"
    printf '\n=== helper-review after fix pass %s attempt %s ===\n' "$i" "$fix_attempt"
    run_codex_phase helper-review "$review_file" "$(review_prompt "$recent" "$plan_file" "$fix_file" "$previous_review" "$fix_file")" || overall_exit=$?

    review_result="$(summary_value HELPER_REVIEW_RESULT "$review_file")"
    fix_attempt=$((fix_attempt + 1))
  done

  write_pass_summary "$pass_dir" "$i" "$plan_file" "$build_file" "$review_file" "$fix_file"
  update_latest_summary
done

update_latest_summary
exit "$overall_exit"
