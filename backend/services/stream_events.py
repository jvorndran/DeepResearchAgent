"""LangGraph stream chunks → SSE event dicts and SSE wire formatting."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def serialize_lc_value(data: Any) -> Any:
    """Recursively serialize LangChain/Pydantic objects to plain dicts."""
    if isinstance(data, dict):
        return {k: serialize_lc_value(v) for k, v in data.items()}
    if isinstance(data, list):
        return [serialize_lc_value(v) for v in data]
    if isinstance(data, tuple):
        return tuple(serialize_lc_value(v) for v in data)
    if hasattr(data, "model_dump"):
        return data.model_dump()
    if hasattr(data, "dict"):
        return data.dict()
    return data


def agent_from_ns(ns: list) -> str | None:
    """Extract the innermost agent name from a LangGraph namespace list."""
    if not ns:
        return None
    last = ns[-1]
    return last.split(":")[0] if ":" in last else last


def parse_graph_update(
    ns: list, data: Any, prev_agent: str | None
) -> tuple[list[dict], str | None]:
    """
    Convert a raw LangGraph 'updates' payload into clean semantic events.
    Returns (events, current_agent_name).
    """
    events: list[dict] = []
    agent = agent_from_ns(ns)

    # Suppress agent_start/agent_end for top-level orchestrator nodes (intake, evaluate, etc.)
    _TOP_LEVEL_AGENTS = {"orchestrator", "intake", "intake_chat", "evaluate_intake", "approval_gate"}

    if agent != prev_agent:
        if prev_agent and prev_agent not in _TOP_LEVEL_AGENTS:
            events.append({"type": "agent_end", "agent": prev_agent})
        if agent and agent not in _TOP_LEVEL_AGENTS:
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
            msg = serialize_lc_value(msg)
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
                events.append(
                    {
                        "type": "tool_call",
                        "agent": agent,
                        "tool": name,
                        "args": args if isinstance(args, dict) else {},
                    }
                )

        msg_type = str(msg.get("type", ""))
        if "tool" in msg_type.lower() or msg.get("role") == "tool":
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            events.append(
                {
                    "type": "tool_result",
                    "agent": agent,
                    "tool": msg.get("name", ""),
                    "summary": str(content)[:300],
                }
            )

    return events, agent


def is_orchestrator_home_ai(meta: Any, token: Any) -> bool:
    if not token or str(getattr(token, "type", "")).lower() not in ("ai", "aimessagechunk"):
        return False
    if not isinstance(meta, dict):
        return True

    lc = meta.get("lc_agent_name") or ""
    node = meta.get("langgraph_node") or ""

    # Treat the intake agent and orchestrator as home-level (their messages go to the UI)
    if lc in ("orchestrator", "intake"):
        return True
    if lc and lc not in ("", "orchestrator", "intake"):
        return False
    return node in ("model", "model_request")


def markdown_from_tool_args(args: Any) -> Optional[str]:
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


def markdown_from_emit_chat_tool_event(event: dict) -> Optional[str]:
    if event.get("type") != "tool_call" or event.get("tool") != "emit_chat_message":
        return None
    return markdown_from_tool_args(event.get("args") or {})


async def process_research_chunks(
    raw_stream: AsyncIterator[Any],
) -> AsyncIterator[dict]:
    """
    Convert raw stream_research chunks into SSE event dicts (research / stream_telemetry=True mode).
    Yields event dicts — no sse() wrapping, that happens at the relay layer.
    """
    current_agent: str | None = None
    current_task_agent: str | None = None
    emitted_user_messages: set[str] = set()

    async for chunk in raw_stream:
        chunk_type = chunk.get("type")
        logger.debug("[BG] chunk type=%s ns=%s", chunk_type, chunk.get("ns", []))

        if chunk_type == "messages":
            token, meta = chunk.get("data", (None, None))
            is_home_ai = is_orchestrator_home_ai(meta, token)
            lc_agent = meta.get("lc_agent_name") if isinstance(meta, dict) else None
            agent_name = meta.get("langgraph_node") if isinstance(meta, dict) else None
            logger.debug(
                "[BG/messages] agent_name=%s lc_agent=%s is_home_ai=%s",
                agent_name,
                lc_agent,
                is_home_ai,
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
                    yield {"type": "text", "delta": text}
            if is_home_ai and token:
                for tc in getattr(token, "tool_calls", None) or []:
                    name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                    if name != "emit_chat_message":
                        continue
                    args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                    md = markdown_from_tool_args(args)
                    if md and md not in emitted_user_messages:
                        emitted_user_messages.add(md)
                        yield {"type": "user_message", "markdown": md}

        elif chunk_type in ("updates", "custom"):
            ns = chunk.get("ns", [])
            raw_data = serialize_lc_value(chunk.get("data", {}))
            events, current_agent = parse_graph_update(ns, raw_data, current_agent)
            logger.debug(
                "[BG/%s] parsed %d events current_agent=%s",
                chunk_type,
                len(events),
                current_agent,
            )
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
                md = markdown_from_emit_chat_tool_event(event)
                if md is not None and md not in emitted_user_messages:
                    emitted_user_messages.add(md)
                    yield {"type": "user_message", "markdown": md}
                yield event

    if current_task_agent:
        yield {"type": "agent_end", "agent": current_task_agent}
    if current_agent and current_agent not in ("orchestrator", "intake", "intake_chat", "evaluate_intake", "approval_gate"):
        yield {"type": "agent_end", "agent": current_agent}
