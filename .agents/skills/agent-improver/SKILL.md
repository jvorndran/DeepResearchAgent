---
name: agent-improver
description: >-
  Iteratively improves the Deep Research Agent by executing it, analyzing
  high-signal logs, and patching the source code. Maintains a context-aware
  loop that stops when the context window reaches 50%.
---

# Agent Improvement Loop

This skill guides the process of self-improving the Deep Research Agent codebase. Follow this iterative cycle precisely.

## 1. Execution Phase

Invoke the agent using the simplified test runner. This script executes the LangGraph pipeline and writes a high-signal log to the output directory.

To push the agent to its limits, use complex macro-economic queries that require fetching and correlating multiple data series from FRED.

**Example Complex Query:**
> "Analyze the relationship between the US 10-year minus 3-month Treasury yield spread, the US unemployment rate (3-month moving average vs 12-month low - Sahm Rule), and the Real Industrial Production Index over the last 40 years. Identify leading indicator patterns across the last 5 recessions. Use FRED for all data series."

```bash
# Run from the backend directory
python tests/runner.py --query "Analyze the relationship between the US 10-year minus 3-month Treasury yield spread, the US unemployment rate (3-month moving average vs 12-month low - Sahm Rule), and the Real Industrial Production Index over the last 40 years. Identify leading indicator patterns across the last 5 recessions. Use FRED for all data series."
```

The runner will output the path to `agent_execution.log` (e.g., `outputs/improver-xxxx/agent_execution.log`).

## 2. Analysis Phase

Read the `agent_execution.log` file. Focus on:
- **Tool Selection**: Did it use the right tool for the job?
- **Logic Flow**: Did it loop unnecessarily or get stuck?
- **Subagent Delegation**: Was the task description given to the subagent clear and effective?
- **Errors**: Identify any crashes or incorrect tool outputs.

Filter out noise. Look for the "trip-up" points where performance or accuracy degraded.

## 3. Patching Phase

Based on the analysis, modify the agent's core logic. Key files are likely in:
- `backend/agents/orchestrator.py` (Graph logic, planning, delegation)
- `backend/agents/data_engineer/`, `backend/agents/quantitative_developer.py`, etc. (Subagent specific logic and prompts)
- `backend/mcp_clients/` (Tool interaction logic)

Apply surgical improvements to prompts, state management, or tool definitions.

## 4. Iteration & Context Management

Repeat the cycle: **Execute -> Analyze -> Patch**.

**CRITICAL**: You must monitor your own context usage.
1. Estimate your current token count/context usage.
2. If you estimate you are approaching **50% of your total context window**, stop the loop immediately.
3. Provide a detailed summary of all improvements made and the current state of the agent before ending the task.

Do not continue past 50% context window to ensure you have enough space to provide a final, high-quality summary and handle any final user directives.
