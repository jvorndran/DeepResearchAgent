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
import logging
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow running from backend/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))

# Suppress cosmetic MCP session-termination warnings (servers return 400 on DELETE)
logging.getLogger("mcp.client.streamable_http").setLevel(logging.ERROR)
# Suppress langchain_google_genai schema-key warnings ($schema, additionalProperties
# are stripped when converting Pydantic tool schemas for the Gemini API — harmless)
logging.getLogger("langchain_google_genai._function_utils").setLevel(logging.ERROR)

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

QUESTION_TEST_CASES: Dict[str, str] = {
    "Tell me about tech stocks.":
        "Which specific tech companies or tickers would you like me to analyze, and what metrics or aspects are you interested in?",
    "Analyze semiconductor companies.":
        "Which semiconductor companies should I focus on, and what financial metrics or time period are you interested in?",
    "Show me some stock data.":
        "Which specific stocks or tickers would you like me to retrieve data for?",
    "What's happening in the market?":
        "Could you clarify which market segments, indices, or specific companies you'd like me to analyze?",
}


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

PREVIEW_LEN = 300


def _truncate(s: str, n: int = PREVIEW_LEN) -> str:
    s = str(s).replace("\n", " ").strip()
    return s[:n] + "..." if len(s) > n else s


def _args_preview(tool_calls: list) -> str:
    if not tool_calls:
        return ""
    tc = tool_calls[0]
    if not isinstance(tc, dict):
        return _truncate(str(tc))
    name = tc.get("name", "?")
    args = tc.get("args", {}) or {}
    if not isinstance(args, dict):
        return f"{name}({_truncate(str(args))})"
    args_str = ", ".join(f"{k}={repr(v)}" for k, v in list(args.items())[:3])
    if len(args) > 3:
        args_str += ", ..."
    return f"{name}({args_str})"


def detect_question(response: str) -> bool:
    """
    Heuristic to detect whether the orchestrator is asking a clarifying question
    rather than proceeding with execution.

    Scoring (threshold >= 2 → True):
      +2  response ends with '?'
      +1  '?' found in last 300 chars
      +1  contains clarification phrases
      +2  numbered list item containing '?' (e.g. "1. Which ticker?")
      +1  response length < 800 chars
      -2  contains execution phrases (delegating, phase 2, etc.)
    """
    if not response:
        return False

    score = 0

    stripped = response.strip()
    if stripped.endswith("?"):
        score += 2
    elif "?" in stripped[-300:]:
        score += 1

    clarification_phrases = [
        "could you specify", "could you clarify", "which ticker", "which company",
        "which metric", "please provide", "before i can", "what would you like",
        "what specific", "before i begin", "would you like to", "let me know",
        "please let me know", "could you tell me", "to proceed", "please confirm",
    ]
    lower = response.lower()
    if any(phrase in lower for phrase in clarification_phrases):
        score += 1

    # Numbered list with at least one question is almost always a clarifying request
    if re.search(r'\d+[\.\)]\s[^\n]*\?', response):
        score += 2

    if len(response) < 800:
        score += 1

    execution_phrases = [
        "delegating to", "phase 2", "data-engineer", "i'll now", "i will now",
        "initiating", "technical-writer",
    ]
    if any(phrase in lower for phrase in execution_phrases):
        score -= 2

    return score >= 2


async def llm_judge_and_answer(
    original_query: str,
    expected_question: str,
    actual_question: str,
) -> tuple[str, str, str]:
    """
    Use Gemini 2.5 Flash to:
    1. Judge whether the orchestrator's actual question semantically matches the expected question
    2. Generate a specific answer to continue the pipeline

    Returns (verdict, reason, answer)
    verdict is "PASS" (asked the right thing) or "FAIL" (asked wrong/unnecessary question)
    """
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage

    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0)

    prompt = f"""You are evaluating whether an AI research orchestrator asked the right clarifying question.

Original user query: "{original_query}"

Expected question (what the orchestrator should ask — intent, not exact wording):
"{expected_question}"

Actual question the orchestrator asked:
"{actual_question}"

1. Does the actual question semantically address the same missing information as the expected question?
   - PASS: The actual question asks about the same missing information (even if worded differently)
   - FAIL: The actual question asks about something else, is unnecessary, or misses the key ambiguity

2. Generate a specific, helpful answer to the ACTUAL question that would let the research pipeline continue.

Respond in EXACTLY this format (no extra text):
VERDICT: [PASS or FAIL]
REASON: [one sentence explaining your verdict]
ANSWER: [your answer to the actual question]"""

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    text = response.content.strip()

    verdict, reason, answer = "UNKNOWN", "", text  # safe defaults
    for line in text.splitlines():
        if line.startswith("VERDICT:"):
            verdict = line.split(":", 1)[1].strip()
        elif line.startswith("REASON:"):
            reason = line.split(":", 1)[1].strip()
        elif line.startswith("ANSWER:"):
            answer = line.split(":", 1)[1].strip()

    return verdict, reason, answer


_SUBAGENT_NAMES = {"data-engineer", "quant-developer", "technical-writer", "quality-analyst"}
_PHASE_MAP = {
    "data-engineer": "PHASE 2: DATA ACQUISITION",
    "quant-developer": "PHASE 3: QUANTITATIVE ANALYSIS",
    "technical-writer": "PHASE 4: REPORT SYNTHESIS",
    "quality-analyst": "PHASE 5: QUALITY ASSURANCE",
}


def format_event(event: Dict[str, Any], elapsed: float) -> List[Dict[str, Any]]:
    """
    Parse a LangGraph stream_mode='updates' event into printable lines.
    Returns a list of dicts: {label, node, text, elapsed, _full_content, raw}
    """
    lines = []
    TASK_PREVIEW = 400

    for node_name, state_update in event.items():
        if not isinstance(state_update, dict):
            lines.append({
                "label": "EVENT",
                "node": node_name,
                "text": f"{node_name}: {_truncate(state_update)}",
                "elapsed": elapsed,
                "_full_content": "",
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
                "_full_content": "",
                "raw": event,
            })
            continue

        for msg in messages:
            msg_type = type(msg).__name__

            if msg_type == "AIMessage":
                tool_calls = getattr(msg, "tool_calls", []) or []
                if tool_calls:
                    tc = tool_calls[0]
                    if not isinstance(tc, dict):
                        tc = {"name": str(tc), "args": {}}
                    tc_name = tc.get("name", "?")
                    tc_args = tc.get("args", {}) or {}
                    if not isinstance(tc_args, dict):
                        tc_args = {}
                    # Detect task() calls to subagents — emit phase banner + [INPUT]
                    if tc_name == "task":
                        subagent = tc_args.get("subagent_type") or tc_args.get("name", "?")
                        desc = tc_args.get("description") or tc_args.get("task", "")
                        phase = _PHASE_MAP.get(subagent, f"TASK → {subagent}")
                        lines.append({
                            "label": "PHASE",
                            "node": node_name,
                            "text": f" ══════ {phase} → {subagent} ══════",
                            "elapsed": elapsed,
                            "_full_content": "",
                            "raw": event,
                        })
                        lines.append({
                            "label": "INPUT",
                            "node": node_name,
                            "text": f"task: {_truncate(desc, TASK_PREVIEW)}",
                            "elapsed": elapsed,
                            "_full_content": "",
                            "raw": event,
                        })
                    else:
                        lines.append({
                            "label": "TOOL CALL",
                            "node": node_name,
                            "text": _args_preview(tool_calls),
                            "elapsed": elapsed,
                            "_full_content": "",
                            "raw": event,
                        })
                else:
                    raw_content = getattr(msg, "content", "") or ""
                    # Handle multimodal list content: [{'type': 'text', 'text': '...'}]
                    if isinstance(raw_content, list):
                        content = " ".join(
                            block.get("text", "") for block in raw_content
                            if isinstance(block, dict) and block.get("type") == "text"
                        )
                    else:
                        content = raw_content
                    lines.append({
                        "label": "MESSAGE",
                        "node": node_name,
                        "text": f"{node_name}: {_truncate(content)}",
                        "elapsed": elapsed,
                        "_full_content": content,
                        "raw": event,
                    })

            elif msg_type == "ToolMessage":
                tool_name = getattr(msg, "name", "?")
                content = getattr(msg, "content", "") or ""
                # Detect task() results from subagents — emit [OUTPUT]
                if tool_name == "task":
                    lines.append({
                        "label": "OUTPUT",
                        "node": node_name,
                        "text": _truncate(content, TASK_PREVIEW),
                        "elapsed": elapsed,
                        "_full_content": "",
                        "raw": event,
                    })
                else:
                    lines.append({
                        "label": "TOOL RESULT",
                        "node": node_name,
                        "text": f"{tool_name} → {_truncate(content)}",
                        "elapsed": elapsed,
                        "_full_content": "",
                        "raw": event,
                    })

            else:
                content = getattr(msg, "content", str(msg)) or str(msg)
                lines.append({
                    "label": "EVENT",
                    "node": node_name,
                    "text": f"{node_name}: {_truncate(content)}",
                    "elapsed": elapsed,
                    "_full_content": "",
                    "raw": event,
                })

    return lines


def print_event_line(line: Dict[str, Any]) -> None:
    label = line["label"]
    elapsed = line["elapsed"]
    text = line["text"]
    if label == "PHASE":
        print(f" [{elapsed:5.1f}s]{text}")
    else:
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

async def run_streaming(
    query: str,
    job_id: str,
    max_turns: int = 3,
    expected_question: Optional[str] = None,
    question_only: bool = False,
) -> Dict[str, Any]:
    from agents.orchestrator import stream_research

    output_dir = get_output_dir(job_id)
    events_file = output_dir / "events.jsonl"

    print("=" * 70)
    print(f"  Job ID : {job_id}")
    print(f"  Query  : {query}")
    if question_only:
        print(f"  Mode   : question-only (stops after judge verdict)")
    print("=" * 70)

    start = time.monotonic()
    event_count = 0
    status = "unknown"
    error: Optional[str] = None
    verdict: Optional[str] = None

    conversation_messages: Optional[list] = None  # None = use default single-message format
    turn = 0

    try:
        with open(events_file, "w", encoding="utf-8") as ef:
            while turn < max_turns:
                turn += 1
                elapsed_at_turn_start = time.monotonic() - start

                if turn == 1:
                    print(f" [ 0.0s] [START]        Orchestrator initializing...")
                else:
                    print(f" [{elapsed_at_turn_start:5.1f}s] [START]        Turn {turn} — continuing with answer...")

                last_orchestrator_message = ""

                async for event in stream_research(
                    query=query,
                    job_id=job_id,
                    messages=conversation_messages,
                ):
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
                        # Track last AI message (untruncated) — node may be named 'model' or 'orchestrator'
                        if line["label"] == "MESSAGE" and line["_full_content"]:
                            last_orchestrator_message = line["_full_content"]

                # After the stream ends, check if orchestrator asked a question
                if detect_question(last_orchestrator_message):
                    elapsed = time.monotonic() - start
                    print(f" [{elapsed:5.1f}s] [QUESTION]     {last_orchestrator_message}")
                    print(f" [{elapsed:5.1f}s] [LLM JUDGE]    Evaluating question against expected...")
                    verdict, reason, answer = await llm_judge_and_answer(
                        query, expected_question or "", last_orchestrator_message
                    )
                    elapsed = time.monotonic() - start
                    print(f" [{elapsed:5.1f}s] [VERDICT]      {verdict} — {reason}")
                    print(f" [{elapsed:5.1f}s] [LLM ANSWER]   {_truncate(answer, 200)}")

                    if question_only:
                        status = "question-pass" if verdict == "PASS" else "question-fail"
                        break

                    # Build extended conversation history for next turn
                    initial_user_msg = {"role": "user", "content": f"Job ID: {job_id}\n\nResearch Query: {query}"}
                    if conversation_messages is None:
                        # First clarification round
                        conversation_messages = [
                            initial_user_msg,
                            {"role": "assistant", "content": last_orchestrator_message},
                            {"role": "user", "content": answer},
                        ]
                    else:
                        # Subsequent rounds: append to existing history
                        conversation_messages = conversation_messages + [
                            {"role": "assistant", "content": last_orchestrator_message},
                            {"role": "user", "content": answer},
                        ]
                else:
                    elapsed = time.monotonic() - start
                    if question_only:
                        # Ambiguous query but orchestrator didn't ask — over-confident
                        verdict = "FAIL"
                        print(f" [{elapsed:5.1f}s] [VERDICT]      FAIL — Orchestrator did not ask a clarifying question")
                        status = "question-fail"
                    else:
                        status = "completed"
                    break
            else:
                # Exhausted max_turns without completing
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
        "verdict": verdict,
        "error": error,
    }
    (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if not question_only:
        # Print artifact summary (not relevant for question-only runs)
        artifacts = check_artifacts(output_dir)
        print("=" * 70)
        print("  Artifacts:")
        for name, status_str in artifacts.items():
            print(f"    {name:<20}: {status_str}")

        # Print report preview if completed successfully
        report_path = output_dir / "report.json"
        if status == "completed" and report_path.exists():
            try:
                report_data = json.loads(report_path.read_text(encoding="utf-8"))
                elapsed = time.monotonic() - start
                print(f" [{elapsed:5.1f}s] [REPORT PATH]  {report_path}")
                print(f" [{elapsed:5.1f}s] [REPORT]       {report_data.get('title', '(no title)')}")
                print(f" [{elapsed:5.1f}s] [SUMMARY]      {report_data.get('executive_summary', '(no summary)')}")
            except Exception:
                pass  # Don't fail the runner if report parsing fails
    print("=" * 70)

    return summary


# =============================================================================
# NON-STREAMING RUN
# =============================================================================

async def run_simple(query: str, job_id: str, max_turns: int = 3, expected_question: Optional[str] = None) -> Dict[str, Any]:
    from agents.orchestrator import run_research

    output_dir = get_output_dir(job_id)

    print("=" * 70)
    print(f"  Job ID : {job_id}")
    print(f"  Query  : {query}")
    print("  Mode   : non-streaming")
    print("=" * 70)

    start = time.monotonic()
    conversation_messages: Optional[list] = None
    turn = 0
    status = "unknown"
    error: Optional[str] = None
    response = ""

    while turn < max_turns:
        turn += 1
        result = await run_research(query=query, job_id=job_id, messages=conversation_messages)

        status = result.get("status", "unknown")
        error = result.get("error")
        response = result.get("response", "")

        if response:
            print(f"\n{response}\n")
        if error:
            print(f"[ERROR] {error}")
            break

        if detect_question(response):
            elapsed = time.monotonic() - start
            print(f" [{elapsed:5.1f}s] [LLM JUDGE]    Evaluating question against expected...")
            verdict, reason, answer = await llm_judge_and_answer(
                query, expected_question or "", response
            )
            elapsed = time.monotonic() - start
            print(f" [{elapsed:5.1f}s] [VERDICT]      {verdict} — {reason}")
            print(f" [{elapsed:5.1f}s] [LLM ANSWER]   {_truncate(answer, 200)}")

            initial_user_msg = {"role": "user", "content": f"Job ID: {job_id}\n\nResearch Query: {query}"}
            if conversation_messages is None:
                conversation_messages = [
                    initial_user_msg,
                    {"role": "assistant", "content": response},
                    {"role": "user", "content": answer},
                ]
            else:
                conversation_messages = conversation_messages + [
                    {"role": "assistant", "content": response},
                    {"role": "user", "content": answer},
                ]
        else:
            break

    elapsed = time.monotonic() - start
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
# REPLAY MODE  (no API calls — re-renders a saved events.jsonl instantly)
# =============================================================================

def replay_run(job_id: str) -> None:
    """
    Re-render a previous run from its saved events.jsonl.

    Reads outputs/{job_id}/events.jsonl, passes each raw event dict back
    through format_event() and print_event_line() so you can iterate on
    output formatting without waiting for real LLM calls.

    Usage:
        python tests/runner.py --replay test-abc12345
    """
    output_dir = get_output_dir(job_id)
    events_file = output_dir / "events.jsonl"

    if not events_file.exists():
        print(f"[ERROR] No events.jsonl found for job '{job_id}'")
        print(f"        Expected: {events_file}")
        sys.exit(1)

    summary_file = output_dir / "run_summary.json"
    query = job_id  # fallback
    if summary_file.exists():
        try:
            summary = json.loads(summary_file.read_text(encoding="utf-8"))
            query = summary.get("query", job_id)
        except Exception:
            pass

    print("=" * 70)
    print(f"  REPLAY  : {job_id}")
    print(f"  Query   : {query}")
    print("=" * 70)

    line_count = 0
    with open(events_file, encoding="utf-8") as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            elapsed = event.pop("_elapsed", 0.0)

            # Reconstruct message objects from the serialized __type__ dicts
            # so format_event can handle them the same way as live events.
            # We reconstruct a minimal shim with the right type name and attributes.
            for node_name, state_update in event.items():
                if not isinstance(state_update, dict):
                    continue
                raw_msgs = state_update.get("messages", [])
                if hasattr(raw_msgs, "value"):
                    raw_msgs = raw_msgs.value
                if not isinstance(raw_msgs, list):
                    continue
                reconstructed = []
                for m in raw_msgs:
                    if isinstance(m, dict) and "__type__" in m:
                        reconstructed.append(_ShimMessage(m))
                    else:
                        reconstructed.append(m)
                state_update["messages"] = reconstructed

            lines = format_event(event, elapsed)
            for line in lines:
                print_event_line(line)
                line_count += 1

    print("=" * 70)
    artifacts = check_artifacts(output_dir)
    print("  Artifacts:")
    for name, status_str in artifacts.items():
        print(f"    {name:<20}: {status_str}")
    print(f"  Events rendered : {line_count}")
    print("=" * 70)


def _ShimMessage(data: dict):
    """
    Factory that returns an instance whose type().__name__ matches the
    serialized __type__ field — so format_event()'s `type(msg).__name__`
    comparisons (AIMessage, ToolMessage, etc.) work correctly on replayed data.
    """
    type_name = data.get("__type__", "Unknown")
    cls = type(type_name, (), {})  # dynamic class with the right __name__
    obj = cls.__new__(cls)
    for k, v in data.items():
        if k != "__type__":
            setattr(obj, k, v)
    return obj


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
    parser.add_argument(
        "--max-turns",
        type=int,
        default=3,
        help="Max clarification rounds before aborting (default: 3).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=900,
        help="Hard timeout in seconds for a single run (default: 900 = 15 min).",
    )
    parser.add_argument(
        "--question-test",
        action="store_true",
        help="Run all predefined ambiguous queries and evaluate question-asking behavior.",
    )
    parser.add_argument(
        "--replay",
        type=str,
        metavar="JOB_ID",
        help="Re-render a previous run from its saved events.jsonl (no API calls).",
    )
    args = parser.parse_args()

    if args.replay:
        replay_run(args.replay)
        return

    if not args.query and args.tier is None and not args.question_test:
        parser.error("Provide --query, --tier, --question-test, or --replay JOB_ID.")

    if args.question_test:
        entries = list(QUESTION_TEST_CASES.items())
        print(f"\nRunning {len(entries)} question tests in parallel...\n")
        results = await asyncio.gather(*[
            run_streaming(
                query=query, job_id=make_job_id(),
                max_turns=1,
                expected_question=expected_question,
                question_only=True,
            )
            for query, expected_question in entries
        ])

        # Print verdict summary table
        print(f"\n{'=' * 70}")
        print(f"  QUESTION TEST RESULTS  ({len(results)} queries)")
        print(f"{'=' * 70}")
        passed = sum(1 for r in results if r.get("verdict") == "PASS")
        for r in results:
            v = r.get("verdict") or "N/A"
            q = r["query"][:50] + ("..." if len(r["query"]) > 50 else "")
            mark = "✓" if v == "PASS" else "✗"
            print(f"  {mark} [{v:<4}]  {q}")
        print(f"{'=' * 70}")
        print(f"  {passed}/{len(results)} PASSED")
        print(f"{'=' * 70}")
        return

    queries: List[str] = []
    if args.query:
        queries = [args.query]
    elif args.tier is not None:
        queries = TIER_QUERIES[args.tier]

    for i, query in enumerate(queries):
        if len(queries) > 1:
            print(f"\n{'#' * 70}")
            print(f"  Query {i + 1}/{len(queries)}")
            print(f"{'#' * 70}")

        job_id = make_job_id()
        expected_question = QUESTION_TEST_CASES.get(query)
        try:
            if args.no_stream:
                coro = run_simple(query=query, job_id=job_id, max_turns=args.max_turns,
                                  expected_question=expected_question)
            else:
                coro = run_streaming(query=query, job_id=job_id, max_turns=args.max_turns,
                                     expected_question=expected_question)
            summary = await asyncio.wait_for(coro, timeout=args.timeout)
        except asyncio.TimeoutError:
            minutes = args.timeout // 60
            print(f"\n [TIMEOUT]      Run exceeded {minutes} min hard limit — aborting")
            summary = {"query": query, "job_id": job_id, "status": "timeout", "error": f"Exceeded {args.timeout}s timeout"}

        if summary.get("status") in ("failed", "timeout") and len(queries) > 1:
            print(f"  [WARN] Query {summary['status']} — continuing with next query.")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
