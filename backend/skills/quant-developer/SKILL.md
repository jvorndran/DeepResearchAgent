---
name: quant-developer
description: Compact non-native index for the quant-developer skill source.
---

# Quant Developer Skill Source

This directory is registered as a DeepAgents skill source. Native skills live in
subdirectories, each with its own `SKILL.md`; the root `SKILL.md` is kept only
as a human-readable index and is not part of the DeepAgents metadata scan.

## Native Skills

- `quant-script-workflow`: first-write contract, script budget, broad
  multi-source handling, SEC company-facts use, and artifact handoff rules.
- `quant-sandbox-environment`: sandbox paths, execution command shape, CSV
  loading patterns, FRED notes handling, and provider data format details.
- `quant-macro-helper-workflows`: deterministic macro helper signatures,
  forecast/backtest/regime/scenario/analog routes, and pandas/FRED safety.
- `quant-chart-generation`: canonical Recharts JSON schema and chart output
  constraints.
- `quant-code-execution-errors`: focused traceback repair rules after Python
  execution failures.

Read only the native skill files that match the current task shape.
