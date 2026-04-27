import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from agents.orchestrator import stream_research
from api.dependencies import AuthUser, get_current_user
from api.schemas.chat import ChatRequest
from core.database import ResearchJob, get_db
from core.paths import OUTPUT_BASE_DIR
from services.report_library import get_job_for_user, upsert_research_job
from services.research_jobs import (
    JOBS,
    preview_text,
    relay_subscriber_queue,
    run_job_background,
    subscribe,
    unsubscribe,
)
from services.research_types import JobState, JobStatus
from services.job_status import write_job_status
from services.stream_errors import build_exception_error_event, normalize_stream_error
from services.stream_events import (
    SSE_HEADERS,
    is_orchestrator_home_ai,
    markdown_from_emit_chat_tool_event,
    markdown_from_tool_args,
    parse_graph_update,
    serialize_lc_value,
    sse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


@router.post("/api/chat/stream")
async def chat_stream(
    request: ChatRequest,
    req: Request,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job_id = request.job_id or f"job_{uuid.uuid4().hex[:8]}"

    messages_dict = []
    for msg in request.messages:
        content = msg.content
        if not content and msg.parts:
            text_parts = [p.get("text", "") for p in msg.parts if p.get("type") == "text"]
            content = "".join(text_parts)
        message_dict = {"role": msg.role, "content": content or ""}
        if msg.metadata:
            message_dict["metadata"] = msg.metadata
        messages_dict.append(message_dict)

    query = ""
    for msg in reversed(messages_dict):
        if msg["role"] == "user":
            query = msg["content"]
            break

    is_research = request.stream_telemetry is not False
    logger.info(
        "Incoming chat stream request job_id=%s mode=%s message_count=%d query=%r client=%s",
        job_id,
        "research" if is_research else "qa",
        len(messages_dict),
        preview_text(query),
        req.client.host if req.client else "unknown",
    )

    q: asyncio.Queue | None = None
    job_state: JobState | None = None

    existing = JOBS.get(job_id)
    if existing and existing.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    stored_job = get_job_for_user(db, job_id, current_user.id)
    if request.job_id and stored_job is None and db.get(ResearchJob, job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    if is_research:
        if existing and existing.status == JobStatus.RUNNING:

            async def _dup():
                yield sse({"type": "start", "job_id": job_id})
                yield sse(
                    {
                        "type": "error",
                        "errorText": (
                            f"Job {job_id} already running — reconnect via GET /api/jobs/{job_id}/stream"
                        ),
                    }
                )
                yield "data: [DONE]\n\n"

            return StreamingResponse(_dup(), media_type="text/event-stream", headers=SSE_HEADERS)

        upsert_research_job(
            db,
            job_id=job_id,
            user_id=current_user.id,
            query=query,
            status=JobStatus.RUNNING,
        )
        job_state = JobState(
            job_id=job_id,
            user_id=current_user.id,
            status=JobStatus.RUNNING,
            query=query,
        )
        q = subscribe(job_state)
        JOBS[job_id] = job_state
        write_job_status(job_id, JobStatus.RUNNING, query)

        bg_task = asyncio.create_task(
            run_job_background(
                job_id, current_user.id, query, messages_dict, req.app.state.agent, job_state
            ),
            name=f"research_{job_id}",
        )
        job_state.task = bg_task

        def _on_done(t: asyncio.Task) -> None:
            s = JOBS.get(job_id)
            if s and s.subscriber_count == 0:
                JOBS.pop(job_id, None)

        bg_task.add_done_callback(_on_done)

    async def event_generator():
        try:
            yield sse({"type": "start", "job_id": job_id})

            if is_research:
                async for event in relay_subscriber_queue(q):
                    if isinstance(event, dict) and "__bg_error__" in event:
                        bg_error = event["__bg_error__"]
                        yield sse(
                            bg_error
                            if isinstance(bg_error, dict)
                            else normalize_stream_error(job_id, "background_research", bg_error)
                        )
                        yield "data: [DONE]\n\n"
                        return
                    yield sse(event)

                report_path = OUTPUT_BASE_DIR / job_id / "report.json"
                yield sse({"type": "finish", "report_ready": report_path.exists()})
                yield "data: [DONE]\n\n"

            else:
                current_agent: str | None = None
                current_task_agent: str | None = None
                stream_telemetry = False
                home_chat_fallback_text = ""
                # Track emitted markdown texts to deduplicate the same
                # emit_chat_message appearing in both 'messages' and 'updates'
                # streams, while still allowing different messages from
                # different graph nodes (e.g. intake Q&A vs approval prompt).
                emitted_user_messages: set[str] = set()

                async for chunk in stream_research(
                    query=query,
                    job_id=job_id,
                    messages=messages_dict,
                    agent=req.app.state.agent,
                ):
                    if "error" in chunk:
                        error_event = normalize_stream_error(job_id, "qa_stream", chunk["error"])
                        logger.warning(
                            "Inline QA stream yielded error job_id=%s error_type=%s detail=%r",
                            job_id,
                            error_event["errorType"],
                            error_event["errorText"],
                        )
                        yield sse(error_event)
                        yield "data: [DONE]\n\n"
                        return

                    chunk_type = chunk.get("type")
                    logger.debug("[STREAM] chunk type=%s ns=%s", chunk_type, chunk.get("ns", []))

                    if chunk_type == "messages":
                        ns = chunk.get("ns", [])
                        token, meta = chunk.get("data", (None, None))
                        agent_name = meta.get("langgraph_node") if isinstance(meta, dict) else None
                        lc_agent = meta.get("lc_agent_name") if isinstance(meta, dict) else None
                        token_type = getattr(token, "type", "")
                        is_home_ai = is_orchestrator_home_ai(meta, token)
                        logger.debug(
                            "[STREAM/messages] ns=%s token_type=%s agent_name=%s lc_agent=%s "
                            "is_home_ai=%s has_content=%s full_meta=%s",
                            ns,
                            token_type,
                            agent_name,
                            lc_agent,
                            is_home_ai,
                            bool(token and hasattr(token, "content") and token.content),
                            meta,
                        )
                        if is_home_ai and token and hasattr(token, "content") and token.content:
                            content = token.content
                            if isinstance(content, list):
                                text = "".join(
                                    p.get("text", "")
                                    for p in content
                                    if isinstance(p, dict) and p.get("type") == "text"
                                )
                            else:
                                text = str(content) if not isinstance(content, str) else content
                            if text:
                                logger.debug(
                                    "[STREAM/messages] emitting text delta len=%d stream_telemetry=%s",
                                    len(text),
                                    stream_telemetry,
                                )
                                if stream_telemetry:
                                    yield sse({"type": "text", "delta": text})
                                else:
                                    home_chat_fallback_text += text
                        if not stream_telemetry and is_home_ai and token:
                            for tc in getattr(token, "tool_calls", None) or []:
                                name = (
                                    tc.get("name")
                                    if isinstance(tc, dict)
                                    else getattr(tc, "name", None)
                                )
                                if name != "emit_chat_message":
                                    continue
                                args = (
                                    tc.get("args")
                                    if isinstance(tc, dict)
                                    else getattr(tc, "args", {})
                                )
                                md = markdown_from_tool_args(args)
                                if md and md not in emitted_user_messages:
                                    emitted_user_messages.add(md)
                                    logger.debug(
                                        "[STREAM/messages] emitting user_message from emit_chat_message tool call"
                                    )
                                    yield sse({"type": "user_message", "markdown": md})

                    elif chunk_type in ("updates", "custom"):
                        ns = chunk.get("ns", [])
                        raw_data = serialize_lc_value(chunk.get("data", {}))
                        logger.debug(
                            "[STREAM/%s] ns=%s data_keys=%s",
                            chunk_type,
                            ns,
                            (
                                list(raw_data.keys())
                                if isinstance(raw_data, dict)
                                else type(raw_data).__name__
                            ),
                        )
                        events, current_agent = parse_graph_update(ns, raw_data, current_agent)
                        logger.debug(
                            "[STREAM/%s] parsed %d events current_agent=%s",
                            chunk_type,
                            len(events),
                            current_agent,
                        )
                        for event in events:
                            if event.get("type") == "tool_call" and event.get("tool") == "task":
                                args = event.get("args") or {}
                                subagent = args.get("subagent_type") or args.get("name")
                                logger.debug(
                                    "[STREAM/updates] task() tool_call subagent=%s", subagent
                                )
                                if subagent:
                                    if current_task_agent:
                                        yield sse(
                                            {"type": "agent_end", "agent": current_task_agent}
                                        )
                                    current_task_agent = subagent
                                    logger.info("[STREAM/updates] agent_start %s", subagent)
                                    yield sse({"type": "agent_start", "agent": subagent})
                                continue
                            if event.get("type") == "tool_result" and event.get("tool") == "task":
                                logger.debug(
                                    "[STREAM/updates] task() tool_result → agent_end for %s",
                                    current_task_agent,
                                )
                                if current_task_agent:
                                    yield sse({"type": "agent_end", "agent": current_task_agent})
                                    current_task_agent = None
                                continue
                            logger.debug(
                                "[STREAM/updates] event type=%s tool=%s agent=%s",
                                event.get("type"),
                                event.get("tool"),
                                event.get("agent"),
                            )
                            md = markdown_from_emit_chat_tool_event(event)
                            if md is not None and md not in emitted_user_messages:
                                emitted_user_messages.add(md)
                                logger.info(
                                    "[STREAM/updates] emitting user_message from emit_chat_message"
                                )
                                yield sse({"type": "user_message", "markdown": md})
                            yield sse(event)

                if current_task_agent:
                    yield sse({"type": "agent_end", "agent": current_task_agent})
                if current_agent and current_agent not in ("orchestrator", "intake", "intake_chat", "evaluate_intake", "approval_gate"):
                    yield sse({"type": "agent_end", "agent": current_agent})

                if not emitted_user_messages and home_chat_fallback_text.strip():
                    yield sse(
                        {
                            "type": "user_message",
                            "markdown": home_chat_fallback_text.strip(),
                            "source": "model_text_fallback",
                        }
                    )

                # Check if the graph is interrupted at approval_gate — emit
                # a dedicated event so the frontend knows to enable the
                # "Commence Deep Research" button (replaces string matching).
                try:
                    agent = req.app.state.agent
                    graph_state = await agent.aget_state(
                        {"configurable": {"thread_id": job_id}}
                    )
                    if graph_state.next:
                        logger.info(
                            "Graph interrupted at %s for job %s — emitting approval_required",
                            graph_state.next,
                            job_id,
                        )
                        yield sse({"type": "approval_required", "job_id": job_id})
                except Exception:
                    logger.debug(
                        "Could not check graph interrupt state for job %s",
                        job_id,
                        exc_info=True,
                    )

                report_path = OUTPUT_BASE_DIR / job_id / "report.json"
                report_ready = report_path.exists()
                yield sse({"type": "finish", "report_ready": report_ready})
                yield "data: [DONE]\n\n"

        except asyncio.CancelledError:
            if is_research:
                logger.info(
                    "SSE client disconnected for job %s — background task continues", job_id
                )
            return

        except Exception as e:
            error_event = build_exception_error_event(
                job_id,
                "research_sse" if is_research else "qa_sse",
                e,
            )
            logger.exception(
                "Chat stream failed job_id=%s mode=%s message_count=%d query=%r error_type=%s retryable=%s",
                job_id,
                "research" if is_research else "qa",
                len(messages_dict),
                preview_text(query),
                error_event["errorType"],
                error_event["retryable"],
            )
            yield sse(error_event)
            yield "data: [DONE]\n\n"

        finally:
            if is_research and job_state is not None and q is not None:
                unsubscribe(job_state, q)
                if job_state.status != JobStatus.RUNNING and job_state.subscriber_count == 0:
                    JOBS.pop(job_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
