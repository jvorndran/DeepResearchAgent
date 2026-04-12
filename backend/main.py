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
from pydantic import BaseModel, Field

from agents.orchestrator import create_orchestrator, stream_research

# Configure logging
# Set STREAM_DEBUG=1 in your environment to enable verbose chunk-level debug logs.
_stream_debug = os.environ.get("STREAM_DEBUG", "0") == "1"
logging.basicConfig(level=logging.DEBUG if _stream_debug else logging.INFO)
logger = logging.getLogger(__name__)
if not _stream_debug:
    # Keep chatty libraries quiet unless debug mode is on
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

# Resolve the absolute path to the backend directory
BACKEND_DIR = Path(__file__).resolve().parent
OUTPUT_BASE_DIR = BACKEND_DIR / "outputs"


# =============================================================================
# SSE HELPERS
# =============================================================================

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _serialize(data: Any) -> Any:
    """Recursively serialize LangChain/Pydantic objects to plain dicts."""
    if isinstance(data, dict):
        return {k: _serialize(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_serialize(v) for v in data]
    if isinstance(data, tuple):
        return tuple(_serialize(v) for v in data)
    if hasattr(data, "model_dump"):
        return data.model_dump()
    if hasattr(data, "dict"):
        return data.dict()
    return data


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

    v2 streaming format: data is {node_name: state_delta}, e.g.
      {"model_request": {"messages": [...]}, "tools": {"messages": [...]}}
    We collect messages from all node state deltas.
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

    # v2 updates: data is {node_name: state_delta} — gather messages from all nodes.
    messages: list = []
    for key, val in data.items():
        if key.startswith("__"):
            continue  # skip __interrupt__, __pregel_tasks__, etc.
        if isinstance(val, dict):
            node_msgs = val.get("messages", [])
            if isinstance(node_msgs, list):
                messages.extend(node_msgs)

    # Fallback: flat messages key (custom events or non-node data)
    if not messages:
        direct = data.get("messages", [])
        if isinstance(direct, list):
            messages = direct

    if not messages:
        return events, agent

    for msg in messages:
        if not isinstance(msg, dict):
            msg = _serialize(msg)
        if not isinstance(msg, dict):
            continue

        # AI message with tool calls → tool_call events
        for tc in msg.get("tool_calls", []) or []:
            name = None
            args: Dict[str, Any] = {}
            if isinstance(tc, dict):
                name = tc.get("name")
                args = tc.get("args") or {}
            else:
                name = getattr(tc, "name", None)
                args = getattr(tc, "args", {}) or {}
                if hasattr(args, "items"):
                    args = dict(args) if args else {}
            if name:
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                events.append({
                    "type": "tool_call",
                    "agent": agent,
                    "tool": name,
                    "args": args if isinstance(args, dict) else {},
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
    stream_telemetry: Optional[bool] = Field(
        default=None,
        description="False = omit raw model tokens; client uses user_message SSE from emit_chat_message.",
    )

@app.get("/health")
async def health_check():
    return {"status": "ok"}

def _is_orchestrator_home_ai(meta: Any, token: Any) -> bool:
    """True for main orchestrator model tokens (not subagent streams).

    deepagents wraps the whole graph so even the orchestrator's tokens arrive
    with a non-empty namespace — we cannot filter by ns depth. Instead we rely
    on metadata fields set by LangGraph / deepagents:

      lc_agent_name  — explicitly "orchestrator" when set by the framework
      langgraph_node — "model" or "model_request" for the orchestrator's LLM node;
                       subagents also use these names, but their lc_agent_name
                       will differ (e.g. "data-engineer", "quant-developer").

    When lc_agent_name is absent we fall back to accepting any AI chunk from a
    model node — this is permissive but avoids dropping orchestrator tokens when
    the framework doesn't populate the field.
    """
    if not token or str(getattr(token, "type", "")).lower() not in ("ai", "aimessagechunk"):
        return False
    if not isinstance(meta, dict):
        return True

    lc = meta.get("lc_agent_name") or ""
    node = meta.get("langgraph_node") or ""

    # Explicit orchestrator label — highest confidence
    if lc == "orchestrator":
        return True

    # Explicit subagent label — reject
    if lc and lc not in ("", "orchestrator"):
        return False

    # lc_agent_name absent: accept if it's a model node
    return node in ("model", "model_request")


def _markdown_from_tool_args(args: Any) -> Optional[str]:
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    if not isinstance(args, dict):
        return None
    for key in ("markdown", "Markdown", "content", "message"):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _markdown_from_emit_chat_tool_event(event: dict) -> Optional[str]:
    if event.get("type") != "tool_call" or event.get("tool") != "emit_chat_message":
        return None
    return _markdown_from_tool_args(event.get("args") or {})


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
        current_task_agent: str | None = None  # tracks subagent running inside task()
        stream_telemetry = True if request.stream_telemetry is None else request.stream_telemetry
        home_chat_fallback_text = ""
        user_message_emitted = False
        try:
            yield _sse({"type": "start", "job_id": job_id})

            async for chunk in stream_research(
                query=query,
                job_id=job_id,
                messages=messages_dict,
                agent=req.app.state.agent,
            ):
                chunk_type = chunk.get("type")
                logger.debug("[STREAM] chunk type=%s ns=%s", chunk_type, chunk.get("ns", []))

                # ── Streaming text tokens from the orchestrator ──────────────
                if chunk_type == "messages":
                    ns = chunk.get("ns", [])
                    token, meta = chunk.get("data", (None, None))
                    agent_name = meta.get("langgraph_node") if isinstance(meta, dict) else None
                    lc_agent = meta.get("lc_agent_name") if isinstance(meta, dict) else None
                    token_type = getattr(token, "type", "")
                    # deepagents wraps everything inside an outer graph so even the main
                    # orchestrator arrives with a non-empty ns (e.g. ('tools:uuid',)).
                    # We cannot use namespace depth to distinguish orchestrator from subagent.
                    # Instead, rely on lc_agent_name / langgraph_node from the metadata.
                    is_home_ai = _is_orchestrator_home_ai(meta, token)
                    logger.debug(
                        "[STREAM/messages] ns=%s token_type=%s agent_name=%s lc_agent=%s "
                        "is_home_ai=%s has_content=%s full_meta=%s",
                        ns, token_type, agent_name, lc_agent,
                        is_home_ai,
                        bool(token and hasattr(token, "content") and token.content),
                        meta,
                    )
                    if is_home_ai and token and hasattr(token, "content") and token.content:
                        content = token.content
                        if isinstance(content, list):
                            text = "".join(
                                p.get("text", "") for p in content
                                if isinstance(p, dict) and p.get("type") == "text"
                            )
                        else:
                            text = str(content) if not isinstance(content, str) else content
                        if text:
                            logger.debug("[STREAM/messages] emitting text delta len=%d stream_telemetry=%s", len(text), stream_telemetry)
                            if stream_telemetry:
                                yield _sse({"type": "text", "delta": text})
                            else:
                                home_chat_fallback_text += text
                    if not stream_telemetry and is_home_ai and token:
                        for tc in getattr(token, "tool_calls", None) or []:
                            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                            if name != "emit_chat_message":
                                continue
                            args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                            md = _markdown_from_tool_args(args)
                            if md and not user_message_emitted:
                                user_message_emitted = True
                                logger.debug("[STREAM/messages] emitting user_message from emit_chat_message tool call")
                                yield _sse({"type": "user_message", "markdown": md})

                # ── LangGraph state updates → semantic pipeline events ────────
                elif chunk_type in ("updates", "custom"):
                    ns = chunk.get("ns", [])
                    raw_data = _serialize(chunk.get("data", {}))
                    logger.debug("[STREAM/%s] ns=%s data_keys=%s", chunk_type, ns, list(raw_data.keys()) if isinstance(raw_data, dict) else type(raw_data).__name__)
                    events, current_agent = _parse_update(ns, raw_data, current_agent)
                    logger.debug("[STREAM/%s] parsed %d events current_agent=%s", chunk_type, len(events), current_agent)
                    for event in events:
                        # Translate the orchestrator's task() tool calls / results into
                        # agent lifecycle events so the pipeline view has something to display.
                        if event.get("type") == "tool_call" and event.get("tool") == "task":
                            args = event.get("args") or {}
                            subagent = args.get("subagent_type") or args.get("name")
                            logger.debug("[STREAM/updates] task() tool_call subagent=%s", subagent)
                            if subagent:
                                if current_task_agent:
                                    yield _sse({"type": "agent_end", "agent": current_task_agent})
                                current_task_agent = subagent
                                logger.info("[STREAM/updates] agent_start %s", subagent)
                                yield _sse({"type": "agent_start", "agent": subagent})
                            continue
                        if event.get("type") == "tool_result" and event.get("tool") == "task":
                            logger.debug("[STREAM/updates] task() tool_result → agent_end for %s", current_task_agent)
                            if current_task_agent:
                                yield _sse({"type": "agent_end", "agent": current_task_agent})
                                current_task_agent = None
                            continue
                        # Regular events
                        logger.debug("[STREAM/updates] event type=%s tool=%s agent=%s", event.get("type"), event.get("tool"), event.get("agent"))
                        md = _markdown_from_emit_chat_tool_event(event)
                        if md is not None and not user_message_emitted:
                            user_message_emitted = True
                            logger.info("[STREAM/updates] emitting user_message from emit_chat_message")
                            yield _sse({"type": "user_message", "markdown": md})
                        yield _sse(event)

            # Close out any still-active agents
            if current_task_agent:
                yield _sse({"type": "agent_end", "agent": current_task_agent})
            if current_agent and current_agent != "orchestrator":
                yield _sse({"type": "agent_end", "agent": current_agent})

            if (
                not stream_telemetry
                and not user_message_emitted
                and home_chat_fallback_text.strip()
            ):
                yield _sse({
                    "type": "user_message",
                    "markdown": home_chat_fallback_text.strip(),
                    "source": "model_text_fallback",
                })

            # Signal whether a report artifact is available for fetching
            report_path = OUTPUT_BASE_DIR / job_id / "report.json"
            report_ready = report_path.exists()
            yield _sse({"type": "finish", "report_ready": report_ready})
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
