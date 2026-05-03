"""Deterministic nodes and routing helpers for orchestrator graph."""
import json
import re
from typing import Any

from .common import FredMCPRequiredError, HumanMessage, MCPTimeoutError, ToolMessage, google, httpx, interrupt
from .prompts import EXECUTION_SYSTEM_PROMPT

# =============================================================================
# DETERMINISTIC NODE FUNCTIONS
# =============================================================================


def approval_gate_node(state: dict) -> dict:
    """Deterministic interrupt — pauses graph for user approval.

    On resume with ``"approved"`` → sets phase to executing.
    On resume with any other string → loops back to intake with feedback.
    """
    result = interrupt(
        {
            "type": "research_approval_needed",
            "summary": state.get("research_summary", ""),
            "approval_action": "commence_research",
        }
    )
    if result == "approved":
        return {
            "phase": "executing",
            "messages": [_build_execution_kickoff_message(state)],
        }
    # User sent feedback instead of approving — loop back to intake.
    return {
        "phase": "intake",
        "research_summary": "",
        "messages": [HumanMessage(content=str(result))],
    }


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
    return str(content)


def _latest_approved_user_request(state: dict) -> str:
    for message in reversed(state.get("messages") or []):
        if not isinstance(message, HumanMessage):
            continue
        text = _message_content_text(message.content).strip()
        if not text:
            continue
        match = re.search(r"Research Query:\s*(.+)\s*$", text, flags=re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else text
    return ""


def _build_execution_kickoff_message(state: dict) -> HumanMessage:
    """Create the post-approval instruction consumed by the execution agent."""
    research_summary = str(state.get("research_summary") or "").strip()
    summary_line = (
        f"Research summary: {research_summary}"
        if research_summary
        else "Research summary: Use the approved research request from the conversation."
    )
    approved_request = _latest_approved_user_request(state)
    request_line = (
        f"Full approved user request for `original_query`: {approved_request}"
        if approved_request
        else "Full approved user request for `original_query`: use the latest user research request from the conversation."
    )
    return HumanMessage(
        content=(
            "Research is approved. Begin the execution pipeline now. "
            "On your first execution turn, emit no assistant prose and make exactly "
            "two tool calls: first `emit_chat_message` with a brief status update, "
            "then `task` with `subagent_type=\"data-engineer\"`. "
            f"{summary_line}\n{request_line}"
        )
    )


# =============================================================================
# CONDITIONAL EDGE FUNCTIONS
# =============================================================================


def route_by_phase(state: dict) -> str:
    """Entry router: send to intake or execution based on current phase."""
    return state.get("phase") or "intake"


def route_after_evaluate(state: dict) -> str:
    """After evaluate_intake: complete if summary was set, else wait."""
    if state.get("research_summary"):
        return "complete"
    return "needs_more"


def route_after_approval(state: dict) -> str:
    """After approval_gate: execute or loop back to intake (feedback)."""
    if state.get("phase") == "executing":
        return "executing"
    return "intake"


def _fred_setup_error_payload(error: FredMCPRequiredError) -> dict[str, Any]:
    """Build a compact, actionable setup error for required FRED failures."""
    message = str(error)
    lowered = message.lower()
    retryable = False
    if "fetch failed" in lowered or "network" in lowered or "timeout" in lowered:
        retryable = True
        hint = (
            "FRED MCP loaded, but its outbound FRED API request failed. "
            "Check network/DNS/proxy access from the backend environment and retry after access is restored; "
            "do not re-enable FMP for this FRED-only flow."
        )
    elif "api_key" in lowered or "api key" in lowered or "unauthorized" in lowered:
        hint = (
            "FRED is required for this research flow. Verify the FRED_API_KEY value "
            "available to the FRED MCP subprocess before retrying."
        )
    else:
        hint = (
            "FRED is required for this research flow. Verify FRED_MCP_SERVER_PATH, "
            "FRED_API_KEY, and backend network access before retrying."
        )

    return {
        "type": "fred_mcp_required",
        "message": message,
        "phase": "setup",
        "retryable": retryable,
        "agent_recoverable": False,
        "hint": hint,
    }


def _is_transient_stream_error(error: Exception) -> bool:
    """Return True for provider failures that can be retried from a checkpoint."""
    err_msg = str(error).lower()
    if isinstance(error, google.genai.errors.ServerError):
        return True
    if isinstance(
        error,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadError,
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
        ),
    ):
        return True
    return (
        "500 internal" in err_msg
        or "503 service unavailable" in err_msg
        or "408 request timeout" in err_msg
        or "429" in err_msg
        or "api connection error" in err_msg
        or "connection error" in err_msg
        or "readerror" in err_msg
    )
