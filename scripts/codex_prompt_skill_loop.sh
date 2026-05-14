#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAX_ITERS="${1:-5}"
START_ITER="${START_ITER:-1}"
CODEX_SANDBOX_MODE="${CODEX_SANDBOX_MODE:-danger-full-access}"
CODEX_MODEL="${CODEX_MODEL:-gpt-5.5}"
CODEX_REASONING_EFFORT="${CODEX_REASONING_EFFORT:-xhigh}"
LOG_ROOT="${LOG_ROOT:-$REPO_ROOT/logs/prompt-skill-loop}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
RUN_DIR="$LOG_ROOT/runs/$RUN_ID"
LATEST_SUMMARY="$LOG_ROOT/latest-summary.md"

TARGET_AGENTS=(
  "quant-developer"
  "data-engineer"
  "orchestrator"
  "technical-writer"
  "quality-analyst"
)

cd "$REPO_ROOT"
mkdir -p "$RUN_DIR"

CODEX_MODEL_ARGS=(
  --model "$CODEX_MODEL"
  -c "model_reasoning_effort=\"$CODEX_REASONING_EFFORT\""
  -c "plan_mode_reasoning_effort=\"$CODEX_REASONING_EFFORT\""
)

select_agent() {
  local pass_num="$1"
  local index
  index=$(( (pass_num - 1) % ${#TARGET_AGENTS[@]} ))
  printf '%s' "${TARGET_AGENTS[$index]}"
}

allowed_scope() {
  local agent="$1"
  case "$agent" in
    quant-developer)
      cat <<'EOF'
- backend/agents/quantitative_developer/prompts.py
- backend/agents/quantitative_developer/middleware.py only when needed for prompt/skill loading behavior
- backend/skills/quant-developer/**
- focused quant prompt/skill tests
EOF
      ;;
    data-engineer)
      cat <<'EOF'
- backend/agents/data_engineer/prompts.py
- backend/agents/data_engineer/factory.py only for runtime prompt/tool selection behavior
- backend/skills/data-engineer/**
- focused data-engineer prompt/factory/toolbox tests
EOF
      ;;
    orchestrator)
      cat <<'EOF'
- backend/agents/orchestrator/prompts.py
- backend/agents/orchestrator/factory.py only when needed for native skill registration/loading
- backend/skills/orchestrator/**
- focused orchestrator prompt/routing/skill tests
EOF
      ;;
    technical-writer)
      cat <<'EOF'
- backend/agents/technical_writer/subagent.py prompt text only
- backend/skills/technical-writer/**
- focused technical-writer prompt/report tests
EOF
      ;;
    quality-analyst)
      cat <<'EOF'
- backend/agents/quality_analyst/prompts.py
- focused quality-analyst prompt/subagent tests
EOF
      ;;
    *)
      printf 'Unknown agent: %s\n' "$agent" >&2
      exit 2
      ;;
  esac
}

verification_hint() {
  local agent="$1"
  case "$agent" in
    quant-developer)
      cat <<'EOF'
Run focused quant prompt/guardrail tests touched by the patch. If chart/report behavior changes, also run scripts/validate_report_charts.sh on the generated report used for evidence.
EOF
      ;;
    data-engineer)
      cat <<'EOF'
Run focused data-engineer tests, including prompt composition and factory middleware tests. Also run one backend/tests/runner.py query whose toolbox route selects a narrow provider subset, or explain the concrete credential/network blocker.
EOF
      ;;
    orchestrator)
      cat <<'EOF'
Run focused orchestrator prompt/routing tests, especially intake/toolbox routing tests when provider handoff text changes.
EOF
      ;;
    technical-writer)
      cat <<'EOF'
Run focused technical-writer flow/report validation tests. If charts are involved, validate the report chart contract.
EOF
      ;;
    quality-analyst)
      cat <<'EOF'
Run focused quality-analyst prompt/subagent tests and any fidelity tests touched by the patch.
EOF
      ;;
  esac
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
    printf 'Recent pass summaries from this script run:\n%s' "$context"
  else
    printf 'Recent pass summaries from this script run: none yet.'
  fi
}

write_prompt_file() {
  local prompt_file="$1"
  local target_agent="$2"
  local recent_context="$3"
  local scope_text
  local verify_text
  scope_text="$(allowed_scope "$target_agent")"
  verify_text="$(verification_hint "$target_agent")"

  cat > "$prompt_file" <<PROMPT
Goal: Reduce resident prompt size and context-window pollution by moving rarely needed specialist instructions out of always-on system prompts.

Optimize for two mechanisms:
- Native DeepAgents skill usage for declarative subagents that can safely load focused instructions on demand. The resident prompt should become a compact router/contract that tells the agent when to use skills, while detailed workflows live in the relevant skill files.
- Dynamic prompt injection for runtime-selected behavior that must mirror live routing state. For data-engineer, provider-specific instructions must be appended only for the providers selected by the toolbox for that run, so inactive provider rules do not consume tokens or bias tool calls.

Success criteria:
- The target agent keeps only stable, always-needed rules in its resident prompt.
- Detailed instructions move to skills or runtime-injected sections without changing behavior.
- Active model context contains only instructions relevant to the current agent/run.
- Tests prove migrated details are still present when needed and absent when not needed.

Target agent: $target_agent

$recent_context

Allowed write scope for this pass:
$scope_text

Instructions:
1. Inspect the current prompt and skill files for only the target agent.
2. Patch exactly one agent. Do not edit another agent's prompt, skill, or behavior in this pass.
3. Identify which instructions are always-needed contract rules versus conditional workflow detail. Keep the former resident and move the latter into skills or runtime injection.
4. Prefer native DeepAgents skills for declarative subagents that can safely use DeepAgents skill loading. The agent prompt should explicitly tell the model which skills to load for which task shapes, but should not duplicate the full skill content.
5. Keep data-engineer special: its provider instructions must be assembled dynamically at model-call time from the selected toolbox providers, not by native DeepAgents skills. The same selected-provider list must control both visible provider tools and injected provider prompt sections.
6. Avoid token regressions: do not replace one bloated prompt with another bloated prompt in a different file unless that file is loaded conditionally as a skill or only injected for a selected runtime route.
7. Preserve guardrails that prevent bad behavior, but place them at the narrowest safe scope:
   - always-on safety/tool/output contracts stay resident;
   - provider-specific rules belong in provider sections;
   - workflow-specific implementation details belong in skills;
   - test-only or legacy reminders should be removed if covered by focused tests.
8. For data-engineer, explicitly verify all of these if you touch it:
   - selected provider tools and selected provider prompt sections match;
   - unselected provider rules are absent from the active prompt;
   - broad fallback still includes all public providers;
   - one runner query exercises a narrow toolbox route, not only broad fallback.
9. FMP remains disabled and unavailable. Do not add paid/keyed providers or re-enable FMP.
10. Patch only the smallest necessary files and focused tests in the allowed scope.
11. Follow AGENTS.md. Before changes involving the Vercel AI SDK or LangChain DeepAgents, retrieve current documentation with Context7.
12. Run focused verification:
$verify_text
13. Stop after one target-agent pass. Summarize how the patch reduces resident prompt/context size, changed files, tests, and the next agent signal.

Final response requirements:
- Keep the summary concise.
- End with exactly these two lines:
PROMPT_SKILL_RESULT: patched|no_patch|blocked
PROMPT_SKILL_TARGET: $target_agent
PROMPT
}

write_pass_summary() {
  local pass_dir="$1"
  local pass_num="$2"
  local target_agent="$3"
  local start_time="$4"
  local end_time="$5"
  local codex_exit="$6"
  local output_file="$7"
  local summary_file="$pass_dir/summary.md"

  if [[ -s "$output_file" ]]; then
    cp "$output_file" "$pass_dir/codex-summary.md"
  else
    printf 'Codex did not write a non-empty summary for pass %s.\n' "$pass_num" > "$pass_dir/codex-summary.md"
  fi

  {
    printf '# Prompt Skill Loop Pass %s\n\n' "$pass_num"
    printf 'Target agent: %s\n' "$target_agent"
    printf 'Started: %s\n' "$start_time"
    printf 'Ended: %s\n' "$end_time"
    printf 'Codex exit: %s\n' "$codex_exit"
    printf 'Codex summary: %s\n' "$pass_dir/codex-summary.md"
    printf '\n## Codex Summary\n\n'
    cat "$pass_dir/codex-summary.md"
  } > "$summary_file"
}

update_latest_summary() {
  local pass_files
  mapfile -t pass_files < <(find "$RUN_DIR" -maxdepth 2 -type f -name summary.md 2>/dev/null | sort -V)
  {
    printf '# Codex Prompt Skill Loop Summary\n\n'
    printf 'Run: %s\n' "$RUN_ID"
    printf 'Run directory: %s\n' "$RUN_DIR"
    printf 'Updated: %s\n\n' "$(date -Is)"
    printf '## Passes\n\n'
    local file pass
    for file in "${pass_files[@]}"; do
      pass="$(basename "$(dirname "$file")")"
      printf -- '- %s: summary=%s\n' "$pass" "$file"
    done
  } > "$LATEST_SUMMARY"
}

end_iter=$((START_ITER + MAX_ITERS - 1))

printf 'Prompt skill loop run directory: %s\n' "$RUN_DIR"
printf 'Codex model: %s\n' "$CODEX_MODEL"
printf 'Codex reasoning effort: %s\n' "$CODEX_REASONING_EFFORT"
printf 'Agent order: %s\n' "${TARGET_AGENTS[*]}"
printf 'Latest rollup: %s\n' "$LATEST_SUMMARY"

for i in $(seq "$START_ITER" "$end_iter"); do
  target_agent="$(select_agent "$i")"
  output_file="/tmp/codex-prompt-skill-pass-${i}.md"
  pass_dir="$RUN_DIR/pass-${i}-${target_agent}"
  prompt_file="$pass_dir/prompt.txt"
  start_time="$(date -Is)"
  recent_context="$(build_recent_context)"
  mkdir -p "$pass_dir"
  write_prompt_file "$prompt_file" "$target_agent" "$recent_context"

  printf '\n=== Codex prompt/skill pass %s/%s: %s ===\n' "$i" "$end_iter" "$target_agent"
  printf 'Prompt file: %s\n\n' "$prompt_file"

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

  write_pass_summary "$pass_dir" "$i" "$target_agent" "$start_time" "$end_time" "$codex_exit" "$output_file"
  update_latest_summary

  printf '\nCodex pass %s exited with status %s\n' "$i" "$codex_exit"
  printf 'Pass summary: %s\n' "$pass_dir/summary.md"
  printf 'Latest rollup: %s\n' "$LATEST_SUMMARY"
  git status --short
done
