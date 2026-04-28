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
        state is not None
        and hasattr(state, "values")
        and bool(state.values.get("messages"))
    )

    # Manual override: user clicked "Commence Deep Research" but the graph
    # is not currently interrupted. This can happen when the approval click is
    # sent from the chat page after a prior home-page stream has already ended.
    # Keep checkpointed intake messages intact; replacing them with only the
    # synthetic approval text makes the execution phase finish without creating
    # report.json.
    if is_research_approval_message(last_user_message):
        if has_prior_state:
            return {"messages": [], "phase": "executing"}
        return {"messages": messages, "phase": "executing"}

    if has_prior_state and last_user_message:
        return {"messages": [last_user_message]}

    return {"messages": messages}


__all__ = ["get_last_user_message", "is_research_approval_message", "resolve_graph_input"]
