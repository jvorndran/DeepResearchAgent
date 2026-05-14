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
"$REPO_ROOT/scripts/audit_report_charts.sh" "$REPORT_PATH"
