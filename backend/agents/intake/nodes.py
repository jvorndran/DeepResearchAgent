"""LangGraph nodes for intake chat, evaluation, and approval emission."""
import logging
from uuid import uuid4

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ..chat_surface_tool import emit_chat_message
from .heuristics import (
    _actionable_fred_macro_summary,
    _actionable_macro_scenario_summary,
    _is_actionable_fred_macro_request,
    _is_actionable_macro_scenario_request,
)
from .prompts import EVALUATE_INTAKE_PROMPT, INTAKE_SYSTEM_PROMPT
from .schema import IntakeEvaluation

logger = logging.getLogger(__name__)

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
    if latest_user_text and _is_actionable_macro_scenario_request(latest_user_text):
        summary = _actionable_macro_scenario_summary(latest_user_text)
        logger.info("Intake deterministic macro scenario shortcut: %r", summary)
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
