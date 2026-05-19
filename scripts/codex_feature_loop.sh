#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/codex_feature_loop.sh [--dry-run] [--allow-dirty-start] [MAX_FEATURES]

Runs a roadmap feature implementation loop:
  analyze roadmap -> plan -> build -> review -> fix/review until approved

Approved feature passes are committed and pushed to the currently checked-out
branch so each feature builds on the last approved repository state.
Each approved pass also appends an implementation-history entry to the roadmap
markdown. The log directory keeps only a compact run index and phase artifacts.

Options:
  --dry-run, --prompt-only   Write stub artifacts and summaries without running Codex.
  --allow-dirty-start        Do not require a clean worktree before starting.
                             Use carefully: approved commits may include existing changes.
  -h, --help                 Show this help text.

Useful environment variables:
  MAX_FEATURES               Number of roadmap feature passes to attempt. Default: 10.
  START_FEATURE              First pass number for this run. Default: 1.
  MAX_FIX_ATTEMPTS           Fix/review cap per feature, or unlimited. Default: unlimited.
  FEATURE_LOOP_TARGET        Preferred roadmap feature or heading to implement first.
  ROADMAP_FILE               Roadmap markdown file to implement.
  FEATURE_LOOP_AUTO_COMMIT   1 to commit approved passes, 0 to skip. Default: 1.
  FEATURE_LOOP_AUTO_PUSH     1 to push approved passes, 0 to skip. Default: 1.
USAGE
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQUESTED_ITERS="${MAX_FEATURES:-}"
DRY_RUN="${DRY_RUN:-0}"
ALLOW_DIRTY_START="${FEATURE_LOOP_ALLOW_DIRTY_START:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run|--prompt-only)
      DRY_RUN=1
      shift
      ;;
    --allow-dirty-start)
      ALLOW_DIRTY_START=1
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

MAX_FEATURES="${REQUESTED_ITERS:-10}"
START_FEATURE="${START_FEATURE:-1}"
MAX_FIX_ATTEMPTS="${MAX_FIX_ATTEMPTS:-unlimited}"
CODEX_SANDBOX_MODE="${CODEX_SANDBOX_MODE:-danger-full-access}"
CODEX_REASONING_EFFORT="${CODEX_REASONING_EFFORT:-xhigh}"
LOG_ROOT="${LOG_ROOT:-$REPO_ROOT/logs/feature-loop}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
RUN_DIR="$LOG_ROOT/runs/$RUN_ID"
LATEST_SUMMARY="$LOG_ROOT/latest-summary.md"
RUN_INDEX_FILE="$LOG_ROOT/run-index.md"
ROADMAP_FILE="${ROADMAP_FILE:-$REPO_ROOT/docs/agent-improvement-feature-roadmap.md}"
PROMPT_DIR="$REPO_ROOT/scripts/feature_loop/prompts"

FEATURE_LOOP_AUTO_COMMIT="${FEATURE_LOOP_AUTO_COMMIT:-1}"
FEATURE_LOOP_AUTO_PUSH="${FEATURE_LOOP_AUTO_PUSH:-1}"
FEATURE_LOOP_GIT_REMOTE="${FEATURE_LOOP_GIT_REMOTE:-origin}"
FEATURE_LOOP_STOP_ON_DIRTY_UNAPPROVED="${FEATURE_LOOP_STOP_ON_DIRTY_UNAPPROVED:-1}"

for value_name in MAX_FEATURES START_FEATURE; do
  value="${!value_name}"
  if ! [[ "$value" =~ ^[0-9]+$ ]] || [[ "$value" -lt 1 ]]; then
    printf '%s must be a positive integer, got %s\n' "$value_name" "$value" >&2
    exit 2
  fi
done

if [[ "$MAX_FIX_ATTEMPTS" != "unlimited" ]] && ! [[ "$MAX_FIX_ATTEMPTS" =~ ^[0-9]+$ ]]; then
  printf 'MAX_FIX_ATTEMPTS must be a non-negative integer or unlimited, got %s\n' "$MAX_FIX_ATTEMPTS" >&2
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
  printf 'Cannot auto-commit feature loop passes from detached HEAD. Check out a branch first.\n' >&2
  exit 2
fi

git_status_porcelain() {
  git status --porcelain --untracked-files=normal -- .
}

has_git_changes() {
  [[ -n "$(git_status_porcelain)" ]]
}

if [[ "$DRY_RUN" != "1" && "$ALLOW_DIRTY_START" != "1" ]] && has_git_changes; then
  {
    printf 'Refusing to start feature loop with a dirty worktree.\n'
    printf 'Commit/stash current changes, or rerun with --allow-dirty-start.\n'
    printf 'Current status:\n'
    git status --short
  } >&2
  exit 2
fi

mkdir -p "$RUN_DIR"

require_loop_files() {
  local missing=0
  local template
  [[ -s "$ROADMAP_FILE" ]] || { printf 'Missing roadmap file: %s\n' "$ROADMAP_FILE" >&2; missing=1; }
  for template in analyze plan build review fix; do
    [[ -s "$PROMPT_DIR/$template.md" ]] || {
      printf 'Missing prompt template: %s\n' "$PROMPT_DIR/$template.md" >&2
      missing=1
    }
  done
  [[ "$missing" -eq 0 ]] || exit 2
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

index_lines() {
  local prefix="$1"
  local limit="$2"
  grep -E "^- ${prefix}:" "$RUN_INDEX_FILE" 2>/dev/null | tail -n "$limit" || true
}

emit_or_none() {
  local lines="$1"
  if [[ -n "$lines" ]]; then
    printf '%s\n' "$lines"
  else
    printf -- '- none\n'
  fi
}

ensure_run_index() {
  mkdir -p "$(dirname "$RUN_INDEX_FILE")"
  if [[ ! -f "$RUN_INDEX_FILE" ]]; then
    cat > "$RUN_INDEX_FILE" <<'INDEX'
# Feature Loop Run Index

## Last 10 Approved Features / Files / Tests
- none

## Blocked Features Needing Human Attention
- none

## Known Environment Blockers
- none
INDEX
  fi
}

write_feature_request() {
  local pass_num="$1"
  local output_file="$2"
  {
    printf '# Feature Implementation Request\n\n'
    printf 'Run ID: %s\n' "$RUN_ID"
    printf 'Feature pass: %s\n' "$pass_num"
    printf 'Roadmap file: %s\n' "$ROADMAP_FILE"
    printf 'Current branch: %s\n' "$CURRENT_GIT_BRANCH"
    printf '\n## Target Agent Flow\n\n'
    printf 'planner -> source recipe -> typed fetch -> validated transforms -> evidence bundle -> chart/report projection -> QA\n'
    printf '\n## Preferred Target\n\n'
    if [[ -n "${FEATURE_LOOP_TARGET:-}" ]]; then
      printf '%s\n' "$FEATURE_LOOP_TARGET"
    else
      printf 'Select the next highest-leverage unimplemented roadmap feature.\n'
    fi
    printf '\n## Implementation Rule\n\n'
    printf 'Implement one coherent feature slice. Do not attempt the entire roadmap in one pass.\n'
    printf 'When the pass is approved, the harness appends how it was implemented to the roadmap markdown.\n'
  } > "$output_file"
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
    printf -- '- Roadmap file: %s\n' "$ROADMAP_FILE"
    printf -- '- Run index path: %s\n' "$RUN_INDEX_FILE"
    printf -- '- Current branch: %s\n' "$CURRENT_GIT_BRANCH"
    printf '\nUse files from the pass directory. Do not expect artifact contents in this prompt.\n'
    printf '\n## Files To Inspect\n\n'
    printf -- '- `feature-request.md`\n'
    printf -- '- `%s`\n' "$ROADMAP_FILE"
    printf -- '- `%s`\n' "$RUN_INDEX_FILE"
    case "$phase" in
      plan)
        printf -- '- `analysis-summary.md`\n'
        printf -- '- relevant source files and nearby tests\n'
        ;;
      build)
        printf -- '- `plan-summary.md`\n'
        printf -- '- `analysis-summary.md`\n'
        ;;
      review)
        printf -- '- `analysis-summary.md`\n'
        printf -- '- `plan-summary.md`\n'
        printf -- '- `build-summary.md` and latest `fix-*-summary.md` if present\n'
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
FEATURE_ANALYSIS_RESULT: feature_selected
FEATURE_TARGET: dry-run feature
FEATURE_ROADMAP_SECTION: dry-run section
FEATURE_FLOW_STAGE: cross-cutting
FEATURE_SELECTION_NOTES: Dry-run selected a small implementation slice.
SUMMARY
      ;;
    plan)
      cat > "$output_file" <<'SUMMARY'
FEATURE_PLAN_RESULT: planned
FEATURE_TARGET: dry-run feature
FEATURE_PLAN_FILES: none
FEATURE_PLAN_TESTS: none
FEATURE_PLAN_SUMMARY: Dry-run planned a stub feature implementation.
SUMMARY
      ;;
    build)
      cat > "$output_file" <<'SUMMARY'
FEATURE_BUILD_RESULT: patched
FEATURE_TARGET: dry-run feature
FEATURE_FILES_CHANGED: none
FEATURE_TESTS_RUN: none
FEATURE_IMPLEMENTATION_NOTES: Dry-run implemented a stub feature.
SUMMARY
      ;;
    review)
      local result
      result="$(dry_run_review_result "$attempt")"
      cat > "$output_file" <<SUMMARY
FEATURE_REVIEW_RESULT: $result
FEATURE_REVIEW_FINDINGS: dry-run finding for attempt $attempt
SUMMARY
      ;;
    fix)
      cat > "$output_file" <<'SUMMARY'
FEATURE_FIX_RESULT: patched
FEATURE_TARGET: dry-run feature
FEATURE_FILES_CHANGED: none
FEATURE_TESTS_RUN: none
FEATURE_IMPLEMENTATION_NOTES: Dry-run fix addressed the review finding.
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
        printf 'FEATURE_PLAN_RESULT: blocked\n'
        printf 'FEATURE_TARGET: unknown\n'
        printf 'FEATURE_PLAN_FILES: unknown\n'
        printf 'FEATURE_PLAN_TESTS: unknown\n'
        printf 'FEATURE_PLAN_SUMMARY: %s\n' "$reason"
      } > "$output_file"
      ;;
    build)
      {
        printf 'FEATURE_BUILD_RESULT: blocked\n'
        printf 'FEATURE_TARGET: unknown\n'
        printf 'FEATURE_FILES_CHANGED: none\n'
        printf 'FEATURE_TESTS_RUN: none\n'
        printf 'FEATURE_IMPLEMENTATION_NOTES: %s\n' "$reason"
      } > "$output_file"
      ;;
    review)
      {
        printf 'FEATURE_REVIEW_RESULT: blocked\n'
        printf 'FEATURE_REVIEW_FINDINGS: %s\n' "$reason"
      } > "$output_file"
      ;;
    fix)
      {
        printf 'FEATURE_FIX_RESULT: no_patch\n'
        printf 'FEATURE_TARGET: unknown\n'
        printf 'FEATURE_FILES_CHANGED: none\n'
        printf 'FEATURE_TESTS_RUN: none\n'
        printf 'FEATURE_IMPLEMENTATION_NOTES: %s\n' "$reason"
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
      tests="$(summary_value "FEATURE_TESTS_RUN" "$summary")"
      [[ -n "$tests" ]] || tests="see phase summary"
      printf -- '- Summary: %s\n' "$summary"
      printf '  Tests: %s\n' "$tests"
    done
  } > "$output_file"
}

write_git_finalization() {
  local output_file="$1"
  local status="$2"
  local detail="$3"
  local commit_sha="${4:-}"

  {
    printf 'status: %s\n' "$status"
    printf 'detail: %s\n' "$detail"
    printf 'remote: %s\n' "$FEATURE_LOOP_GIT_REMOTE"
    printf 'branch: %s\n' "$CURRENT_GIT_BRANCH"
    if [[ -n "$commit_sha" ]]; then
      printf 'commit: %s\n' "$commit_sha"
    fi
  } > "$output_file"
}

commit_and_push_pass() {
  local pass_num="$1"
  local pass_dir="$2"

  if [[ "$DRY_RUN" == "1" || "$FEATURE_LOOP_AUTO_COMMIT" != "1" ]]; then
    write_git_finalization "$pass_dir/git-finalization.txt" "skipped" "Git auto-commit disabled for this run."
    return 0
  fi

  if ! has_git_changes; then
    write_git_finalization "$pass_dir/git-finalization.txt" "skipped" "No repository changes to commit."
    printf 'No repository changes to commit for approved feature pass %s.\n' "$pass_num"
    return 0
  fi

  local target tests title body commit_sha
  target="$(summary_value "FEATURE_TARGET" "$pass_dir/analysis-summary.md")"
  [[ -n "$target" ]] || target="roadmap feature"
  target="${target//$'\n'/ }"
  tests="$(summary_value "FEATURE_TESTS_RUN" "$pass_dir/build-summary.md")"
  [[ -n "$tests" ]] || tests="see feature summary"

  title="codex feature pass ${pass_num}: ${target}"
  body="$(cat <<BODY
Run: $RUN_ID
Pass: $pass_num
Target: $target
Roadmap: $ROADMAP_FILE
Summary: $pass_dir/summary.md
Tests: $tests
BODY
)"

  git add -A -- .
  if git diff --cached --quiet -- .; then
    write_git_finalization "$pass_dir/git-finalization.txt" "skipped" "No staged changes after git add."
    printf 'No staged changes to commit for approved feature pass %s.\n' "$pass_num"
    return 0
  fi

  git commit -m "$title" -m "$body"
  commit_sha="$(git rev-parse HEAD)"
  printf '%s\n' "$commit_sha" > "$pass_dir/git-commit.txt"

  if [[ "$FEATURE_LOOP_AUTO_PUSH" == "1" ]]; then
    git push "$FEATURE_LOOP_GIT_REMOTE" "HEAD:$CURRENT_GIT_BRANCH"
    write_git_finalization "$pass_dir/git-finalization.txt" "pushed" "Committed and pushed approved feature pass." "$commit_sha"
    printf 'Committed and pushed approved feature pass %s: %s\n' "$pass_num" "$commit_sha"
  else
    write_git_finalization "$pass_dir/git-finalization.txt" "committed" "Committed approved feature pass; push disabled." "$commit_sha"
    printf 'Committed approved feature pass %s without push: %s\n' "$pass_num" "$commit_sha"
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

  write_git_finalization "$pass_dir/git-finalization.txt" "skipped" "Feature pass was not approved; no commit attempted."
  if [[ "$FEATURE_LOOP_STOP_ON_DIRTY_UNAPPROVED" == "1" ]] && has_git_changes; then
    {
      printf 'Feature pass %s ended with review result %s and left uncommitted changes.\n' "$pass_num" "$final_review_result"
      printf 'Stopping before the next pass so unapproved work is not overwritten or built upon.\n'
      printf 'Inspect: %s/current-diff.patch\n' "$pass_dir"
    } >&2
    return 1
  fi
}

update_run_index() {
  local pass_num="$1"
  local pass_dir="$2"
  local build_summary="$3"
  local final_review_summary="$4"

  local target files tests review_result build_result
  target="$(summary_value "FEATURE_TARGET" "$pass_dir/analysis-summary.md")"
  files="$(summary_value "FEATURE_FILES_CHANGED" "$build_summary")"
  tests="$(summary_value "FEATURE_TESTS_RUN" "$build_summary")"
  review_result="$(summary_value "FEATURE_REVIEW_RESULT" "$final_review_summary")"
  build_result="$(summary_value "FEATURE_BUILD_RESULT" "$build_summary")"

  local old_approved old_blocked old_env
  old_approved="$(index_lines "approved" 10)"
  old_blocked="$(index_lines "blocked" 10)"
  old_env="$(index_lines "env" 5)"

  local new_approved=""
  if [[ "$review_result" == "approved" ]]; then
    new_approved="- approved: run=$RUN_ID pass=$pass_num target=${target:-unknown} files=${files:-see-build-summary} tests=${tests:-see-build-summary} summary=$pass_dir/summary.md"
  fi

  local new_blocked=""
  if [[ "$review_result" == "blocked" || "$build_result" == "blocked" ]]; then
    new_blocked="- blocked: run=$RUN_ID pass=$pass_num target=${target:-unknown} summary=$pass_dir/summary.md"
  fi

  local approved_lines blocked_lines
  approved_lines="$(printf '%s\n%s\n' "$old_approved" "$new_approved" | sed '/^[[:space:]]*$/d' | tail -n 10)"
  blocked_lines="$(printf '%s\n%s\n' "$old_blocked" "$new_blocked" | sed '/^[[:space:]]*$/d' | tail -n 10)"

  {
    printf '# Feature Loop Run Index\n\n'
    printf '## Last 10 Approved Features / Files / Tests\n'
    emit_or_none "$approved_lines"
    printf '\n## Blocked Features Needing Human Attention\n'
    emit_or_none "$blocked_lines"
    printf '\n## Known Environment Blockers\n'
    emit_or_none "$old_env"
  } > "$RUN_INDEX_FILE"
}

roadmap_escape_line() {
  local value="$1"
  value="${value//$'\n'/ }"
  value="${value//$'\r'/ }"
  printf '%s' "$value"
}

append_roadmap_implementation() {
  local pass_num="$1"
  local pass_dir="$2"
  local final_review_result="$3"

  [[ "$final_review_result" == "approved" ]] || return 0
  [[ "$DRY_RUN" == "1" ]] && return 0

  local target roadmap_section flow_stage files tests implementation_notes review_findings stamp
  target="$(roadmap_escape_line "$(summary_value "FEATURE_TARGET" "$pass_dir/analysis-summary.md")")"
  [[ -n "$target" ]] || target="unknown feature"
  roadmap_section="$(roadmap_escape_line "$(summary_value "FEATURE_ROADMAP_SECTION" "$pass_dir/analysis-summary.md")")"
  [[ -n "$roadmap_section" ]] || roadmap_section="unknown"
  flow_stage="$(roadmap_escape_line "$(summary_value "FEATURE_FLOW_STAGE" "$pass_dir/analysis-summary.md")")"
  [[ -n "$flow_stage" ]] || flow_stage="unknown"
  files="$(roadmap_escape_line "$(summary_value "FEATURE_FILES_CHANGED" "$pass_dir/build-summary.md")")"
  [[ -n "$files" ]] || files="none"
  tests="$(roadmap_escape_line "$(summary_value "FEATURE_TESTS_RUN" "$pass_dir/build-summary.md")")"
  [[ -n "$tests" ]] || tests="none"
  implementation_notes="$(roadmap_escape_line "$(summary_value "FEATURE_IMPLEMENTATION_NOTES" "$pass_dir/build-summary.md")")"
  if [[ -z "$implementation_notes" && -s "$pass_dir/fix-0-summary.md" ]]; then
    implementation_notes="$(roadmap_escape_line "$(summary_value "FEATURE_IMPLEMENTATION_NOTES" "$pass_dir/fix-0-summary.md")")"
  fi
  [[ -n "$implementation_notes" ]] || implementation_notes="See feature pass summary."
  review_findings="$(roadmap_escape_line "$(summary_value "FEATURE_REVIEW_FINDINGS" "$pass_dir/summary.md")")"
  [[ -n "$review_findings" ]] || review_findings="approved"
  stamp="$(date -Is)"

  if ! grep -q '^## Implementation History$' "$ROADMAP_FILE"; then
    {
      printf '\n## Implementation History\n\n'
      printf 'This section is updated by `scripts/codex_feature_loop.sh` when a feature pass is approved.\n'
    } >> "$ROADMAP_FILE"
  fi

  {
    printf '\n- [x] %s - %s\n' "$stamp" "$target"
    printf '  - Roadmap section: %s\n' "$roadmap_section"
    printf '  - Flow stage: %s\n' "$flow_stage"
    printf '  - Run/pass: %s / %s\n' "$RUN_ID" "$pass_num"
    printf '  - Summary: %s\n' "$pass_dir/summary.md"
    printf '  - Files changed: %s\n' "$files"
    printf '  - Tests: %s\n' "$tests"
    printf '  - Implementation: %s\n' "$implementation_notes"
    printf '  - Review: %s\n' "$review_findings"
  } >> "$ROADMAP_FILE"
}

write_pass_summary() {
  local pass_dir="$1"
  local pass_num="$2"
  local started="$3"
  local ended="$4"
  local final_review_summary="$5"
  local final_review_result="$6"
  local fix_attempts="$7"
  local final_review_findings
  final_review_findings="$(summary_value "FEATURE_REVIEW_FINDINGS" "$final_review_summary")"

  {
    printf '# Feature Loop Pass %s\n\n' "$pass_num"
    printf 'Started: %s\n' "$started"
    printf 'Ended: %s\n' "$ended"
    printf 'Run: %s\n' "$RUN_ID"
    printf 'Run directory: %s\n' "$RUN_DIR"
    printf 'Roadmap: %s\n' "$ROADMAP_FILE"
    printf 'Run index: %s\n' "$RUN_INDEX_FILE"
    printf 'Feature request: %s\n' "$pass_dir/feature-request.md"
    printf 'Final review result: %s\n' "$final_review_result"
    printf 'Fix attempts: %s\n' "$fix_attempts"
    printf 'FEATURE_ANALYSIS_RESULT: %s\n' "$(summary_value "FEATURE_ANALYSIS_RESULT" "$pass_dir/analysis-summary.md")"
    printf 'FEATURE_TARGET: %s\n' "$(summary_value "FEATURE_TARGET" "$pass_dir/analysis-summary.md")"
    printf 'FEATURE_ROADMAP_SECTION: %s\n' "$(summary_value "FEATURE_ROADMAP_SECTION" "$pass_dir/analysis-summary.md")"
    printf 'FEATURE_FLOW_STAGE: %s\n' "$(summary_value "FEATURE_FLOW_STAGE" "$pass_dir/analysis-summary.md")"
    printf 'FEATURE_PLAN_RESULT: %s\n' "$(summary_value "FEATURE_PLAN_RESULT" "$pass_dir/plan-summary.md")"
    printf 'FEATURE_BUILD_RESULT: %s\n' "$(summary_value "FEATURE_BUILD_RESULT" "$pass_dir/build-summary.md")"
    printf 'FEATURE_REVIEW_RESULT: %s\n' "$final_review_result"
    printf 'FEATURE_REVIEW_FINDINGS: %s\n' "$final_review_findings"
    if [[ -s "$pass_dir/fix-${fix_attempts}-summary.md" ]]; then
      printf 'FEATURE_FIX_RESULT: %s\n' "$(summary_value "FEATURE_FIX_RESULT" "$pass_dir/fix-${fix_attempts}-summary.md")"
    else
      printf 'FEATURE_FIX_RESULT: not_run\n'
    fi
    printf 'FEATURE_IMPLEMENTATION_NOTES: %s\n' "$(summary_value "FEATURE_IMPLEMENTATION_NOTES" "$pass_dir/build-summary.md")"
    printf '\n## Artifact Paths\n\n'
    printf -- '- Analysis prompt: %s\n' "$pass_dir/analysis-prompt.md"
    printf -- '- Analysis summary: %s\n' "$pass_dir/analysis-summary.md"
    printf -- '- Plan prompt: %s\n' "$pass_dir/plan-prompt.md"
    printf -- '- Plan summary: %s\n' "$pass_dir/plan-summary.md"
    printf -- '- Build prompt: %s\n' "$pass_dir/build-prompt.md"
    printf -- '- Build summary: %s\n' "$pass_dir/build-summary.md"
    printf -- '- Current diff: %s\n' "$pass_dir/current-diff.patch"
    printf -- '- Current status: %s\n' "$pass_dir/current-status.txt"
    printf -- '- Test evidence: %s\n' "$pass_dir/test-evidence.md"
    printf '\n## Feature Request\n\n'
    cat "$pass_dir/feature-request.md"
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
    printf '# Codex Feature Loop Summary\n\n'
    printf 'Run: %s\n' "$RUN_ID"
    printf 'Run directory: %s\n' "$RUN_DIR"
    printf 'Roadmap: %s\n' "$ROADMAP_FILE"
    printf 'Run index: %s\n' "$RUN_INDEX_FILE"
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
    printf -- '- Start with the newest pass summary, then inspect current-diff.patch and test-evidence.md.\n'
    printf -- '- Each approved pass should implement one roadmap feature slice.\n'
    printf -- '- The roadmap markdown stores approved implementation history.\n'
    printf -- '- The run index stores only compact approved/blocked pass pointers.\n'
  } > "$LATEST_SUMMARY"
}

require_loop_files
ensure_run_index

end_feature=$((START_FEATURE + MAX_FEATURES - 1))

printf 'Feature loop run directory: %s\n' "$RUN_DIR"
printf 'Roadmap: %s\n' "$ROADMAP_FILE"
printf 'Run index: %s\n' "$RUN_INDEX_FILE"
printf 'Feature passes requested: %s\n' "$MAX_FEATURES"
printf 'Feature pass range: %s-%s\n' "$START_FEATURE" "$end_feature"
printf 'Max fix attempts per feature: %s\n' "$MAX_FIX_ATTEMPTS"
printf 'Codex reasoning effort: %s\n' "$CODEX_REASONING_EFFORT"
printf 'Dry run: %s\n' "$DRY_RUN"
printf 'Git auto-commit: %s\n' "$FEATURE_LOOP_AUTO_COMMIT"
printf 'Git auto-push: %s\n' "$FEATURE_LOOP_AUTO_PUSH"
printf 'Git push target: %s/%s\n' "$FEATURE_LOOP_GIT_REMOTE" "$CURRENT_GIT_BRANCH"
printf 'Latest rollup: %s\n' "$LATEST_SUMMARY"

for i in $(seq "$START_FEATURE" "$end_feature"); do
  pass_dir="$RUN_DIR/feature-${i}"
  mkdir -p "$pass_dir"
  started="$(date -Is)"
  export FEATURE_LOOP_RUN_ID="$RUN_ID"
  export FEATURE_LOOP_PASS="$i"

  write_feature_request "$i" "$pass_dir/feature-request.md"

  printf '\n=== Analyze feature %s/%s ===\n' "$i" "$end_feature"
  write_prompt analyze "$pass_dir/analysis-prompt.md" "$pass_dir"
  if run_codex_phase analyze "$pass_dir/analysis-summary.md" "$pass_dir/analysis-prompt.md"; then
    analysis_exit=0
  else
    analysis_exit=$?
  fi
  printf 'Analysis phase exit: %s\n' "$analysis_exit"

  analysis_result="$(summary_value "FEATURE_ANALYSIS_RESULT" "$pass_dir/analysis-summary.md")"
  if [[ "$analysis_result" == "feature_selected" ]]; then
    printf '\n=== Plan feature %s/%s ===\n' "$i" "$end_feature"
    write_prompt plan "$pass_dir/plan-prompt.md" "$pass_dir"
    if run_codex_phase plan "$pass_dir/plan-summary.md" "$pass_dir/plan-prompt.md"; then
      plan_exit=0
    else
      plan_exit=$?
    fi
  else
    plan_exit=99
    write_skipped_summary plan "$pass_dir/plan-summary.md" "Analysis did not return FEATURE_ANALYSIS_RESULT: feature_selected."
  fi
  printf 'Plan phase exit: %s\n' "$plan_exit"

  plan_result="$(summary_value "FEATURE_PLAN_RESULT" "$pass_dir/plan-summary.md")"
  if [[ "$plan_result" == "planned" ]]; then
    printf '\n=== Build feature %s/%s ===\n' "$i" "$end_feature"
    write_prompt build "$pass_dir/build-prompt.md" "$pass_dir"
    if run_codex_phase build "$pass_dir/build-summary.md" "$pass_dir/build-prompt.md"; then
      build_exit=0
    else
      build_exit=$?
    fi
  else
    build_exit=99
    write_skipped_summary build "$pass_dir/build-summary.md" "Plan did not return FEATURE_PLAN_RESULT: planned."
  fi
  printf 'Build phase exit: %s\n' "$build_exit"

  write_current_diff "$pass_dir"
  write_test_evidence "$pass_dir/test-evidence.md" "$pass_dir/build-summary.md"

  build_result="$(summary_value "FEATURE_BUILD_RESULT" "$pass_dir/build-summary.md")"
  if [[ "$build_result" == "blocked" ]]; then
    write_skipped_summary review "$pass_dir/review-1-summary.md" "Build phase was blocked."
    final_review_summary="$pass_dir/review-1-summary.md"
    final_review_result="blocked"
    fix_attempts=0
  else
    review_attempt=1
    fix_attempts=0
    while true; do
      printf '\n=== Review feature %s/%s attempt %s ===\n' "$i" "$end_feature" "$review_attempt"
      write_prompt review "$pass_dir/review-${review_attempt}-prompt.md" "$pass_dir"
      if run_codex_phase review "$pass_dir/review-${review_attempt}-summary.md" "$pass_dir/review-${review_attempt}-prompt.md" "$review_attempt"; then
        review_exit=0
      else
        review_exit=$?
      fi
      printf 'Review phase exit: %s\n' "$review_exit"

      final_review_summary="$pass_dir/review-${review_attempt}-summary.md"
      final_review_result="$(summary_value "FEATURE_REVIEW_RESULT" "$final_review_summary")"
      [[ -n "$final_review_result" ]] || final_review_result="blocked"

      if [[ "$final_review_result" != "changes_requested" ]]; then
        break
      fi
      if [[ "$MAX_FIX_ATTEMPTS" != "unlimited" && "$fix_attempts" -ge "$MAX_FIX_ATTEMPTS" ]]; then
        final_review_result="blocked"
        break
      fi

      fix_attempts=$((fix_attempts + 1))
      printf '\n=== Fix feature %s/%s attempt %s ===\n' "$i" "$end_feature" "$fix_attempts"
      write_prompt fix "$pass_dir/fix-${fix_attempts}-prompt.md" "$pass_dir"
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
  append_roadmap_implementation "$i" "$pass_dir" "$final_review_result"
  update_run_index "$i" "$pass_dir" "$pass_dir/build-summary.md" "$pass_dir/summary.md"
  update_latest_summary
  finalize_git_for_pass "$i" "$pass_dir" "$final_review_result"

  printf '\nFeature pass %s final review result: %s\n' "$i" "$final_review_result"
  printf 'Feature summary: %s\n' "$pass_dir/summary.md"
  printf 'Latest rollup: %s\n' "$LATEST_SUMMARY"
  git status --short
done
