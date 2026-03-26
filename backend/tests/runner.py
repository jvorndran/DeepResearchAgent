"""
Streaming Test Runner for the Deep Research Agent pipeline.

Runs research queries against the orchestrator and prints every agent event
in real-time. Events are also saved to outputs/{job_id}/events.jsonl for
post-run inspection.

Usage (from backend/ directory):
    python tests/runner.py --query "Show me Apple's (AAPL) annual revenue over the last 10 years."
    python tests/runner.py --tier 1
    python tests/runner.py --query "..." --no-stream
"""

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow running from backend/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

# Ensure stdout/stderr handle Unicode on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# =============================================================================
# TIER QUERIES
# =============================================================================

TIER_QUERIES: Dict[int, List[str]] = {
    1: [
        "Show me Apple's (AAPL) annual revenue over the last 5 years.",
        "What has been Amazon's (AMZN) gross margin trend over the last 5 years?",
        "Give me a breakdown of Microsoft's (MSFT) current assets vs. current liabilities for the last 5 years.",
        "Compare the net income of Apple (AAPL) and Microsoft (MSFT) over the last 5 years.",
    ],
    2: [
        "Compare the trailing P/E ratios of NVIDIA (NVDA), AMD, and Intel (INTC) over the last 3 years.",
        "Which of the major hyperscalers — Microsoft, Google, Amazon, and Meta — has grown capital expenditure the fastest since 2020?",
        "Compare return on equity (ROE) for JPMorgan (JPM), Bank of America (BAC), and Goldman Sachs (GS) from 2018 to 2024.",
    ],
    3: [
        "What is the correlation between TSMC's annual CapEx spending and global semiconductor equipment shipment volumes over the last 10 years?",
        "How correlated is the 10-year US Treasury yield with the S&P 500 P/E ratio since 2000?",
        "Analyze the correlation between WTI crude oil prices and ExxonMobil's (XOM) free cash flow from 2010 to 2024.",
        "What is the relationship between US CPI inflation (from FRED) and the revenue growth of major US consumer discretionary companies (AMZN, TGT, WMT) since 2018?",
    ],
    4: [
        "Generate a research report on the investment case for ASML. Include revenue growth, net margin trends, R&D spending as a percentage of revenue, and its position in the EUV lithography market.",
        "Analyze NVIDIA's revenue growth by segment since 2020, with a focus on the Data Center segment. How does its growth rate compare to its gross margin expansion?",
        "Using FRED data, analyze the relationship between the US yield curve (10Y-2Y spread) and subsequent S&P 500 returns. Has an inverted yield curve historically predicted recessions?",
        "Compare the capital allocation strategies of ExxonMobil and NextEra Energy from 2015 to 2024. How have their CapEx, R&D, and dividend profiles diverged as energy transition accelerates?",
    ],
    5: [
        "Tell me about tech stocks.",
        "What is the correlation between US housing starts (FRED) and Home Depot's (HD) same-store sales growth?",
        "Plot the S&P 500 price-to-book ratio from 1990 to present alongside US 10-year real interest rates.",
        "Create a dashboard showing US GDP growth, unemployment rate, CPI, and the Fed Funds Rate together from 2000 to present, highlighting recession periods.",
        "Is there a leading indicator relationship between the ISM Manufacturing PMI (FRED) and the earnings growth of S&P 500 industrials? Analyze the last 15 years.",
    ],
}


# =============================================================================
# EVENT FORMATTING
# =============================================================================

PREVIEW_LEN = 120


def _truncate(s: str, n: int = PREVIEW_LEN) -> str:
    s = str(s).replace("\n", " ").strip()
    return s[:n] + "..." if len(s) > n else s


def _args_preview(tool_calls: list) -> str:
    if not tool_calls:
        return ""
    tc = tool_calls[0]
    name = tc.get("name", "?")
    args = tc.get("args", {})
    args_str = ", ".join(f"{k}={repr(v)}" for k, v in list(args.items())[:3])
    if len(args) > 3:
        args_str += ", ..."
    return f"{name}({args_str})"


def format_event(event: Dict[str, Any], elapsed: float) -> List[Dict[str, Any]]:
    """
    Parse a LangGraph stream_mode='updates' event into printable lines.
    Returns a list of dicts: {label, node, text, elapsed, raw}
    """
    lines = []
    ts = f"[{elapsed:5.1f}s]"

    for node_name, state_update in event.items():
        if not isinstance(state_update, dict):
            lines.append({
                "label": "EVENT",
                "node": node_name,
                "text": f"{node_name}: {_truncate(state_update)}",
                "elapsed": elapsed,
                "raw": event,
            })
            continue

        raw_messages = state_update.get("messages", [])
        # LangGraph sometimes wraps list values in an Overwrite object (has .value attr)
        if hasattr(raw_messages, "value"):
            raw_messages = raw_messages.value
        messages = raw_messages if isinstance(raw_messages, (list, tuple)) else []
        if not messages:
            # No messages — just log the raw update keys
            lines.append({
                "label": "EVENT",
                "node": node_name,
                "text": f"{node_name}: {_truncate(list(state_update.keys()))}",
                "elapsed": elapsed,
                "raw": event,
            })
            continue

        for msg in messages:
            msg_type = type(msg).__name__

            if msg_type == "AIMessage":
                tool_calls = getattr(msg, "tool_calls", []) or []
                if tool_calls:
                    lines.append({
                        "label": "TOOL CALL",
                        "node": node_name,
                        "text": _args_preview(tool_calls),
                        "elapsed": elapsed,
                        "raw": event,
                    })
                else:
                    content = getattr(msg, "content", "") or ""
                    lines.append({
                        "label": "MESSAGE",
                        "node": node_name,
                        "text": f"{node_name}: {_truncate(content)}",
                        "elapsed": elapsed,
                        "raw": event,
                    })

            elif msg_type == "ToolMessage":
                tool_name = getattr(msg, "name", "?")
                content = getattr(msg, "content", "") or ""
                lines.append({
                    "label": "TOOL RESULT",
                    "node": node_name,
                    "text": f"{tool_name} → {_truncate(content)}",
                    "elapsed": elapsed,
                    "raw": event,
                })

            else:
                content = getattr(msg, "content", str(msg)) or str(msg)
                lines.append({
                    "label": "EVENT",
                    "node": node_name,
                    "text": f"{node_name}: {_truncate(content)}",
                    "elapsed": elapsed,
                    "raw": event,
                })

    return lines


def print_event_line(line: Dict[str, Any]) -> None:
    label = line["label"]
    elapsed = line["elapsed"]
    text = line["text"]
    label_col = f"[{label}]"
    print(f" [{elapsed:5.1f}s] {label_col:<14} {text}")


def serialize_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Make event JSON-serializable."""
    def _convert(obj: Any) -> Any:
        if hasattr(obj, "__dict__"):
            return {"__type__": type(obj).__name__, **{k: _convert(v) for k, v in obj.__dict__.items()}}
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_convert(i) for i in obj]
        try:
            json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return str(obj)
    return _convert(event)


# =============================================================================
# OUTPUT DIRECTORY
# =============================================================================

def get_output_dir(job_id: str) -> Path:
    output_base = Path(os.getenv("OUTPUT_DIR", str(Path(__file__).resolve().parent.parent / "outputs")))
    output_dir = output_base / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def check_artifacts(output_dir: Path) -> Dict[str, str]:
    artifacts = {}
    for name in ["report.json", "charts.json", "events.jsonl", "run_summary.json"]:
        path = output_dir / name
        if path.exists():
            size = path.stat().st_size
            artifacts[name] = f"FOUND ({size:,} bytes)"
        else:
            artifacts[name] = "NOT FOUND"
    return artifacts


# =============================================================================
# STREAMING RUN
# =============================================================================

async def run_streaming(query: str, job_id: str) -> Dict[str, Any]:
    from agents.orchestrator import stream_research

    output_dir = get_output_dir(job_id)
    events_file = output_dir / "events.jsonl"

    print("=" * 70)
    print(f"  Job ID : {job_id}")
    print(f"  Query  : {query}")
    print("=" * 70)

    start = time.monotonic()
    event_count = 0
    status = "unknown"
    error: Optional[str] = None

    print(f" [ 0.0s] [START]        Orchestrator initializing...")

    try:
        with open(events_file, "w", encoding="utf-8") as ef:
            async for event in stream_research(query=query, job_id=job_id):
                elapsed = time.monotonic() - start
                event_count += 1

                # Write full event to JSONL
                safe_event = serialize_event(event)
                safe_event["_elapsed"] = elapsed
                ef.write(json.dumps(safe_event) + "\n")
                ef.flush()

                # Parse and print event lines
                lines = format_event(event, elapsed)
                for line in lines:
                    print_event_line(line)

        status = "completed"
    except Exception as e:
        elapsed = time.monotonic() - start
        error = str(e)
        status = "failed"
        print(f" [{elapsed:5.1f}s] [ERROR]        {error}")

    elapsed_total = time.monotonic() - start
    print(f" [{elapsed_total:5.1f}s] [COMPLETE]     Status: {status}")

    # Save run summary
    summary = {
        "query": query,
        "job_id": job_id,
        "status": status,
        "elapsed_seconds": round(elapsed_total, 2),
        "event_count": event_count,
        "error": error,
    }
    (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # Print artifact summary
    artifacts = check_artifacts(output_dir)
    print("=" * 70)
    print("  Artifacts:")
    for name, status_str in artifacts.items():
        print(f"    {name:<20}: {status_str}")
    print("=" * 70)

    return summary


# =============================================================================
# NON-STREAMING RUN
# =============================================================================

async def run_simple(query: str, job_id: str) -> Dict[str, Any]:
    from agents.orchestrator import run_research

    output_dir = get_output_dir(job_id)

    print("=" * 70)
    print(f"  Job ID : {job_id}")
    print(f"  Query  : {query}")
    print("  Mode   : non-streaming")
    print("=" * 70)

    start = time.monotonic()
    result = await run_research(query=query, job_id=job_id)
    elapsed = time.monotonic() - start

    status = result.get("status", "unknown")
    error = result.get("error")
    response = result.get("response", "")

    if response:
        print(f"\n{response}\n")
    if error:
        print(f"[ERROR] {error}")

    print(f"Status: {status} ({elapsed:.1f}s)")

    summary = {
        "query": query,
        "job_id": job_id,
        "status": status,
        "elapsed_seconds": round(elapsed, 2),
        "error": error,
    }
    (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    artifacts = check_artifacts(output_dir)
    print("=" * 70)
    print("  Artifacts:")
    for name, status_str in artifacts.items():
        print(f"    {name:<20}: {status_str}")
    print("=" * 70)

    return summary


# =============================================================================
# MAIN
# =============================================================================

def make_job_id() -> str:
    return "test-" + uuid.uuid4().hex[:8]


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Streaming test runner for the Deep Research Agent pipeline."
    )
    parser.add_argument("--query", type=str, help="Run a specific query.")
    parser.add_argument(
        "--tier",
        type=int,
        choices=list(TIER_QUERIES.keys()),
        help="Run all predefined Tier-N queries sequentially.",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Fall back to run_research() for simpler (non-streaming) output.",
    )
    args = parser.parse_args()

    if not args.query and args.tier is None:
        parser.error("Provide --query or --tier.")

    queries: List[str] = []
    if args.query:
        queries = [args.query]
    elif args.tier is not None:
        queries = TIER_QUERIES[args.tier]

    runner = run_simple if args.no_stream else run_streaming

    for i, query in enumerate(queries):
        if len(queries) > 1:
            print(f"\n{'#' * 70}")
            print(f"  Query {i + 1}/{len(queries)}")
            print(f"{'#' * 70}")

        job_id = make_job_id()
        summary = await runner(query=query, job_id=job_id)

        if summary.get("status") == "failed" and len(queries) > 1:
            print(f"  [WARN] Query failed — continuing with next query.")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
