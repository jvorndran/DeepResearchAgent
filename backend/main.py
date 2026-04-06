"""
FastAPI Application Entry Point

This file serves as the main entry point for the Deep Financial Research Agent API.
"""

import json
import uuid
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv

# Load environment variables from .env file
# Try to load from the backend directory first
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.orchestrator import create_orchestrator, stream_research

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Resolve the absolute path to the backend directory
BACKEND_DIR = Path(__file__).resolve().parent
OUTPUT_BASE_DIR = BACKEND_DIR / "outputs"


# =============================================================================
# SSE HELPERS
# =============================================================================

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _agent_from_ns(ns: list) -> str | None:
    """Extract the innermost agent name from a LangGraph namespace list."""
    if not ns:
        return None
    last = ns[-1]
    return last.split(":")[0] if ":" in last else last


def _parse_update(ns: list, data: Any, prev_agent: str | None) -> tuple[list[dict], str | None]:
    """
    Convert a raw LangGraph 'updates' payload into clean semantic events.
    Returns (events, current_agent_name).
    """
    events: list[dict] = []
    agent = _agent_from_ns(ns)

    # Emit agent transition events
    if agent != prev_agent:
        if prev_agent and prev_agent != "orchestrator":
            events.append({"type": "agent_end", "agent": prev_agent})
        if agent and agent != "orchestrator":
            events.append({"type": "agent_start", "agent": agent})

    if not isinstance(data, dict):
        return events, agent

    messages = data.get("messages", [])
    if not isinstance(messages, list):
        return events, agent

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        # AI message with tool calls → tool_call events
        for tc in msg.get("tool_calls", []):
            if isinstance(tc, dict) and tc.get("name"):
                events.append({
                    "type": "tool_call",
                    "agent": agent,
                    "tool": tc["name"],
                    "args": tc.get("args", {}),
                })

        # Tool result message → tool_result event
        msg_type = str(msg.get("type", ""))
        if "tool" in msg_type.lower() or msg.get("role") == "tool":
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            events.append({
                "type": "tool_result",
                "agent": agent,
                "tool": msg.get("name", ""),
                "summary": str(content)[:300],
            })

    return events, agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing orchestrator agent (MCP connections, tool registration)...")
    app.state.agent = await create_orchestrator()
    logger.info("Orchestrator ready.")
    yield


app = FastAPI(
    title="Deep Financial Research Agent API",
    description="API for the Deep Financial Research Agent",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001"],  # Next.js frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Message(BaseModel):
    role: str
    content: Optional[str] = None
    parts: Optional[List[Dict[str, Any]]] = None

class ChatRequest(BaseModel):
    messages: List[Message]
    job_id: Optional[str] = None

@app.get("/health")
async def health_check():
    return {"status": "ok"}

def _serialize(data: Any) -> Any:
    """Recursively serialize LangChain/Pydantic objects to plain dicts."""
    if isinstance(data, dict):
        return {k: _serialize(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_serialize(v) for v in data]
    if hasattr(data, "model_dump"):
        return data.model_dump()
    if hasattr(data, "dict"):
        return data.dict()
    return data


@app.get("/api/reports/{job_id}")
async def get_report(job_id: str):
    """
    Return the completed ResearchReport for a finished job.

    The frontend should call this after receiving the `finish` SSE event.
    Returns 202 while the job is still running (outputs dir exists but report.json
    not yet written), 404 if the job_id is unknown, and 200 with the full report
    JSON once complete.
    """
    outputs_dir = OUTPUT_BASE_DIR / job_id
    report_path = outputs_dir / "report.json"

    if not outputs_dir.exists():
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if not report_path.exists():
        raise HTTPException(status_code=202, detail="Report not ready yet")

    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to read report for job %s: %s", job_id, e)
        raise HTTPException(status_code=500, detail="Failed to read report")


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest, req: Request):
    job_id = request.job_id or f"job_{uuid.uuid4().hex[:8]}"

    messages_dict = []
    for msg in request.messages:
        content = msg.content
        if not content and msg.parts:
            text_parts = [p.get("text", "") for p in msg.parts if p.get("type") == "text"]
            content = "".join(text_parts)
        messages_dict.append({"role": msg.role, "content": content or ""})

    query = ""
    for msg in reversed(messages_dict):
        if msg["role"] == "user":
            query = msg["content"]
            break

    async def event_generator():
        current_agent: str | None = None
        try:
            yield _sse({"type": "start", "job_id": job_id})

            async for chunk in stream_research(query=query, job_id=job_id, messages=messages_dict, agent=req.app.state.agent):
                chunk_type = chunk.get("type")

                # ── Streaming text tokens from the orchestrator ──────────────
                if chunk_type == "messages":
                    token, _ = chunk.get("data", (None, None))
                    if token and hasattr(token, "content") and token.content:
                        content = token.content
                        if isinstance(content, list):
                            text = "".join(
                                p.get("text", "") for p in content
                                if isinstance(p, dict) and p.get("type") == "text"
                            )
                        else:
                            text = str(content) if not isinstance(content, str) else content
                        if text:
                            yield _sse({"type": "text", "delta": text})

                # ── LangGraph state updates → semantic pipeline events ────────
                elif chunk_type in ("updates", "custom"):
                    ns = chunk.get("ns", [])
                    raw_data = _serialize(chunk.get("data", {}))
                    events, current_agent = _parse_update(ns, raw_data, current_agent)
                    for event in events:
                        yield _sse(event)

            # Close out the last active subagent
            if current_agent and current_agent != "orchestrator":
                yield _sse({"type": "agent_end", "agent": current_agent})

            # Signal whether a report artifact is available for fetching
            report_path = OUTPUT_BASE_DIR / job_id / "report.json"
            yield _sse({"type": "finish", "report_ready": report_path.exists()})
            yield "data: [DONE]\n\n"

        except BaseException as e:
            logger.error(f"Error in stream: {e}")
            yield _sse({"type": "error", "errorText": str(e)})
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_excludes=["outputs/*", "outputs/**/*"],
    )
