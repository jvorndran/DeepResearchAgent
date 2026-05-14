"""Orchestrator LangGraph state schema."""
from typing import Any, NotRequired

from .common import Annotated, AnyMessage, TypedDict, add_messages

# =============================================================================
# STATE SCHEMA
# =============================================================================

class OrchestratorState(dict):
    """Parent graph state for the deterministic orchestrator pipeline.

    Uses ``add_messages`` reducer so both subgraph agents and deterministic
    nodes can append messages without overwriting.
    """
    messages: Annotated[list[AnyMessage], add_messages]
    phase: str  # "intake" | "executing"
    research_summary: str
    data_toolbox: dict[str, Any]


# Re-declare as a proper TypedDict for LangGraph (it needs __annotations__).
from typing import TypedDict  # noqa: E402

class OrchestratorState(TypedDict):  # type: ignore[no-redef]  # noqa: F811
    messages: Annotated[list[AnyMessage], add_messages]
    phase: str
    research_summary: str
    data_toolbox: NotRequired[dict[str, Any]]
