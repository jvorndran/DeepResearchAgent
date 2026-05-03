"""Compiled quality analyst subagent."""
from functools import lru_cache

from langchain.agents import create_agent
from langchain_core.runnables import RunnableLambda

from .prompts import QUALITY_ANALYST_DESCRIPTION, QUALITY_ANALYST_SYSTEM_PROMPT
from .tools import load_report_for_review, submit_quality_decision

def _quality_analyst_agent():
    return create_agent(
        "deepseek:deepseek-chat",
        system_prompt=QUALITY_ANALYST_SYSTEM_PROMPT,
        tools=[load_report_for_review, submit_quality_decision],
        name="quality-analyst",
    )


def _invoke_quality_analyst(state: dict) -> dict:
    return _normalize_terminal_quality_decision(_quality_analyst_agent().invoke(state))


async def _ainvoke_quality_analyst(state: dict) -> dict:
    return _normalize_terminal_quality_decision(
        await _quality_analyst_agent().ainvoke(state)
    )


QUALITY_ANALYST_SUBAGENT = {
    "name": "quality-analyst",
    "description": QUALITY_ANALYST_DESCRIPTION,
    # Use a compiled agent instead of a declarative Deep Agents subagent. Declarative
    # subagents receive the default filesystem/shell middleware, which lets QA drift
    # into open-ended `execute` probes after it has enough evidence to decide.
    "runnable": RunnableLambda(
        _invoke_quality_analyst,
        afunc=_ainvoke_quality_analyst,
        name="quality-analyst",
    ),
}
