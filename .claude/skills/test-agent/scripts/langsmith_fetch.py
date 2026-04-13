"""
LangSmith Trace Fetcher

Fetches recent agent runs from LangSmith and prints a readable trace tree,
including subagent internals that don't appear in the streaming runner output.

Usage (from backend/ directory):
    python tools/langsmith_fetch.py                    # last 1 run
    python tools/langsmith_fetch.py --last 3           # last 3 runs
    python tools/langsmith_fetch.py --run-id <id>      # specific run by ID
    python tools/langsmith_fetch.py --project macro-agent --last 1
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Script lives at .claude/skills/test-agent/scripts/ — repo root is 5 levels up
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_BACKEND = _REPO_ROOT / "backend"
sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv
load_dotenv(_BACKEND / ".env")

# Ensure stdout handles Unicode on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

INDENT = "  "
PREVIEW = 200


def _trunc(s: str, n: int = PREVIEW) -> str:
    s = str(s).replace("\n", " ").strip()
    return s[:n] + "..." if len(s) > n else s


def _ts(dt: Optional[datetime]) -> str:
    if not dt:
        return "?"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%H:%M:%S")


def _elapsed(start: Optional[datetime], end: Optional[datetime]) -> str:
    if not start or not end:
        return "?"
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    secs = (end - start).total_seconds()
    return f"{secs:.1f}s"


def _status_icon(run: Any) -> str:
    if getattr(run, "error", None):
        return "[ERROR]"
    status = getattr(run, "status", "") or ""
    if status == "success":
        return "[OK]   "
    if status == "error":
        return "[ERROR]"
    return "[?]    "


# ---------------------------------------------------------------------------
# Tree printer
# ---------------------------------------------------------------------------

def print_run_tree(run: Any, depth: int = 0, client: Any = None) -> None:
    """Recursively print a run and its children."""
    prefix = INDENT * depth
    name = getattr(run, "name", "?") or "?"
    run_type = getattr(run, "run_type", "") or ""
    status = _status_icon(run)
    start = getattr(run, "start_time", None)
    end = getattr(run, "end_time", None)
    elapsed = _elapsed(start, end)
    error = getattr(run, "error", None)

    # Header line
    print(f"{prefix}{status} [{run_type:8}] {name}  ({elapsed})")

    # Inputs summary
    inputs = getattr(run, "inputs", {}) or {}
    if inputs:
        # For tool runs, show the key inputs
        if run_type == "tool":
            inp_str = _trunc(json.dumps(inputs, default=str))
            print(f"{prefix}{INDENT}in : {inp_str}")
        elif run_type == "llm":
            msgs = inputs.get("messages", [])
            if msgs:
                last = msgs[-1] if isinstance(msgs[-1], dict) else str(msgs[-1])
                content = last.get("content", "") if isinstance(last, dict) else str(last)
                print(f"{prefix}{INDENT}in : {_trunc(str(content), 120)}")

    # Outputs / error summary
    if error:
        print(f"{prefix}{INDENT}ERR: {_trunc(str(error), 300)}")
    else:
        outputs = getattr(run, "outputs", {}) or {}
        if outputs and run_type == "tool":
            out_str = _trunc(json.dumps(outputs, default=str))
            print(f"{prefix}{INDENT}out: {out_str}")
        elif outputs and run_type == "llm":
            gens = outputs.get("generations", [[]])
            if gens and gens[0]:
                gen = gens[0][0] if isinstance(gens[0], list) else gens[0]
                text = gen.get("text", "") or gen.get("message", {}).get("content", "") if isinstance(gen, dict) else str(gen)
                if text:
                    print(f"{prefix}{INDENT}out: {_trunc(str(text), 120)}")

    # Children (already fetched on the run object in most cases)
    child_runs = getattr(run, "child_runs", []) or []
    for child in child_runs:
        print_run_tree(child, depth + 1, client)


# ---------------------------------------------------------------------------
# Main fetch logic
# ---------------------------------------------------------------------------

def fetch_and_print(
    project: str,
    last: int = 1,
    run_id: Optional[str] = None,
) -> None:
    try:
        from langsmith import Client
    except ImportError:
        print("ERROR: langsmith package not installed. Run: pip install langsmith")
        sys.exit(1)

    api_key = os.getenv("LANGSMITH_API_KEY")
    if not api_key:
        print("ERROR: LANGSMITH_API_KEY not set in .env")
        sys.exit(1)

    client = Client(api_key=api_key)

    if run_id:
        runs = [client.read_run(run_id)]
    else:
        runs = list(client.list_runs(
            project_name=project,
            is_root=True,
            limit=last,
            order_by="-start_time",
        ))

    if not runs:
        print(f"No runs found in project '{project}'")
        return

    for run in runs:
        start = getattr(run, "start_time", None)
        end = getattr(run, "end_time", None)
        run_id_str = str(getattr(run, "id", "?"))
        status = _status_icon(run)
        elapsed = _elapsed(start, end)
        ts = _ts(start)

        print("=" * 72)
        print(f"  Run ID  : {run_id_str}")
        print(f"  Project : {project}")
        print(f"  Started : {ts}   Elapsed: {elapsed}   {status}")
        query = ""
        inputs = getattr(run, "inputs", {}) or {}
        msgs = inputs.get("messages", [])
        if msgs:
            last_msg = msgs[-1] if isinstance(msgs[-1], dict) else {}
            query = last_msg.get("content", "")[:120] if isinstance(last_msg, dict) else str(msgs[-1])[:120]
        if query:
            print(f"  Query   : {query}")
        print("=" * 72)

        # Fetch full run tree — use list_runs filtered by trace_id (one API call)
        try:
            all_runs = list(client.list_runs(
                project_name=project,
                trace_id=run_id_str,
            ))
            # Build id→run map and attach children
            run_map = {str(r.id): r for r in all_runs}
            for r in all_runs:
                r.child_runs = []
            for r in all_runs:
                pid = str(getattr(r, "parent_run_id", "") or "")
                if pid and pid in run_map:
                    run_map[pid].child_runs.append(r)
            root = run_map.get(run_id_str, run)
            print_run_tree(root, depth=0, client=client)
        except Exception as e:
            print(f"  [WARN] Could not fetch run tree: {e}")
            print_run_tree(run, depth=0, client=client)

        print()

    print(f"View in UI: https://smith.langchain.com/o/default/projects/p/{project}")


def _attach_children(client: Any, run: Any, depth: int = 0, max_depth: int = 6) -> None:
    """Recursively fetch and attach child runs."""
    if depth >= max_depth:
        return
    if not hasattr(run, "child_run_ids") or not run.child_run_ids:
        return
    children = []
    for cid in (run.child_run_ids or []):
        try:
            child = client.read_run(str(cid))
            _attach_children(client, child, depth + 1, max_depth)
            children.append(child)
        except Exception:
            pass
    run.child_runs = children


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch LangSmith traces for agent runs.")
    parser.add_argument("--project", default=os.getenv("LANGSMITH_PROJECT", "macro-agent"),
                        help="LangSmith project name (default: $LANGSMITH_PROJECT or macro-agent)")
    parser.add_argument("--last", type=int, default=1,
                        help="Number of most recent root runs to fetch (default: 1)")
    parser.add_argument("--run-id", default=None,
                        help="Fetch a specific run by ID")
    args = parser.parse_args()

    fetch_and_print(
        project=args.project.strip('"\''),
        last=args.last,
        run_id=args.run_id,
    )


if __name__ == "__main__":
    main()