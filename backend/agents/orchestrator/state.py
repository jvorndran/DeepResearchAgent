"""Orchestrator LangGraph state schema."""
from typing import Annotated, Any, NotRequired, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

# =============================================================================
# STATE SCHEMA
# =============================================================================

class OrchestratorState(TypedDict):
    """Parent graph state for the deterministic orchestrator pipeline."""

    messages: Annotated[list[AnyMessage], add_messages]
    phase: str
    research_summary: str
    data_toolbox: NotRequired[dict[str, Any]]
