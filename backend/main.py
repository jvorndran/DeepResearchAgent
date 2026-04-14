"""
FastAPI Application Entry Point

This file serves as the main entry point for the Deep Financial Research Agent API.
"""

import asyncio
import json
import uuid
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
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

_SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


# =============================================================================
# JOB REGISTRY  (fan-out: each subscriber gets its own queue + replay from log)
# =============================================================================

class JobStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass
class JobState:
    job_id: str
    status: JobStatus
    query: str
    task: asyncio.Task | None = None
    # Every processed SSE event dict is appended here so reconnect can replay
    events_log: list = field(default_factory=list)
    # One asyncio.Queue per active SSE subscriber
    _subscriber_queues: list = field(default_factory=list)
    subscriber_count: int = 0


_JOBS: dict[str, JobState] = {}
_JOB_DONE = object()  # sentinel pushed into every subscriber queue when bg task finishes


# --- Fan-out helpers ---------------------------------------------------------

def _subscribe(job_state: JobState) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    job_state._subscriber_queues.append(q)
    job_state.subscriber_count += 1
    return q


def _unsubscribe(job_state: JobState, q: asyncio.Queue) -> None:
    try:
        job_state._subscriber_queues.remove(q)
    except ValueError:
        pass
    job_state.subscriber_count = max(0, job_state.subscriber_count - 1)


async def _publish(job_state: JobState, event: dict) -> None:
    """Append event to the replay log and push to all active subscriber queues."""
    job_state.events_log.append(event)
    for q in list(job_state._subscriber_queues):
        await q.put(event)


async def _publish_done(job_state: JobState) -> None:
    """Push the done sentinel to every subscriber queue (not logged)."""
    for q in list(job_state._subscriber_queues):
        await q.put(_JOB_DONE)


# =============================================================================
# FILESYSTEM HELPERS
# =============================================================================

def _write_status(job_id: str, status: JobStatus, query: str = "") -> None:
    """Write/overwrite status.json atomically. Creates outputs dir if needed."""
    outputs_dir = OUTPUT_BASE_DIR / job_id
    outputs_dir.mkdir(parents=True, exist_ok=True)
    tmp = outputs_dir / "status.json.tmp"
    final = outputs_dir / "status.json"
    tmp.write_text(json.dumps({
        "job_id": job_id,
        "status": status.value,
        "query": query,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }), encoding="utf-8")
    os.replace(tmp, final)  # atomic rename (POSIX guarantee)


def _read_status(job_id: str) -> dict | None:
    try:
        return json.loads((OUTPUT_BASE_DIR / job_id / "status.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


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
    """
    events: list[dict] = []
    agent = _agent_from_ns(ns)

    if agent != prev_agent:
        if prev_agent and prev_agent != "orchestrator":
            events.append({"type": "agent_end", "agent": prev_agent})
        if agent and agent != "orchestrator":
            events.append({"type": "agent_start", "agent": agent})

    if not isinstance(data, dict):
        return events, agent

    messages: list = []
    for key, val in data.items():
        if key.startswith("__"):
            continue
        if isinstance(val, dict):
            node_msgs = val.get("messages", [])
            if isinstance(node_msgs, list):
                messages.extend(node_msgs)

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


def _is_orchestrator_home_ai(meta: Any, token: Any) -> bool:
    if not token or str(getattr(token, "type", "")).lower() not in ("ai", "aimessagechunk"):
        return False
    if not isinstance(meta, dict):
        return True

    lc = meta.get("lc_agent_name") or ""
    node = meta.get("langgraph_node") or ""

    if lc == "orchestrator":
        return True
    if lc and lc not in ("", "orchestrator"):
        return False
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


# =============================================================================
# RESEARCH CHUNK PROCESSOR  (runs inside the background task for research jobs)
# =============================================================================

async def _process_research_chunks(raw_stream):
    """
    Convert raw stream_research chunks into SSE event dicts (research / stream_telemetry=True mode).
    Yields event dicts — no _sse() wrapping, that happens at the relay layer.
    """
    current_agent: str | None = None
    current_task_agent: str | None = None
    user_message_emitted = False

    async for chunk in raw_stream:
        chunk_type = chunk.get("type")
        logger.debug("[BG] chunk type=%s ns=%s", chunk_type, chunk.get("ns", []))

        if chunk_type == "messages":
            token, meta = chunk.get("data", (None, None))
            is_home_ai = _is_orchestrator_home_ai(meta, token)
            lc_agent = meta.get("lc_agent_name") if isinstance(meta, dict) else None
            agent_name = meta.get("langgraph_node") if isinstance(meta, dict) else None
            logger.debug(
                "[BG/messages] agent_name=%s lc_agent=%s is_home_ai=%s",
                agent_name, lc_agent, is_home_ai,
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
                    yield {"type": "text", "delta": text}
            if is_home_ai and token:
                for tc in getattr(token, "tool_calls", None) or []:
                    name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                    if name != "emit_chat_message":
                        continue
                    args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                    md = _markdown_from_tool_args(args)
                    if md and not user_message_emitted:
                        user_message_emitted = True
                        yield {"type": "user_message", "markdown": md}

        elif chunk_type in ("updates", "custom"):
            ns = chunk.get("ns", [])
            raw_data = _serialize(chunk.get("data", {}))
            events, current_agent = _parse_update(ns, raw_data, current_agent)
            logger.debug("[BG/%s] parsed %d events current_agent=%s", chunk_type, len(events), current_agent)
            for event in events:
                if event.get("type") == "tool_call" and event.get("tool") == "task":
                    args = event.get("args") or {}
                    subagent = args.get("subagent_type") or args.get("name")
                    if subagent:
                        if current_task_agent:
                            yield {"type": "agent_end", "agent": current_task_agent}
                        current_task_agent = subagent
                        logger.info("[BG] agent_start %s", subagent)
                        yield {"type": "agent_start", "agent": subagent}
                    continue
                if event.get("type") == "tool_result" and event.get("tool") == "task":
                    if current_task_agent:
                        yield {"type": "agent_end", "agent": current_task_agent}
                        current_task_agent = None
                    continue
                md = _markdown_from_emit_chat_tool_event(event)
                if md is not None and not user_message_emitted:
                    user_message_emitted = True
                    yield {"type": "user_message", "markdown": md}
                yield event

    # Close out any still-active agents
    if current_task_agent:
        yield {"type": "agent_end", "agent": current_task_agent}
    if current_agent and current_agent != "orchestrator":
        yield {"type": "agent_end", "agent": current_agent}


# =============================================================================
# BACKGROUND JOB RUNNER
# =============================================================================

async def _run_job_background(
    job_id: str, query: str, messages_dict: list, agent: Any, job_state: JobState
) -> None:
    try:
        raw_stream = stream_research(query=query, job_id=job_id, messages=messages_dict, agent=agent)
        async for event_dict in _process_research_chunks(raw_stream):
            await _publish(job_state, event_dict)
        job_state.status = JobStatus.COMPLETED
        _write_status(job_id, JobStatus.COMPLETED, query)
        logger.info("Job %s completed", job_id)
    except asyncio.CancelledError:
        job_state.status = JobStatus.INTERRUPTED
        _write_status(job_id, JobStatus.INTERRUPTED, query)
        raise
    except Exception as e:
        job_state.status = JobStatus.FAILED
        _write_status(job_id, JobStatus.FAILED, query)
        logger.error("Job %s failed: %s", job_id, e, exc_info=True)
        await _publish(job_state, {"__bg_error__": str(e)})
    finally:
        await _publish_done(job_state)
        _JOBS.pop(job_id, None)


# =============================================================================
# SSE RELAY HELPER  (shared by chat_stream and reconnect endpoint)
# =============================================================================

async def _relay_subscriber_queue(q: asyncio.Queue):
    """Async generator that yields event dicts from a subscriber queue until done."""
    while True:
        event = await q.get()
        if event is _JOB_DONE:
            return
        yield event


# =============================================================================
# LIFESPAN
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    if OUTPUT_BASE_DIR.exists():
        for job_dir in OUTPUT_BASE_DIR.iterdir():
            if not job_dir.is_dir():
                continue
            d = _read_status(job_dir.name)
            if d and d.get("status") == JobStatus.RUNNING.value:
                logger.warning("Job %s was running at startup — marking interrupted", job_dir.name)
                _write_status(job_dir.name, JobStatus.INTERRUPTED, d.get("query", ""))

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001"],
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


# =============================================================================
# REPORT ENDPOINT
# =============================================================================

@app.get("/api/reports/{job_id}")
async def get_report(job_id: str):
    """
    Return the completed ResearchReport for a finished job.

    Checks in-memory registry first, then report.json, then status.json.
    Returns 202 while running, 410 if interrupted, 404 if unknown.
    """
    report_path = OUTPUT_BASE_DIR / job_id / "report.json"

    # 1. In-memory check (fastest — for active jobs)
    job_state = _JOBS.get(job_id)
    if job_state and job_state.status == JobStatus.RUNNING:
        raise HTTPException(status_code=202, detail="Research in progress")

    # 2. Return report if it exists
    if report_path.exists():
        try:
            return json.loads(report_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to read report for job %s: %s", job_id, e)
            raise HTTPException(status_code=500, detail="Failed to read report")

    # 3. Fall back to status.json (post-restart case where _JOBS is empty)
    status_data = _read_status(job_id)
    if status_data is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    on_disk = status_data.get("status")
    if on_disk == JobStatus.RUNNING.value:
        raise HTTPException(status_code=202, detail="Research in progress")
    if on_disk == JobStatus.INTERRUPTED.value:
        raise HTTPException(status_code=410, detail="Job was interrupted — server was restarted mid-job")
    if on_disk == JobStatus.FAILED.value:
        raise HTTPException(status_code=500, detail="Research job failed")

    raise HTTPException(status_code=202, detail="Report not yet available")


# =============================================================================
# RECONNECT SSE ENDPOINT  (GET — used by frontend on page refresh)
# =============================================================================

@app.get("/api/jobs/{job_id}/stream")
async def reconnect_job_stream(job_id: str):
    """
    Reconnect to a running research job's live SSE stream after a page refresh.

    Replays all events emitted so far, then streams live events until the job
    finishes. Returns 404 if the job is not currently active in memory.
    """
    job_state = _JOBS.get(job_id)
    if not job_state or job_state.status != JobStatus.RUNNING:
        raise HTTPException(status_code=404, detail="No active job found — job may have finished or never started")

    # Snapshot the replay log and subscribe atomically (no await between — asyncio is cooperative)
    replay = list(job_state.events_log)
    q = _subscribe(job_state)
    logger.info("Reconnect SSE for job %s — replaying %d events", job_id, len(replay))

    async def gen():
        try:
            yield _sse({"type": "start", "job_id": job_id})
            # Replay everything the client missed
            for event in replay:
                yield _sse(event)
            # Stream live events from here
            async for event in _relay_subscriber_queue(q):
                if isinstance(event, dict) and "__bg_error__" in event:
                    yield _sse({"type": "error", "errorText": event["__bg_error__"]})
                    yield "data: [DONE]\n\n"
                    return
                yield _sse(event)
            # Job done
            report_path = OUTPUT_BASE_DIR / job_id / "report.json"
            yield _sse({"type": "finish", "report_ready": report_path.exists()})
            yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            logger.info("Reconnect SSE client disconnected for job %s", job_id)
            return
        finally:
            _unsubscribe(job_state, q)
            if job_state.status != JobStatus.RUNNING and job_state.subscriber_count == 0:
                _JOBS.pop(job_id, None)

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


# =============================================================================
# CHAT STREAM ENDPOINT
# =============================================================================

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

    # Q&A / intake phase: stream_telemetry=False means the home page conversation.
    # These are short-lived and don't need job persistence — use original SSE-tied behavior.
    # Research phase: stream_telemetry is None or True (chat page after "Commence Deep Research").
    # These are long-running and benefit from background task + status.json persistence.
    is_research = request.stream_telemetry is not False

    if is_research:
        # Guard: second SSE connection to a running job gets a redirect
        existing = _JOBS.get(job_id)
        if existing and existing.status == JobStatus.RUNNING:
            async def _dup():
                yield _sse({"type": "start", "job_id": job_id})
                yield _sse({"type": "error", "errorText": f"Job {job_id} already running — reconnect via GET /api/jobs/{job_id}/stream"})
                yield "data: [DONE]\n\n"
            return StreamingResponse(_dup(), media_type="text/event-stream", headers=_SSE_HEADERS)

        # Create job state and subscribe before launching the task
        job_state = JobState(job_id=job_id, status=JobStatus.RUNNING, query=query)
        q = _subscribe(job_state)
        _JOBS[job_id] = job_state
        _write_status(job_id, JobStatus.RUNNING, query)  # creates outputs dir immediately

        # Reuse app.state.agent across research jobs. Previously this passed
        # agent=None (creating a fresh orchestrator per job) to work around a
        # WSL2 issue where the Hyper-V virtual switch drops idle TCP connections
        # after ~4 min, silently invalidating FRED's HTTP MCP session. FRED now
        # uses stdio transport (no TCP), so reuse is safe and avoids the extra
        # FRED subprocess startup on every query.
        bg_task = asyncio.create_task(
            _run_job_background(job_id, query, messages_dict, req.app.state.agent, job_state),
            name=f"research_{job_id}",
        )
        job_state.task = bg_task

        def _on_done(t: asyncio.Task) -> None:
            s = _JOBS.get(job_id)
            if s and s.subscriber_count == 0:
                _JOBS.pop(job_id, None)
        bg_task.add_done_callback(_on_done)

    async def event_generator():
        try:
            yield _sse({"type": "start", "job_id": job_id})

            if is_research:
                # ── Research mode: relay pre-processed events from the subscriber queue ──
                async for event in _relay_subscriber_queue(q):
                    if isinstance(event, dict) and "__bg_error__" in event:
                        yield _sse({"type": "error", "errorText": event["__bg_error__"]})
                        yield "data: [DONE]\n\n"
                        return
                    yield _sse(event)

                report_path = OUTPUT_BASE_DIR / job_id / "report.json"
                yield _sse({"type": "finish", "report_ready": report_path.exists()})
                yield "data: [DONE]\n\n"

            else:
                # ── Q&A mode: process raw chunks inline (original unmodified behavior) ──
                current_agent: str | None = None
                current_task_agent: str | None = None
                stream_telemetry = False  # always False for Q&A path
                home_chat_fallback_text = ""
                user_message_emitted = False

                async for chunk in stream_research(
                    query=query,
                    job_id=job_id,
                    messages=messages_dict,
                    agent=req.app.state.agent,
                ):
                    chunk_type = chunk.get("type")
                    logger.debug("[STREAM] chunk type=%s ns=%s", chunk_type, chunk.get("ns", []))

                    if chunk_type == "messages":
                        ns = chunk.get("ns", [])
                        token, meta = chunk.get("data", (None, None))
                        agent_name = meta.get("langgraph_node") if isinstance(meta, dict) else None
                        lc_agent = meta.get("lc_agent_name") if isinstance(meta, dict) else None
                        token_type = getattr(token, "type", "")
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

                    elif chunk_type in ("updates", "custom"):
                        ns = chunk.get("ns", [])
                        raw_data = _serialize(chunk.get("data", {}))
                        logger.debug("[STREAM/%s] ns=%s data_keys=%s", chunk_type, ns, list(raw_data.keys()) if isinstance(raw_data, dict) else type(raw_data).__name__)
                        events, current_agent = _parse_update(ns, raw_data, current_agent)
                        logger.debug("[STREAM/%s] parsed %d events current_agent=%s", chunk_type, len(events), current_agent)
                        for event in events:
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

                if not user_message_emitted and home_chat_fallback_text.strip():
                    yield _sse({
                        "type": "user_message",
                        "markdown": home_chat_fallback_text.strip(),
                        "source": "model_text_fallback",
                    })

                report_path = OUTPUT_BASE_DIR / job_id / "report.json"
                report_ready = report_path.exists()
                yield _sse({"type": "finish", "report_ready": report_ready})
                yield "data: [DONE]\n\n"

        except asyncio.CancelledError:
            if is_research:
                logger.info("SSE client disconnected for job %s — background task continues", job_id)
            return

        except Exception as e:
            logger.error(f"Error in stream: {e}")
            yield _sse({"type": "error", "errorText": str(e)})
            yield "data: [DONE]\n\n"

        finally:
            if is_research:
                _unsubscribe(job_state, q)
                if job_state.status != JobStatus.RUNNING and job_state.subscriber_count == 0:
                    _JOBS.pop(job_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
