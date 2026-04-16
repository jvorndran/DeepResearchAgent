"""Tool that enforces the Phase 1 → Phase 2 human-in-the-loop gate.

The orchestrator calls this at the end of intake (Phase 1) to pause the graph
until the user clicks "Commence Deep Research" in the UI. LangGraph's
`interrupt()` saves the checkpoint; the backend resumes with
`Command(resume="approved")` when the chat page request arrives with the
approval action metadata.
"""

from langchain_core.tools import tool
from langgraph.types import interrupt


@tool
def request_research_approval(summary: str = "") -> str:
    """
    Call this tool at the end of Phase 1 — after `emit_chat_message` has shown
    the 'Commence Deep Research' message — to pause the graph and wait for user
    confirmation. The pipeline will not proceed to `task()` until the user
    clicks the button and the backend resumes.

    Args:
        summary: One-sentence description of what research will be run (optional).
    """
    approval_status = interrupt(
        {
            "type": "research_approval_needed",
            "summary": summary,
            "approval_action": "commence_research",
        }
    )
    if approval_status == "approved":
        return "Research approved by user. Proceed with task() delegation to data-engineer."
    else:
        return (
            f"Research NOT approved. User feedback: '{approval_status}'. "
            "Ask clarifying questions or adjust parameters, then call request_research_approval again."
        )
