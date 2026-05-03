from types import SimpleNamespace

import pytest
from langgraph.types import Command

from agents.graph_input import resolve_graph_input


class FakeAgent:
    def __init__(self, *, next_nodes=(), messages=None):
        self._state = SimpleNamespace(
            next=next_nodes,
            values={"messages": messages or []},
        )

    async def aget_state(self, _config):
        return self._state


APPROVAL_MESSAGE = {
    "role": "user",
    "content": "Please begin the research now with the parameters discussed.",
    "metadata": {"action": "commence_research"},
}


@pytest.mark.asyncio
async def test_commence_on_interrupted_thread_resumes_approval_gate():
    result = await resolve_graph_input(
        FakeAgent(next_nodes=("approval_gate",), messages=[{"role": "user", "content": "q"}]),
        {"configurable": {"thread_id": "job_1"}},
        [APPROVAL_MESSAGE],
    )

    assert isinstance(result, Command)
    assert result.resume == "approved"


@pytest.mark.asyncio
async def test_commence_on_existing_thread_preserves_checkpointed_messages():
    result = await resolve_graph_input(
        FakeAgent(messages=[{"role": "user", "content": "Analyze GDP vs unemployment"}]),
        {"configurable": {"thread_id": "job_1"}},
        [APPROVAL_MESSAGE],
    )

    assert result["phase"] == "executing"
    assert len(result["messages"]) == 1
    assert "Research is approved" in result["messages"][0]["content"]
    assert "Analyze GDP vs unemployment" in result["messages"][0]["content"]


@pytest.mark.asyncio
async def test_commence_on_existing_thread_overrides_pending_clarification_wait():
    result = await resolve_graph_input(
        FakeAgent(
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Job ID: improver-1\n\nResearch Query: Compare current "
                        "cycle analogs and include Apple and Microsoft."
                    ),
                },
                {
                    "role": "assistant",
                    "content": "Let's wait for the user's answers.",
                },
            ]
        ),
        {"configurable": {"thread_id": "job_1"}},
        [APPROVAL_MESSAGE],
    )

    kickoff = result["messages"][0]["content"]
    assert result["phase"] == "executing"
    assert "Ignore earlier intake clarification prompts" in kickoff
    assert "do not wait for more answers" in kickoff
    assert "Compare current cycle analogs" in kickoff


@pytest.mark.asyncio
async def test_commence_without_prior_thread_starts_execution_with_request_messages():
    result = await resolve_graph_input(
        FakeAgent(),
        {"configurable": {"thread_id": "job_1"}},
        [APPROVAL_MESSAGE],
    )

    assert result == {"messages": [APPROVAL_MESSAGE], "phase": "executing"}
