#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_PATH="${1:-}"
FRONTEND_SERVER_PID=""
FRONTEND_SERVER_LOG=""

cleanup() {
  if [[ -n "$FRONTEND_SERVER_PID" ]]; then
    kill "$FRONTEND_SERVER_PID" >/dev/null 2>&1 || true
    wait "$FRONTEND_SERVER_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

is_reachable() {
  local url="$1"
  command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 "$url" >/dev/null 2>&1
}

chart_audit_ports() {
  if [[ -n "${CHART_AUDIT_PORTS:-}" ]]; then
    printf '%s\n' $CHART_AUDIT_PORTS
  else
    printf '%s\n' 3000 3001 3002 3003 3004 3005
  fi
}

discover_frontend_url() {
  local port url
  while IFS= read -r port; do
    [[ -n "$port" ]] || continue
    url="http://localhost:$port"
    if is_reachable "$url"; then
      printf '%s' "$url"
      return 0
    fi
  done < <(chart_audit_ports)
  return 1
}

start_frontend_server() {
  local port url attempt pid log_file
  while IFS= read -r port; do
    [[ -n "$port" ]] || continue
    url="http://localhost:$port"
    if is_reachable "$url"; then
      printf '%s' "$url"
      return 0
    fi

    log_file="${TMPDIR:-/tmp}/chart-audit-next-${port}-$$.log"
    printf 'Starting temporary Next dev server on %s for Cypress chart audit...\n' "$url" >&2
    (
      cd "$REPO_ROOT/frontend"
      node node_modules/next/dist/bin/next dev -p "$port"
    ) >"$log_file" 2>&1 &
    pid=$!

    for attempt in $(seq 1 45); do
      if is_reachable "$url"; then
        FRONTEND_SERVER_PID="$pid"
        FRONTEND_SERVER_LOG="$log_file"
        printf '%s' "$url"
        return 0
      fi
      if ! kill -0 "$pid" >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done

    kill "$pid" >/dev/null 2>&1 || true
    wait "$pid" >/dev/null 2>&1 || true
    printf 'Next dev server did not become reachable on %s. Log: %s\n' "$url" "$log_file" >&2
  done < <(chart_audit_ports)
  return 1
}

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

printf 'Auditing report charts for %s\n' "$REPORT_PATH"
(
  cd "$REPO_ROOT/backend"
  UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}" uv run --extra dev python - "$REPORT_PATH" <<'PY'
import json
import sys

from agents.technical_writer.chart_audit import run_report_chart_audit

payload = json.loads(run_report_chart_audit(sys.argv[1]))
print(json.dumps(payload, indent=2))
if not payload.get("passes_audit"):
    raise SystemExit(1)
PY
)

printf 'Running frontend chart contract tests...\n'
(
  cd "$REPO_ROOT/frontend"
  node node_modules/vitest/vitest.mjs run lib/chart-contract.test.ts
)

CHART_AUDIT_RENDER="${CHART_AUDIT_RENDER:-auto}"
ELECTRON_EXTRA_LAUNCH_ARGS="${ELECTRON_EXTRA_LAUNCH_ARGS:---no-sandbox --disable-dev-shm-usage}"
if [[ -z "${CYPRESS_BASE_URL:-}" ]]; then
  CYPRESS_BASE_URL="$(discover_frontend_url || true)"
fi
if [[ -z "$CYPRESS_BASE_URL" ]]; then
  CYPRESS_BASE_URL="http://localhost:3000"
fi
run_browser_audit=0

case "$CHART_AUDIT_RENDER" in
  0|false|False|FALSE|off|OFF)
    ;;
  1|true|True|TRUE|required|REQUIRED)
    if ! is_reachable "$CYPRESS_BASE_URL"; then
      CYPRESS_BASE_URL="$(start_frontend_server || true)"
    fi
    if [[ -z "$CYPRESS_BASE_URL" ]] || ! is_reachable "$CYPRESS_BASE_URL"; then
      printf 'Cypress chart render audit required, but no frontend dev server is reachable. Checked CHART_AUDIT_PORTS=%s.\n' "${CHART_AUDIT_PORTS:-3000 3001 3002 3003 3004 3005}" >&2
      [[ -n "$FRONTEND_SERVER_LOG" ]] && printf 'Last Next dev log: %s\n' "$FRONTEND_SERVER_LOG" >&2
      exit 1
    fi
    run_browser_audit=1
    ;;
  auto|AUTO)
    if is_reachable "$CYPRESS_BASE_URL"; then
      run_browser_audit=1
    else
      printf 'Skipping Cypress chart render audit because %s is not reachable. Set CHART_AUDIT_RENDER=required to fail instead.\n' "$CYPRESS_BASE_URL"
    fi
    ;;
  *)
    printf 'Unsupported CHART_AUDIT_RENDER=%s. Use auto, required, or false.\n' "$CHART_AUDIT_RENDER" >&2
    exit 2
    ;;
esac

if [[ "$run_browser_audit" -eq 1 ]]; then
  printf 'Running Cypress chart render audit against %s...\n' "$CYPRESS_BASE_URL"
  (
    cd "$REPO_ROOT/frontend"
    ELECTRON_EXTRA_LAUNCH_ARGS="$ELECTRON_EXTRA_LAUNCH_ARGS" \
      CYPRESS_REPORT_JSON_PATH="$REPORT_PATH" \
      CYPRESS_BASE_URL="$CYPRESS_BASE_URL" \
      node node_modules/cypress/bin/cypress run --spec cypress/e2e/chart-render-audit.cy.ts
  )
fi
