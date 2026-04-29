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
import re
from uuid import uuid4

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

_RESEARCH_QUERY_RE = re.compile(
    r"Research Query:\s*(?P<query>.*)", re.IGNORECASE | re.DOTALL
)
_FRED_MACRO_TERMS = (
    "macro",
    "economic",
    "economy",
    "consumer",
    "labor",
    "inflation",
    "recession",
)
_RESEARCH_ACTION_TERMS = (
    "analyze",
    "compare",
    "build",
    "investigate",
    "answer",
    "are ",
    "is ",
    "should ",
)


def _extract_research_query(text: str) -> str:
    """Extract the user-facing research query from the job envelope."""
    match = _RESEARCH_QUERY_RE.search(text)
    if match:
        return match.group("query").strip()
    return text.strip()


def _is_actionable_fred_macro_request(text: str) -> bool:
    """Return True when a broad FRED macro prompt is ready for analyst execution."""
    query = _extract_research_query(text)
    lowered = query.lower()
    if "fred" not in lowered:
        return False
    if not any(term in lowered for term in _FRED_MACRO_TERMS):
        return False
    if not any(term in lowered for term in _RESEARCH_ACTION_TERMS):
        return False
    return True


def _actionable_fred_macro_summary(text: str) -> str:
    query = _extract_research_query(text)
    return (
        "Use FRED macro data to answer the user's question, selecting appropriate "
        f"economic indicators and using the latest available observations: {query}"
    )


# ---------------------------------------------------------------------------
# Model & graph nodes
# ---------------------------------------------------------------------------

_INTAKE_MODEL = "deepseek:deepseek-chat"


async def intake_chat_node(state: dict) -> dict:
    """Single-pass intake: one model call, execute emit_chat_message, return.

    Unlike a ReAct agent loop, this guarantees exactly one model turn,
    preventing the model from calling emit_chat_message in an infinite loop.
    """
    llm = init_chat_model(_INTAKE_MODEL).bind_tools([emit_chat_message])

    messages = [SystemMessage(content=INTAKE_SYSTEM_PROMPT)] + list(state["messages"])
    response = await llm.ainvoke(messages)

    result_messages = [response]

    # Execute any tool calls (should be exactly one emit_chat_message)
    for tc in response.tool_calls or []:
        if tc["name"] == "emit_chat_message":
            tool_result = emit_chat_message.invoke(tc["args"])
            result_messages.append(
                ToolMessage(content=str(tool_result), tool_call_id=tc["id"])
            )

    return {"messages": result_messages}


def _message_text(content: object) -> str:
    """Return user-visible text from LangChain text or content-block payloads."""
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
            if not isinstance(part, dict) or part.get("type") in (None, "text")
        )
    return str(content) if content else ""


def _clean_messages_for_eval(messages: list) -> list:
    """Extract only user/assistant conversational content for the evaluator.

    Strips out internal ToolMessages and converts assistant/user messages to
    fresh text-only messages. This is important because OpenAI rejects an
    assistant message with unresolved ``tool_calls`` unless matching
    ToolMessages immediately follow it, and the evaluator does not need those
    internal tool-call envelopes.
    """
    clean = []
    seen_content: set[str] = set()
    for msg in messages:
        # Skip ToolMessages (internal plumbing)
        if isinstance(msg, ToolMessage):
            continue
        if isinstance(msg, AIMessage):
            text = _message_text(msg.content)
            if not text.strip():
                continue
            if text.strip() in seen_content:
                continue
            seen_content.add(text.strip())
            clean.append(AIMessage(content=text))
            continue
        if isinstance(msg, HumanMessage):
            text = _message_text(msg.content)
            if not text.strip() or text.strip() in seen_content:
                continue
            seen_content.add(text.strip())
            clean.append(HumanMessage(content=text))
    return clean


async def evaluate_intake_node(state: dict) -> dict:
    """Structured-output LLM call — the deterministic completeness gate.

    Returns ``{research_summary: str}`` when complete, empty dict otherwise.
    The parent graph's conditional edge inspects ``research_summary`` to route.
    """
    clean = _clean_messages_for_eval(list(state["messages"]))
    latest_user_text = ""
    for msg in reversed(clean):
        if isinstance(msg, HumanMessage):
            latest_user_text = _message_text(msg.content)
            break

    if latest_user_text and _is_actionable_fred_macro_request(latest_user_text):
        summary = _actionable_fred_macro_summary(latest_user_text)
        logger.info("Intake deterministic FRED macro shortcut: %r", summary)
        return {"research_summary": summary}

    llm = init_chat_model(_INTAKE_MODEL).with_structured_output(IntakeEvaluation)
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
    "intake_chat_node",
    "emit_approval_message_node",
    "evaluate_intake_node",
]
