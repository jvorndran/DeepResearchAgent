---
name: agent-improver
description: >-
  Iteratively improves the Deep Research Agent by executing it, analyzing
  high-signal logs, and patching the source code. Each outer-loop iteration
  runs in a fresh Codex process so context is cleared between test runs.
---

# Agent Improvement Loop

This skill guides the process of self-improving the Deep Research Agent codebase. Follow this iterative cycle precisely.

## 1. Execution Phase

Invoke the agent using the simplified test runner. This script executes the LangGraph pipeline and writes a high-signal log to the output directory.

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

The runner will output the path to `agent_execution.log` (e.g., `outputs/improver-xxxx/agent_execution.log`). It logs the intake behavior, auto-approves the research gate, and if intake ends without approval it forces execution for improver coverage so ambiguous prompts can still exercise the full data → quant → writer → QA flow. If it sees suspicious behavior, it stops early and writes `WATCHDOG`, `STOPPED_EARLY`, and `STOP_REASON` lines. Treat those lines as the highest-priority improvement signal.

## 2. Analysis Phase

Read the `agent_execution.log` file. Focus on:
- **Tool Selection**: Did it use the right tool for the job?
- **Logic Flow**: Did it loop unnecessarily or get stuck?
- **Subagent Delegation**: Was the task description given to the subagent clear and effective?
- **Errors**: Identify any crashes or incorrect tool outputs.

Filter out noise. Look for the "trip-up" points where performance or accuracy degraded.

## 3. Patching Phase

Based on the analysis, modify the smallest part of the agent system that explains the failure. Do not default to editing `orchestrator.py` when the trace points to a specialist prompt, tool contract, skill file, MCP wrapper, or report artifact behavior.

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
- `backend/skills/quant-developer/*.md`: Sandbox usage, code execution recovery, chart generation, and deterministic artifact creation.
- `backend/skills/technical-writer/*.md`: Report-writing style, report shape, source usage, and domain-specific synthesis guidance.
- `backend/mcp_clients/` and `backend/agents/data_engineer/mcp_wrappers.py`: MCP client configuration, timeout budgets, result compaction, error normalization, retries, and provider-specific tool quirks.
- `backend/.env.example`, `backend/core/config.py`, and startup/lifespan wiring: Optional integration flags, disabled-by-default providers, and clear local setup documentation.
- `backend/tests/runner.py`: Logging fidelity and watchdog budgets when the improver needs better visibility or faster early stops.

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
- Register each new tool only with the specialist that owns it. Data/source retrieval belongs in data-engineer, deterministic artifact checks belong near technical-writer or quality-analyst, and computation/chart helpers belong with quantitative-developer.
- Give every new tool a precise name, short docstring, typed arguments, compact structured return payload, timeout/error handling, and tests for unavailable-provider behavior.
- Update relevant `backend/skills/...` files so agents know when to use the integration, when not to use it, call budgets, fallback behavior, and expected output shape.
- Add focused tests that do not require live credentials or paid services. Mock network/MCP responses where possible.

Apply surgical improvements only. Prefer one coherent fix per iteration. If the failure is caused by missing external credentials or provider availability, improve diagnosis and graceful handling rather than inventing data or broadening scope.

## 4. Iteration & Context Management

Repeat the cycle: **Execute -> Analyze -> Patch**.

When invoked by `scripts/codex_improve_loop.sh`, each iteration starts a new
`codex exec` process. Treat that process boundary as the context reset. Do not
stop merely because the current Codex context is past 50%; finish the current
single execute-analyze-patch cycle, summarize the patch, and exit so the next
outer-loop iteration starts with a clean context.

Do not loop multiple test runs inside one Codex session. The outer shell script
owns repetition; the Codex agent owns exactly one test run, one analysis, one
coherent patch, and focused verification.
