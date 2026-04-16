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
from pathlib import Path
from typing import Any, Dict, List, Optional

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

async def run_research_loop(query: str, job_id: str):
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
        
        try:
            async for event in stream_research(query=query, job_id=job_id):
                elapsed = time.monotonic() - start_time
                
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
                                entry = format_log_entry("TOOL CALL", node, f"{tc_name}({json.dumps(tc_args)})", elapsed)
                                lf.write(entry)
                                print(entry.strip())
                        
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

                    elif chunk_type == "updates":
                        # Log state updates briefly
                        data = event["data"]
                        if isinstance(data, dict):
                            for node_name, update in data.items():
                                entry = format_log_entry("UPDATE", node_name, f"Keys: {list(update.keys())}", elapsed)
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

        except Exception as e:
            elapsed = time.monotonic() - start_time
            error_msg = f"ERROR: {str(e)}"
            lf.write(format_log_entry("FATAL ERROR", "system", error_msg, elapsed))
            print(f"[{elapsed:5.1f}s] [FATAL ERROR] {error_msg}")
        
        lf.write("-" * 80 + "\n")
        lf.write(f"COMPLETED in {time.monotonic() - start_time:.2f}s\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", type=str, required=True)
    args = parser.parse_args()
    
    job_id = f"improver-{uuid.uuid4().hex[:8]}"
    asyncio.run(run_research_loop(args.query, job_id))
