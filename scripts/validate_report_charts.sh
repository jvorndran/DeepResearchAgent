#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_PATH="${1:-}"

if [[ -z "$REPORT_PATH" ]]; then
  REPORT_PATH="$(
    find "$REPO_ROOT/backend/outputs" -maxdepth 2 -type f -name report.json -printf '%T@ %p\n' 2>/dev/null \
      | sort -nr \
      | awk 'NR==1 {print $2}'
  )"
fi

if [[ -z "$REPORT_PATH" || ! -f "$REPORT_PATH" ]]; then
  printf 'No report.json found. Pass an explicit report path or generate a report first.\n' >&2
  exit 2
fi
REPORT_PATH="$(cd "$(dirname "$REPORT_PATH")" && pwd)/$(basename "$REPORT_PATH")"

printf 'Validating chart render contract for %s\n' "$REPORT_PATH"
(
  cd "$REPO_ROOT/backend"
  UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}" uv run --extra dev python - "$REPORT_PATH" <<'PY'
import json
import sys

from agents.technical_writer.report_validation import run_report_static_gate

payload = json.loads(run_report_static_gate(sys.argv[1], auto_patch=False))
print(json.dumps(payload.get("chart_render", {}), indent=2))
if not payload.get("passes_gate"):
    print(json.dumps({"blockers": payload.get("blockers", [])}, indent=2), file=sys.stderr)
    raise SystemExit(1)
PY
)

(
  cd "$REPO_ROOT/frontend"
  node node_modules/vitest/vitest.mjs run lib/chart-contract.test.ts
)
