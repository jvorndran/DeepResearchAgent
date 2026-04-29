"""
Simplified Research Agent Runner

Executes the Deep Research Agent pipeline for a given query and logs
high-signal execution events to outputs/{job_id}/agent_execution.log.
This log is designed to be easily parsed and understood by an AI agent
for iterative improvement.

Usage (from backend/ directory):
    python tests/runner.py --query "Research query here..."
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Keep the standalone improver runner focused on local agent behavior. Local
# .env files may enable LangSmith tracing, which adds unrelated network noise.
os.environ.setdefault("LANGCHAIN_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LANGSMITH_TRACING", "false")

# Allow running from backend/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))

# Suppress noisy framework logging
logging.getLogger("mcp.client.streamable_http").setLevel(logging.ERROR)
logging.getLogger("langchain_google_genai._function_utils").setLevel(logging.ERROR)

from dotenv import load_dotenv
load_dotenv()

from agents.orchestrator import stream_research

# Ensure stdout handles Unicode
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def _truncate(s: str, n: int = 400) -> str:
    s = str(s).replace("\n", " ").strip()
    return s[:n] + "..." if len(s) > n else s

def format_log_entry(label: str, node: str, text: str, elapsed: float) -> str:
    return f"[{elapsed:5.1f}s] [{label:<12}] [{node:<15}] {text}\n"


APPROVAL_MESSAGES = [
    {
        "role": "user",
        "content": "Commence Deep Research",
        "metadata": {"action": "commence_research"},
    }
]


def format_update_summary(update: Any) -> str:
    if isinstance(update, dict):
        return f"Keys: {list(update.keys())}"
    return f"{type(update).__name__}: {_truncate(update)}"


def is_approval_interrupt_update(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    interrupts = data.get("__interrupt__")
    if not isinstance(interrupts, tuple):
        return False
    for interrupt in interrupts:
        value = getattr(interrupt, "value", None)
        if isinstance(value, dict) and value.get("type") == "research_approval_needed":
            return True
    return False


def format_stream_error(error: dict[str, Any]) -> str:
    error_type = error.get("type", "error")
    error_message = error.get("message", str(error))
    details = []
    if error.get("phase"):
        details.append(f"phase={error['phase']}")
    if "retryable" in error:
        details.append(f"retryable={error['retryable']}")
    if "agent_recoverable" in error:
        details.append(f"agent_recoverable={error['agent_recoverable']}")
    if error.get("hint"):
        details.append(f"hint={error['hint']}")
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"{error_type}: {error_message}{suffix}"


def is_setup_error(error: dict[str, Any] | None) -> bool:
    return isinstance(error, dict) and error.get("phase") == "setup"


def is_incomplete_streaming_tool_call(name: Any, args: Any) -> bool:
    """Return True for partial AIMessageChunk tool-call fragments.

    Some streaming providers emit placeholder tool-call chunks before the
    complete tool call is assembled. Those fragments have no tool name and no
    args; counting them as real calls creates false identical-call watchdog
    stops.
    """
    return not name and (args is None or args == {})


@dataclass
class Watchdog:
    """Detect inefficient or suspicious agent behavior from the event stream."""

    max_runtime_seconds: float
    max_tool_calls: int
    max_identical_tool_calls: int
    max_fred_search_calls: int
    max_model_messages: int
    tool_calls: int = 0
    model_messages: int = 0
    fred_search_calls: int = 0
    repeated_call_exempt_tools: frozenset[str] = frozenset({"fred_search"})
    identical_tool_calls: Counter[str] = field(default_factory=Counter)

    def observe_tool_call(self, name: str, args: Any, elapsed: float) -> str | None:
        self.tool_calls += 1
        if name == "fred_search":
            self.fred_search_calls += 1

        try:
            normalized_args = json.dumps(args, sort_keys=True, default=str)
        except TypeError:
            normalized_args = str(args)

        signature = f"{name}:{normalized_args}"
        self.identical_tool_calls[signature] += 1

        if elapsed > self.max_runtime_seconds:
            return f"runtime exceeded {self.max_runtime_seconds:.0f}s"
        if self.tool_calls > self.max_tool_calls:
            return f"tool call budget exceeded ({self.tool_calls}>{self.max_tool_calls})"
        if self.fred_search_calls > self.max_fred_search_calls:
            return (
                f"fred_search budget exceeded "
                f"({self.fred_search_calls}>{self.max_fred_search_calls})"
            )
        if (
            name not in self.repeated_call_exempt_tools
            and self.identical_tool_calls[signature] > self.max_identical_tool_calls
        ):
            return (
                "identical tool call repeated "
                f"{self.identical_tool_calls[signature]} times: {name}({normalized_args})"
            )
        return None

    def observe_model_message(self, elapsed: float) -> str | None:
        self.model_messages += 1
        if elapsed > self.max_runtime_seconds:
            return f"runtime exceeded {self.max_runtime_seconds:.0f}s"
        if self.model_messages > self.max_model_messages:
            return (
                f"model message budget exceeded "
                f"({self.model_messages}>{self.max_model_messages})"
            )
        return None


async def run_research_loop(
    query: str,
    job_id: str,
    watchdog: Watchdog,
):
    output_dir = Path(os.getenv("OUTPUT_DIR", "outputs")) / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = output_dir / "agent_execution.log"
    
    print(f"Executing Query: {query}")
    print(f"Job ID: {job_id}")
    print(f"Log: {log_file}")
    
    start_time = time.monotonic()
    
    with open(log_file, "w", encoding="utf-8") as lf:
        lf.write(f"QUERY: {query}\n")
        lf.write(f"JOB_ID: {job_id}\n")
        lf.write("-" * 80 + "\n")
        stop_reason = None
        setup_failed = False
        approval_requested = False
        execution_seen = False
        force_execute_sent = False
        
        try:
            stream_messages = None
            max_stream_passes = 3
            for stream_pass in range(max_stream_passes):
                approval_requested = False
                execution_seen = stream_messages == APPROVAL_MESSAGES
                async for event in stream_research(
                    query=query,
                    job_id=job_id,
                    messages=stream_messages,
                ):
                    elapsed = time.monotonic() - start_time

                    if isinstance(event, dict) and "error" in event:
                        error = event["error"] or {}
                        setup_failed = is_setup_error(error)
                        stop_reason = format_stream_error(error)
                        entry = format_log_entry("ERROR", "system", stop_reason, elapsed)
                        lf.write(entry)
                        print(entry.strip())
                        break
                    
                    # Normalize LangGraph v2 events
                    if isinstance(event, dict) and "type" in event and "data" in event:
                        chunk_type = event["type"]
                        if chunk_type == "messages":
                            msg, meta = event["data"]
                            node = meta.get("langgraph_node", "model")
                            
                            # Handle tool calls
                            tool_calls = getattr(msg, "tool_calls", [])
                            if tool_calls:
                                for tc in tool_calls:
                                    tc_name = tc.get("name", "?")
                                    tc_args = tc.get("args", {})
                                    if is_incomplete_streaming_tool_call(tc_name, tc_args):
                                        continue
                                    entry = format_log_entry(
                                        "TOOL CALL",
                                        node,
                                        f"{tc_name}({json.dumps(tc_args, default=str)})",
                                        elapsed,
                                    )
                                    lf.write(entry)
                                    print(entry.strip())
                                    stop_reason = watchdog.observe_tool_call(
                                        tc_name,
                                        tc_args,
                                        elapsed,
                                    )
                                    if stop_reason:
                                        break
                                if stop_reason:
                                    entry = format_log_entry(
                                        "WATCHDOG",
                                        "system",
                                        f"Stopping early: {stop_reason}",
                                        elapsed,
                                    )
                                    lf.write(entry)
                                    print(entry.strip())
                                    break
                            
                            # Handle content
                            content = getattr(msg, "content", "")
                            if content and not tool_calls:
                                if isinstance(content, list):
                                    text = " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
                                else:
                                    text = str(content)
                                if text.strip():
                                    entry = format_log_entry("MESSAGE", node, _truncate(text), elapsed)
                                    lf.write(entry)
                                    print(entry.strip())
                                    stop_reason = watchdog.observe_model_message(elapsed)
                                    if stop_reason:
                                        entry = format_log_entry(
                                            "WATCHDOG",
                                            "system",
                                            f"Stopping early: {stop_reason}",
                                            elapsed,
                                        )
                                        lf.write(entry)
                                        print(entry.strip())
                                        break

                        elif chunk_type == "updates":
                            # Log state updates briefly.
                            data = event["data"]
                            if is_approval_interrupt_update(data):
                                approval_requested = True
                            if isinstance(data, dict):
                                if "execute" in data:
                                    execution_seen = True
                                for node_name, update in data.items():
                                    entry = format_log_entry(
                                        "UPDATE",
                                        node_name,
                                        format_update_summary(update),
                                        elapsed,
                                    )
                                    lf.write(entry)
                                    # (Optional) don't print updates to console to keep it cleaner
                    
                    # Handle ToolMessage (results)
                    # Note: stream_research handles ToolMessage differently in messages chunks, 
                    # but if we get them in updates we handle them here.
                    # In LangGraph v2, tool results often come back in 'messages' chunks as ToolMessage.
                    if isinstance(event, dict) and event.get("type") == "messages":
                        msg, _ = event["data"]
                        if type(msg).__name__ == "ToolMessage":
                            node = "tool_result"
                            content = getattr(msg, "content", "")
                            tool_name = getattr(msg, "name", "?")
                            entry = format_log_entry("TOOL RESULT", node, f"{tool_name} -> {_truncate(str(content))}", elapsed)
                            lf.write(entry)
                            print(entry.strip())

                if stop_reason or setup_failed:
                    break
                if approval_requested:
                    elapsed = time.monotonic() - start_time
                    entry = format_log_entry(
                        "AUTO APPROVE",
                        "approval_gate",
                        "Resuming approval interrupt for improver execution.",
                        elapsed,
                    )
                    lf.write(entry)
                    print(entry.strip())
                    stream_messages = APPROVAL_MESSAGES
                    continue
                if not execution_seen and not force_execute_sent:
                    force_execute_sent = True
                    elapsed = time.monotonic() - start_time
                    entry = format_log_entry(
                        "FORCE EXECUTE",
                        "intake",
                        "Intake ended without approval; resuming directly into execution "
                        "for improver coverage.",
                        elapsed,
                    )
                    lf.write(entry)
                    print(entry.strip())
                    stream_messages = APPROVAL_MESSAGES
                    continue
                break

        except Exception as e:
            elapsed = time.monotonic() - start_time
            error_msg = f"ERROR: {str(e)}"
            lf.write(format_log_entry("FATAL ERROR", "system", error_msg, elapsed))
            print(f"[{elapsed:5.1f}s] [FATAL ERROR] {error_msg}")
            stop_reason = error_msg
        
        lf.write("-" * 80 + "\n")
        if setup_failed:
            status = "SETUP_FAILED"
        else:
            status = "STOPPED_EARLY" if stop_reason else "COMPLETED"
        lf.write(f"{status} in {time.monotonic() - start_time:.2f}s\n")
        if stop_reason:
            lf.write(f"STOP_REASON: {stop_reason}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", type=str, required=True)
    parser.add_argument("--max-runtime-seconds", type=float, default=2400)
    parser.add_argument("--max-tool-calls", type=int, default=300)
    parser.add_argument("--max-identical-tool-calls", type=int, default=25)
    parser.add_argument("--max-fred-search-calls", type=int, default=100)
    parser.add_argument("--max-model-messages", type=int, default=5000)
    args = parser.parse_args()
    
    job_id = f"improver-{uuid.uuid4().hex[:8]}"
    asyncio.run(
        run_research_loop(
            args.query,
            job_id,
            Watchdog(
                max_runtime_seconds=args.max_runtime_seconds,
                max_tool_calls=args.max_tool_calls,
                max_identical_tool_calls=args.max_identical_tool_calls,
                max_fred_search_calls=args.max_fred_search_calls,
                max_model_messages=args.max_model_messages,
            ),
        )
    )
