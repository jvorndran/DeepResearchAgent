"""Shared graph input resolution for run_research / stream_research."""

from typing import Any, Dict, Union

from langgraph.types import Command


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
    try:
        state = await agent.aget_state(config)
        is_interrupted = bool(state.next)
    except Exception:
        is_interrupted = False

    if is_interrupted:
        last_user_message = get_last_user_message(messages)
        last_content = last_user_message.get("content", "") if last_user_message else ""
        if is_research_approval_message(last_user_message):
            return Command(resume="approved")
        return Command(
            resume=last_content,
            update={"messages": [last_user_message]} if last_user_message else {},
        )
    return {"messages": messages}


__all__ = ["get_last_user_message", "is_research_approval_message", "resolve_graph_input"]
