"""
Intake phase: deterministic clarification loop for the orchestrator.

Nodes:
- ``intake_chat``: lightweight agent (emit_chat_message only) that asks
  clarifying questions about the user's research query.
- ``evaluate_intake``: structured-output LLM call that decides whether enough
  information has been gathered (tickers, metrics, horizon, scope).
- ``emit_approval_message``: pure function that injects the
  "Commence Deep Research" message so the frontend shows the approval button.
"""

import logging
from uuid import uuid4

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from .chat_surface_tool import emit_chat_message

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured output schema for the evaluate gate
# ---------------------------------------------------------------------------

class IntakeEvaluation(BaseModel):
    """Structured evaluation of whether intake is complete."""

    complete: bool = Field(
        description="True if the user has provided enough information to begin research"
    )
    summary: str = Field(
        description=(
            "One-sentence summary of the research to be conducted. "
            "Write this even if complete is False (best-effort so far)."
        )
    )
    missing: list[str] = Field(
        default_factory=list,
        description="List of missing pieces of information. Empty when complete is True.",
    )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

INTAKE_SYSTEM_PROMPT = """\
# ROLE
You are the **Research Intake Specialist**. Your job is to understand the
user's financial research query and ask targeted clarifying questions until the
request is fully specified.

# RULES
1. Call `emit_chat_message(markdown=...)` exactly once per turn with your
   response to the user. Do NOT reply with plain text — always use the tool.
2. Ask only the minimum questions needed. Do not over-interrogate.
3. If the query is already fully specified on the first message, confirm your
   understanding via `emit_chat_message` and stop.
4. Focus on: **tickers / assets**, **metrics / indicators**, **time horizon**,
   and **scope / angle** of the analysis.

# TONE
Professional, concise, analytical. Use bullet lists for questions.
"""

EVALUATE_INTAKE_PROMPT = """\
You are an evaluation function. Given the conversation between a user and a
research intake specialist, decide whether the research request is fully
specified and ready to execute.

A request is **complete** when the following are clear (explicitly stated or
strongly implied):
- What asset(s), ticker(s), or economic indicator(s) to analyze
- What metric(s) or relationship(s) to examine
- The time horizon or date range (can be implicit, e.g. "recent trends")
- The scope or angle of the analysis

Be pragmatic: if a reasonable analyst could begin work without further
questions, mark it complete. Do NOT require every detail to be spelled out.

Return your evaluation as structured JSON.
"""


# ---------------------------------------------------------------------------
# Intake agent factory
# ---------------------------------------------------------------------------

_INTAKE_MODEL = "deepseek:deepseek-chat"


def _create_intake_agent():
    """Lightweight agent for intake Q&A — only has emit_chat_message."""
    return create_agent(
        model=_INTAKE_MODEL,
        tools=[emit_chat_message],
        system_prompt=INTAKE_SYSTEM_PROMPT,
        name="intake",
    )


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


def _clean_messages_for_eval(messages: list) -> list:
    """Extract only user/assistant conversational content for the evaluator.

    Strips out internal ToolMessages, AIMessages that contain only tool_calls
    (no text content), and deduplicates by content so the evaluator sees a
    clean human ↔ assistant conversation.
    """
    clean = []
    seen_content: set[str] = set()
    for msg in messages:
        # Skip ToolMessages (internal plumbing)
        if isinstance(msg, ToolMessage):
            continue
        # Skip AIMessages that are pure tool-call wrappers (no user-visible text)
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, list):
                text = "".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            else:
                text = str(content) if content else ""
            if not text.strip():
                continue
            # Deduplicate identical assistant messages
            if text.strip() in seen_content:
                continue
            seen_content.add(text.strip())
        if isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if content.strip() in seen_content:
                continue
            seen_content.add(content.strip())
        clean.append(msg)
    return clean


async def evaluate_intake_node(state: dict) -> dict:
    """Structured-output LLM call — the deterministic completeness gate.

    Returns ``{research_summary: str}`` when complete, empty dict otherwise.
    The parent graph's conditional edge inspects ``research_summary`` to route.
    """
    llm = init_chat_model(_INTAKE_MODEL).with_structured_output(IntakeEvaluation)
    clean = _clean_messages_for_eval(list(state["messages"]))
    messages = [SystemMessage(content=EVALUATE_INTAKE_PROMPT)] + clean
    result: IntakeEvaluation = await llm.ainvoke(messages)

    logger.info(
        "Intake evaluation: complete=%s summary=%r missing=%s",
        result.complete,
        result.summary,
        result.missing,
    )

    if result.complete:
        return {"research_summary": result.summary}
    return {}


def emit_approval_message_node(state: dict) -> dict:
    """Deterministically inject the 'Commence Deep Research' message.

    Emits a synthetic ``emit_chat_message`` tool call + result so the
    streaming layer picks it up identically to a real tool invocation.
    """
    approval_text = (
        "I now have what I need to proceed. Please click "
        "**Commence Deep Research** below to begin."
    )
    tool_call_id = str(uuid4())
    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "emit_chat_message",
                "args": {"markdown": approval_text},
                "id": tool_call_id,
            }
        ],
    )
    tool_msg = ToolMessage(
        content="Message recorded for the chat UI.",
        tool_call_id=tool_call_id,
    )
    return {"messages": [ai_msg, tool_msg]}


__all__ = [
    "IntakeEvaluation",
    "_create_intake_agent",
    "emit_approval_message_node",
    "evaluate_intake_node",
]
