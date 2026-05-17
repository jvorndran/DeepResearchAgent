#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKLOG_FILE="$REPO_ROOT/docs/free-agent-feature-backlog.md"
REQUESTED_ITERS="${1:-}"
CODEX_SANDBOX_MODE="${CODEX_SANDBOX_MODE:-danger-full-access}"

cd "$REPO_ROOT"

CODEX_MODEL_ARGS=()
if [[ -n "${CODEX_MODEL:-}" ]]; then
  CODEX_MODEL_ARGS=(--model "$CODEX_MODEL")
fi

mapfile -t FEATURE_NAMES < <(awk '/^### / { sub(/^### /, ""); print }' "$BACKLOG_FILE")
if [[ "${#FEATURE_NAMES[@]}" -eq 0 ]]; then
  printf 'No feature headings found in %s\n' "$BACKLOG_FILE" >&2
  exit 1
fi

MAX_ITERS="${REQUESTED_ITERS:-${#FEATURE_NAMES[@]}}"

extract_feature_section() {
  local feature_name="$1"
  awk -v feature="$feature_name" '
    $0 == "### " feature { capture = 1; print; next }
    capture && /^### / { exit }
    capture { print }
  ' "$BACKLOG_FILE"
}

extract_evaluation_query() {
  sed -n 's/^- Evaluation query: //p' | head -1
}

run_codex_phase() {
  local phase_name="$1"
  local output_file="$2"
  local prompt="$3"

  set +e
  codex exec \
    --cd "$REPO_ROOT" \
    --sandbox "$CODEX_SANDBOX_MODE" \
    --output-last-message "$output_file" \
    "${CODEX_MODEL_ARGS[@]}" \
    "$prompt"
  local codex_exit=$?
  set -e

  printf '\nCodex %s exited with status %s\n' "$phase_name" "$codex_exit"
  printf 'Last Codex summary: %s\n' "$output_file"
  return "$codex_exit"
}

for i in $(seq 1 "$MAX_ITERS"); do
  feature_index=$(( (i - 1) % ${#FEATURE_NAMES[@]} ))
  feature_name="${FEATURE_NAMES[$feature_index]}"
  feature_section="$(extract_feature_section "$feature_name")"
  query="$(printf '%s\n' "$feature_section" | extract_evaluation_query)"

  if [[ -z "$query" ]]; then
    printf 'Feature "%s" is missing an "- Evaluation query:" line in %s\n' "$feature_name" "$BACKLOG_FILE" >&2
    exit 1
  fi

  build_output="/tmp/codex-feature-pass-${i}-build.md"
  verify_output="/tmp/codex-feature-pass-${i}-verify.md"
  improve_output="/tmp/codex-feature-pass-${i}-improve.md"

  printf '\n=== Codex feature %s/%s: %s ===\n' "$i" "$MAX_ITERS" "$feature_name"
  printf 'Evaluation query: %s\n\n' "$query"

  build_prompt="$(cat <<EOF
Phase: feature-build

Source of truth:
- Read docs/free-agent-feature-backlog.md.
- Use only the feature section pasted below as the active feature scope.
- Do not use shell-script arrays or prior summaries as the feature spec.

Active feature section:
$feature_section

Goal:
Understand this feature, inspect the existing code, implement the smallest useful slice, and review your own code before stopping.

Instructions:
1. Inspect existing files first so you do not duplicate capabilities already covered by FRED, local quant code, report validation, or existing skills.
2. Implement at most one coherent feature slice.
3. Preserve the frontend intake/approval flow.
4. Free/no-key rules are strict: no API keys, signup, OAuth, paid providers, hosted services, provisioned cloud resources, or FMP re-enable.
5. Prefer local/open-source tools and optional public no-key HTTP clients. Missing dependencies, missing binaries, network failures, and unsupported platforms must degrade gracefully.
6. Add focused tests. Mock network responses for public integrations.
7. Add integration coverage appropriate to the feature:
   - Public no-key HTTP integrations must include mocked unit/contract tests plus a tiny skipped-by-default live smoke test under backend/tests/integration/.
   - Live tests must be gated behind RUN_LIVE_INTEGRATION_TESTS=1, make only one narrow provider call when possible, and assert shape/source metadata rather than exact volatile values.
   - Local analysis features must include realistic fixture-driven integration tests that exercise helper/artifact behavior and assert output schema, method labels, no-lookahead behavior, chart/report compatibility, or QA gates as relevant.
   - If integration coverage is intentionally not added in this slice, state why in the Self-review risks and make it clear the verifier should treat that as an improvement candidate.
8. Perform an in-depth self-review of the patch before stopping:
   - Re-read every file you changed with the final diff in mind.
   - Check that the implementation matches the active markdown feature section and does not quietly broaden scope.
   - Check ownership boundaries: data retrieval belongs to data-engineer, deterministic analysis helpers to quant-developer, report validation to technical-writer/QA, and orchestration only to flow/handoff logic.
   - Check free/no-key constraints again: no API keys, signups, OAuth, paid providers, hosted services, FMP re-enable, secret reads, or mandatory background daemons.
   - Check failure behavior: missing dependency, disabled optional tool, network timeout, malformed provider response, bad user input, and unsupported platform must return compact actionable errors.
   - Check agent ergonomics: tool names, docstrings, schemas, return payloads, and skill guidance should be compact, typed, and easy for the owning specialist to act on.
   - Check artifact contracts: paths, schemas, \`report.json\`, \`charts.json\`, \`execution_summary.json\`, citations, and data-source metadata should remain compatible with downstream agents.
   - Check regressions around frontend intake/approval, FRED-only macro flow, disabled FMP, watchdog limits, and existing focused tests.
   - Check tests for meaningful coverage, including mocked network responses, unavailable-provider behavior, live smoke gating for public integrations, and fixture-driven artifact tests for local analysis.
   - If the review finds a blocker, fix it in this same build phase and rerun focused tests before summarizing.
9. Stop after this build/review phase. Do not run the full research agent in this phase.

Final response requirements:
- Summarize the feature slice added.
- List changed files.
- List tests run.
- Include a short "Self-review" section with issues checked, issues fixed during review, and remaining risks.
- Note any unresolved risks for the verifier.
EOF
)"

  run_codex_phase "feature-build pass $i" "$build_output" "$build_prompt" || true

  verify_prompt="$(cat <<EOF
Phase: feature-verify

This is a fresh Codex session. Do not modify code in this phase.

Source of truth:
- Read docs/free-agent-feature-backlog.md.
- Use only the feature section pasted below as the active feature scope.
- Also read the build summary at $build_output.

Active feature section:
$feature_section

Evaluation query:
$query

Goal:
Run the test agent, explain what new feature appears to have been added to this test agent, and decide whether the feature works or needs improvement.

Instructions:
1. From backend/, run:
   UV_CACHE_DIR=/tmp/uv-cache uv run python tests/runner.py --max-runtime-seconds 2400 --max-tool-calls 300 --max-identical-tool-calls 25 --max-fred-search-calls 100 --max-model-messages 5000 --query "$query"
2. Read the generated outputs/improver-*/trace-digest.md first, then trace_diagnostics.json, phoenix_spans.jsonl, and any report artifacts.
3. Run relevant focused tests added by the build phase. For public no-key HTTP integrations, also run relevant live smoke tests with RUN_LIVE_INTEGRATION_TESTS=1 when they exist. For local analysis features, run fixture-driven integration tests that exercise the real helper/artifact path.
4. If public live smoke tests fail only because of provider/network unavailability while mocked contract tests pass, report that separately; do not confuse provider availability with code correctness.
5. Compare observed agent behavior, mocked tests, and integration tests to the feature acceptance signal in the markdown section.
6. If no meaningful integration test exists for the feature, mark FEATURE_VERDICT: improve unless the build summary gives a defensible reason this first slice could not include one.
7. Do not patch code. This phase verifies only.

Final response requirements:
- Explain the new feature added in plain language.
- State what evidence shows it is working or not working.
- Include the generated trace digest path and the trace signal that drove the verdict.
- End with exactly one line:
  FEATURE_VERDICT: pass
  or
  FEATURE_VERDICT: improve
EOF
)"

  run_codex_phase "feature-verify pass $i" "$verify_output" "$verify_prompt" || true

  verdict="improve"
  if rg -q '^FEATURE_VERDICT: pass$' "$verify_output"; then
    verdict="pass"
  fi

  if [[ "$verdict" == "improve" ]]; then
    improve_prompt="$(cat <<EOF
Phase: feature-improve

This is a fresh Codex session after verifier feedback.

Source of truth:
- Read docs/free-agent-feature-backlog.md.
- Use only the feature section pasted below as the active feature scope.
- Read the build summary at $build_output and verifier summary at $verify_output.

Active feature section:
$feature_section

Evaluation query:
$query

Goal:
Improve the feature based on the verifier result, then stop. Do not move to another feature inside this session.

Instructions:
1. Inspect the verifier summary and generated trace digest path.
2. Patch only the smallest issue that prevented the acceptance signal from being met.
3. Preserve the frontend intake/approval flow.
4. Keep free/no-key constraints strict.
5. Add or update focused tests and the relevant integration tests:
   - Public no-key HTTP integrations need mocked tests plus RUN_LIVE_INTEGRATION_TESTS-gated live smoke tests.
   - Local analysis features need realistic fixture-driven integration tests for helper/artifact behavior.
6. Run focused verification, including integration tests when relevant.

Final response requirements:
- Summarize the improvement.
- List changed files.
- List tests run.
- Note whether another fresh verification pass should be run.
EOF
)"

    run_codex_phase "feature-improve pass $i" "$improve_output" "$improve_prompt" || true
  else
    printf 'Feature "%s" passed verification; moving to next feature with a fresh session.\n' "$feature_name"
  fi

  git status --short
done
