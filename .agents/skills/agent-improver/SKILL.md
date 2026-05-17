---
name: agent-improver
description: >-
  Iteratively improves the Deep Research Agent by executing it, analyzing
  high-signal trace artifacts, and patching the source code. Each outer-loop iteration
  runs in a fresh Codex process so context is cleared between test runs.
---

# Agent Improvement Loop

This skill guides the process of self-improving the Deep Research Agent codebase. Follow this iterative cycle precisely.

## 1. Execution Phase

Invoke the agent using the simplified test runner. This script executes the LangGraph pipeline, emits runner-observed spans, and writes Phoenix trace artifacts to the output directory.

To push the agent to its limits, use macro-economic queries that require fetching and correlating multiple data series from FRED. Use a different prompt every iteration, varying complexity, ambiguity, and the number of required FRED series.

**Prompt Rotation Rules:**
- Do not repeat the same query in consecutive iterations.
- Prefer FRED-only macro questions while FMP is disabled.
- Rotate across easy, medium, complex, and ambiguous questions.
- Include occasional underspecified prompts to test intake clarification and approval behavior.
- Include occasional highly specific prompts to test direct execution behavior.
- When using a shell loop, pass the selected query into `tests/runner.py --query`.

**Example Query Bank:**

Easy / direct:
> "Compare US headline CPI inflation, core CPI inflation, and the effective federal funds rate since 2000. Identify periods where policy rates lagged inflation inflections. Use FRED for all data series."

Easy / ambiguous:
> "Is the US labor market weakening right now? Use FRED data and explain what changed across the last few years."

Medium / direct:
> "Analyze the relationship between the US unemployment rate, labor force participation rate, and real average hourly earnings since 1990. Identify whether tight labor markets consistently translated into real wage gains. Use FRED for all data series."

Medium / ambiguous:
> "Are consumers under stress? Use FRED macro data to build a concise evidence-based answer."

Complex / direct:
> "Analyze the relationship between the US 10-year minus 3-month Treasury yield spread, the US unemployment rate (3-month moving average vs 12-month low - Sahm Rule), and the Real Industrial Production Index over the last 40 years. Identify leading indicator patterns across the last 5 recessions. Use FRED for all data series."

Complex / ambiguous:
> "Build a recession risk dashboard from FRED using rates, labor, credit, output, and inflation indicators. Decide which series are appropriate, justify the choices, and identify current risks versus prior cycles."

Complex / regime comparison:
> "Compare the inflation-growth-policy mix in the 1970s, the 2001 recession, the 2008 financial crisis, the COVID shock, and the latest post-pandemic cycle. Use FRED series for inflation, unemployment, real output, industrial production, and policy rates."

Stress / broad but FRED-only:
> "Investigate whether the US economy is showing a soft landing, hard landing, or reacceleration pattern. Use at least six FRED macro series spanning labor, inflation, rates, credit, output, and consumption."

```bash
# Run from the backend directory
python tests/runner.py \
  --max-runtime-seconds 2400 \
  --max-tool-calls 300 \
  --max-identical-tool-calls 25 \
  --max-fred-search-calls 100 \
  --max-model-messages 5000 \
  --query "Analyze the relationship between the US 10-year minus 3-month Treasury yield spread, the US unemployment rate (3-month moving average vs 12-month low - Sahm Rule), and the Real Industrial Production Index over the last 40 years. Identify leading indicator patterns across the last 5 recessions. Use FRED for all data series."
```

The runner will output the path to `trace-digest.md` (e.g., `outputs/improver-xxxx/trace-digest.md`). It traces intake behavior, auto-approval, forced execution, model messages, tool calls/results, updates, stream errors, watchdog stops, fatal errors, and artifact discovery. Read trace artifacts in this order:

1. `trace-digest.md`
2. `trace_diagnostics.json`
3. `phoenix_spans.jsonl`
4. Report artifacts, if present

Treat the digest's primary trace signal and diagnostics as the highest-priority improvement evidence. Final improver summaries must name the trace signal that drove the patch, such as repeated tool loop, slow node, failed handoff, retry churn, or shallow artifact generation.

## 2. Analysis Phase

Read `trace-digest.md`, then `trace_diagnostics.json`, then `phoenix_spans.jsonl`. Focus on:
- **Tool Selection**: Did it use the right tool for the job?
- **Logic Flow**: Did it loop unnecessarily, retry churn, hit a watchdog stop, or get stuck in a slow node?
- **Subagent Delegation**: Was the task description given to the subagent clear and effective?
- **Errors**: Identify any crashes or incorrect tool outputs.

Filter out noise. Look for the "trip-up" points where performance or accuracy degraded.

## 3. Planning and Build Phase

Based on the analysis, choose the best root-cause fix for the agent system. Do not optimize for minimal diff size, and do not default to editing `orchestrator.py` when the trace points to a specialist prompt, tool contract, skill file, MCP wrapper, or report artifact behavior. A larger coherent refactor is the right fix when it removes brittle routing, retry churn, duplicated prompt/tool rules, prompt bloat, unclear specialist ownership, or artifact contract drift.

When invoked by `scripts/codex_improve_loop.sh`, improve mode is split across two fresh Codex phases:

- `improve-plan`: run the selected agent query, inspect trace artifacts/report artifacts and recent pass summaries, choose a root-cause implementation plan, and make no code changes.
- `improve-build`: start in a separate fresh Codex process, read the plan summary plus query/trace paths and recent pass summaries, then implement the planned root-cause fix with focused verification.

Anti-workaround policy:
- Do not add broad phrase-matching tables, magic prompt strings, ad hoc substring catch-alls, one-off branches for a single trace wording, or prompt-only workarounds when a typed contract, schema, validator, tool result, state field, or clearer ownership boundary would solve the class of failure.
- Prefer structured contracts over prose inference: typed JSON payloads, explicit tool return fields, deterministic validators, named failure categories, and handoff schemas should carry routing and recovery decisions.
- If existing heuristic debt is on the direct path, either replace it with a structured contract as part of the fix or explicitly document why it is out of scope and what cleanup signal should trigger removal.
- Before finalizing a build, self-review the diff for workaround smells and state why the patch is a root-cause fix rather than another layer of brittle special cases.

High-value improvement surfaces:
- `backend/agents/orchestrator.py`: Pipeline sequencing, approval/execution routing, retry behavior, final-stop behavior, top-level delegation instructions, artifact handoff rules, and chat updates.
- `backend/agents/subagents_registry.py`: Specialist registration, names, descriptions, model assignment, and whether the orchestrator can discover the right delegate.
- `backend/agents/data_engineer/`: FRED MCP loading, data-fetch prompt behavior, tool availability, result persistence, schema extraction, MCP retry/timeout handling, and context-bloat prevention.
- `backend/agents/quantitative_developer.py`: Code-generation instructions, analysis workflow, chart/report artifact handoff, sandbox assumptions, and how it consumes data-engineer outputs.
- `backend/agents/technical_writer/`: Report synthesis, schema validation, `report.json`/`charts.json` production, citation/source handling, and recovery from malformed artifacts.
- `backend/agents/quality_analyst.py`: QA acceptance criteria, rejection specificity, artifact validation, and whether feedback is actionable for the writer/quant/data agents.
- `backend/agents/*/tools.py` and `backend/agents/report_artifacts.py`: Tool names, docstrings, argument schemas, return payloads, error shape, and whether tool outputs are compact and easy for agents to act on.
- `backend/skills/orchestrator/*.md`: Workflow-specific guidance for macro, equity, sector, path/artifact handling, QA recovery, and delegation recipes.
- `backend/skills/data-engineer/*.md`: FRED workflow guidance, MCP error recovery, source selection, fetch limits, and saved-data conventions.
- `backend/skills/quant-developer/*.md`: Sandbox usage, code execution recovery, chart generation, and reusable helper composition.
- `backend/skills/technical-writer/*.md`: Report-writing style, report shape, source usage, and domain-specific synthesis guidance.
- `backend/mcp_clients/` and `backend/agents/data_engineer/mcp_wrappers.py`: MCP client configuration, timeout budgets, result compaction, error normalization, retries, and provider-specific tool quirks.
- `backend/.env.example`, `backend/core/config.py`, and startup/lifespan wiring: Optional integration flags, disabled-by-default providers, and clear local setup documentation.
- `backend/tests/runner.py`: Trace fidelity and watchdog budgets when the improver needs better visibility or faster early stops.

Patch categories to consider:
- **Delegation:** Make task descriptions more self-contained, include absolute paths, expected output shapes, retry limits, and clear ownership boundaries between specialists.
- **Skill use:** Move reusable workflow rules into `backend/skills/...` when they are domain/process guidance rather than Python behavior. Keep prompts concise and let skills carry detailed procedures.
- **Tool design:** Improve tool names, docstrings, schemas, validation, return payloads, and errors so agents can recover without guessing. Prefer structured JSON outputs with status, paths, metadata, and actionable error messages.
- **MCP use:** Reduce redundant searches, enforce fetch budgets, normalize provider errors, compact large payloads, save raw data out of context, and make retry behavior explicit.
- **Free integration expansion:** If report quality is limited by missing context, citations, validation, visualization, or public reference data, consider adding a new optional MCP or tool only when it is free, requires no API key, requires no signup, and has little overlap with existing FRED/local capabilities.
- **State and artifacts:** Fix missing or ambiguous handoffs between `data_files`, schemas, generated code, charts, `report.json`, `charts.json`, and QA feedback.
- **Loop control:** Add or tune stop conditions when the trace shows repeated tool calls, repeated delegation, post-approval drift, or final-answer churn.
- **Model/prompt behavior:** Tighten role boundaries, remove contradictory instructions, clarify when to ask for clarification versus proceed, and make final-stop conditions explicit.
- **Tests:** Add focused tests for deterministic logic, tool wrappers, report validation, artifact handling, or watchdog behavior when the patch changes behavior that can be tested without a full external MCP run.

Free integration rules:
- Before adding an integration, inspect existing tools, MCP clients, and skills to confirm the capability is not already covered by FRED, the disabled FMP path, local shell/code execution, report validation, or existing artifact tools.
- Allowed integrations must be free to use without an account, signup, API key, paid plan, OAuth flow, or manually provisioned cloud resource.
- Prefer local/open-source tools, public no-key HTTP endpoints, local file parsers, validators, chart helpers, citation/source checkers, or MCP servers that run locally without credentials.
- Do not add required startup dependencies for optional integrations. Missing binaries, network failures, unavailable MCP servers, or unsupported platforms must degrade gracefully with a clear disabled-tool message.
- Do not re-enable FMP, add a paid-gated provider, or introduce a provider that requires credentials. If such a provider would help, document it as a future optional idea only; do not wire it into the active agent flow.
- Prefer a thin client module under `backend/mcp_clients/` or a narrowly scoped specialist tool over embedding provider-specific behavior in prompts.
- Register each new tool only with the specialist that owns it. Data/source retrieval belongs in data-engineer, artifact checks belong near technical-writer or quality-analyst, and computation/chart helpers belong with quantitative-developer.
- Give every new tool a precise name, short docstring, typed arguments, compact structured return payload, timeout/error handling, and tests for unavailable-provider behavior.
- Update relevant `backend/skills/...` files so agents know when to use the integration, when not to use it, call budgets, fallback behavior, and expected output shape.
- Add focused tests that do not require live credentials or paid services. Mock network/MCP responses where possible.

Prefer one coherent root-cause fix per iteration. If the failure is caused by missing external credentials or provider availability, improve diagnosis and graceful handling rather than inventing data or broadening scope.

## Refactor Mode

Use `scripts/codex_refactor_loop.sh` for dedicated backend quant helper-library cleanup. This loop is static-first: normal passes do not run the research agent, do not start Phoenix, and do not inspect a fresh trace. It has one standing goal: the backend quant library must expose reusable helper functions only.

Each outer iteration has fresh Codex phases:

- `helper-plan`: static inspection only. Run banned-pattern searches, inventory canned report surfaces, and choose one coherent cleanup target. Make no code changes.
- `helper-build`: fresh Codex context. Delete or rewrite the selected canned surface, modularize reusable internals, and update directly related prompts/tests.
- `helper-review`: fresh Codex context. Perform a read-only review of diff, tests, scope, and actual canned-surface reduction.
- `helper-fix`: fresh Codex context. Resolve only review findings, then re-review.

If `helper-review` returns `changes_requested`, the shell loop starts a fresh `helper-fix` phase, then reruns `helper-review` against the fixed diff. It repeats this fix-and-review cycle until review returns `approved` or the bounded fix attempts are exhausted.

Every helper-cleanup pass must reject reintroducing public `build_*_outputs` helpers, `build_*_artifacts` tools, deterministic artifact registries, deterministic chart packs, query-marker report routing, exact company/recession/macro-cycle contracts, or prompt language saying a report-specific tool must run before `analysis.py`.

Target selection prioritizes high-impact helper-library outcomes: reduced canned surface area, fewer duplicated helper paths, clearer public helper APIs, smaller prompts/tool contracts, less generated-script burden, deleted obsolete functions, and fewer one-off report branches. Prefer reusable library functions and stable public APIs over another specialized chart helper branch. Do not choose a tiny helper extraction when the static evidence supports collapsing a larger duplicated family.

Refactor mode is intentionally aggressive. A refactor may split modules, move code, consolidate duplicate rules, delete dead code, reshape file structure, and adjust or delete brittle tests when behavior coverage remains. It is acceptable to remove, replace, or reshape existing internal functionality when a cleaner reusable design provides better functionality. If five narrow helpers can become one reusable helper/API, do that and migrate callers instead of preserving five old paths. Compatibility shims are debt unless they protect a documented external contract.

Tests may be deleted completely when they only preserve hacky, brittle, overfit, obsolete, or superseded functionality. Replace deleted tests only when the behavior is still valuable under the cleaner design. Tests that assert old private structure should be rewritten or deleted when the structure is superseded by a better API.

The review phase must return `changes_requested` for scope drift, tiny-refactor behavior, new hacky helpers, prompt-only workarounds, canned API compatibility shims, preserved query-specific routing, preserved exact-report gates, unjustified preservation of obsolete tests, deletion of meaningful coverage for behavior the system still promises, missing coverage for still-promised behavior, or no measurable cleanup. Review should reject test deletion only when it removes meaningful promised-behavior coverage under the cleaner design. The fix phase must address those review findings substantively, including migrating more callers or deleting the obsolete path when the first build preserved too much legacy shape.

Focused static and unit checks come first. After several approved static passes, run one realistic agent validation only to confirm the agent still creates reports from generated `analysis.py`.

Pass summaries must include target, files changed, before/after metric when practical, functions/behaviors removed or intentionally changed, tests deleted or changed, tests run, review result, and whether agent validation was run or skipped.

End helper-build summaries with:

```text
HELPER_BUILD_RESULT: patched|no_patch|blocked
HELPER_TARGET: <short target name>
HELPER_NEXT_SIGNAL: <one short sentence>
```

End helper-review summaries with:

```text
HELPER_REVIEW_RESULT: approved|changes_requested|blocked
HELPER_REVIEW_FINDINGS: <short finding summary>
```

## 4. Iteration & Context Management

Repeat the cycle: **Execute -> Analyze -> Patch**.

When invoked by `scripts/codex_improve_loop.sh` in improve mode, each iteration
starts one `improve-plan` Codex process and one fresh `improve-build` Codex
process. Treat each process boundary as a context reset. Do not stop merely
because the current Codex context is past 50%; finish the current phase,
summarize the plan or patch, and exit so the next phase starts with clean
context.

Do not loop multiple test runs inside one Codex session. The outer shell script
owns repetition. In improve mode, `improve-plan` owns exactly one agent test
run and no code changes; `improve-build` owns one coherent root-cause
implementation and focused verification. In static refactor mode,
`refactor-plan` owns static inspection only, `refactor-build` owns one coherent
refactor and focused verification, `refactor-review` owns read-only review plus
the review-controlled validation checkpoint when due, and `refactor-fix` owns
only the bounded changes needed to satisfy review findings before re-review.
