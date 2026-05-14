"""Shared graph input resolution for run_research / stream_research."""

from typing import Any, Dict, Union

from langgraph.types import Command

from .data_toolbox import format_data_toolbox_for_prompt


def _message_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("content") or ""))
            else:
                parts.append(str(part))
        return "".join(parts)
    return str(content) if content else ""


def _state_message_text(message: Any) -> str:
    if isinstance(message, dict):
        return _message_content_text(message.get("content"))
    return _message_content_text(getattr(message, "content", ""))


def _latest_state_user_request(state: Any) -> str:
    values = getattr(state, "values", {}) if state is not None else {}
    for message in reversed(values.get("messages") or []):
        role = message.get("role") if isinstance(message, dict) else None
        is_user = role == "user" or type(message).__name__ == "HumanMessage"
        if not is_user:
            continue
        text = _state_message_text(message).strip()
        if not text:
            continue
        marker = "Research Query:"
        if marker.lower() in text.lower():
            return text.split(marker, 1)[-1].strip()
        return text
    return ""


def _execution_override_message(state: Any) -> dict[str, str]:
    values = getattr(state, "values", {}) if state is not None else {}
    research_summary = str(values.get("research_summary") or "").strip()
    approved_request = _latest_state_user_request(state)
    summary_line = (
        f"Research summary: {research_summary}"
        if research_summary
        else "Research summary: Use the approved research request from the conversation."
    )
    request_line = (
        f"Full approved user request for `original_query`: {approved_request}"
        if approved_request
        else "Full approved user request for `original_query`: use the latest user research request from the conversation."
    )
    toolbox_line = format_data_toolbox_for_prompt(values.get("data_toolbox"))
    return {
        "role": "user",
        "content": (
            "Research is approved. Begin the execution pipeline now. "
            "Ignore earlier intake clarification prompts and do not wait for more "
            "answers. On your first execution turn, emit no assistant prose and "
            "make exactly two tool calls: first `emit_chat_message` with a brief "
            'status update, then `task` with `subagent_type="data-engineer"`. '
            f"{summary_line}\n{request_line}\n{toolbox_line}"
        ),
    }


def get_last_user_message(messages: list[dict] | None) -> dict[str, Any] | None:
    if messages and messages[-1].get("role") == "user":
        return messages[-1]
    return None


def is_research_approval_message(message: dict[str, Any] | None) -> bool:
    if not message:
        return False
    metadata = message.get("metadata")
    return isinstance(metadata, dict) and metadata.get("action") == "commence_research"


async def resolve_graph_input(
    agent: Any, config: dict[str, Any], messages: list[dict] | None
) -> Union[Command, Dict[str, Any]]:
    """
    Build the same graph input as the legacy duplicated paths:
    interrupted + approval metadata vs normal message injection.
    """
    state = None
    is_interrupted = False
    try:
        state = await agent.aget_state(config)
        is_interrupted = bool(state.next)
    except Exception:
        pass

    last_user_message = get_last_user_message(messages)

    if is_interrupted:
        last_content = last_user_message.get("content", "") if last_user_message else ""
        if is_research_approval_message(last_user_message):
            return Command(resume="approved")
        return Command(
            resume=last_content,
            update={"messages": [last_user_message]} if last_user_message else {},
        )

    # Re-invocation after a previous execution completed (graph at END).
    # The checkpoint already contains the full conversation history from
    # prior runs.  Only pass the NEW user message to avoid duplicating
    # every message via the add_messages reducer.
    has_prior_state = (
        state is not None and hasattr(state, "values") and bool(state.values.get("messages"))
    )

    # Manual override: user clicked "Commence Deep Research" but the graph
    # is not currently interrupted. This can happen when the approval click is
    # sent from the chat page after a prior home-page stream has already ended.
    # Keep checkpointed intake messages intact; replacing them with only the
    # synthetic approval text makes the execution phase finish without creating
    # report.json.
    if is_research_approval_message(last_user_message):
        if has_prior_state:
            return {"messages": [_execution_override_message(state)], "phase": "executing"}
        return {"messages": messages, "phase": "executing"}

    if has_prior_state and last_user_message:
        return {"messages": [last_user_message]}

    return {"messages": messages}


__all__ = ["get_last_user_message", "is_research_approval_message", "resolve_graph_input"]
