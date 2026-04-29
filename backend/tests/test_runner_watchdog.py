import asyncio

import pytest

from agents import orchestrator
from agents.orchestrator import FredMCPRequiredError
from tests.runner import Watchdog
from tests.runner import format_stream_error
from tests.runner import format_update_summary
from tests.runner import is_approval_interrupt_update
from tests.runner import is_incomplete_streaming_tool_call
from tests.runner import is_setup_error
from tests.runner import run_research_loop


class FakeInterrupt:
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"FakeInterrupt(value={self.value!r})"


def test_watchdog_stops_on_repeated_identical_tool_call():
    watchdog = Watchdog(
        max_runtime_seconds=900,
        max_tool_calls=120,
        max_identical_tool_calls=8,
        max_fred_search_calls=40,
        max_model_messages=80,
    )

    for i in range(8):
        assert watchdog.observe_tool_call("fred_get_series", {"series_id": "GDP"}, i) is None

    reason = watchdog.observe_tool_call("fred_get_series", {"series_id": "GDP"}, 9.0)

    assert reason is not None
    assert "identical tool call repeated" in reason


def test_watchdog_allows_repeated_fred_search_calls_until_search_budget():
    watchdog = Watchdog(
        max_runtime_seconds=900,
        max_tool_calls=120,
        max_identical_tool_calls=2,
        max_fred_search_calls=40,
        max_model_messages=80,
    )

    for i in range(40):
        assert watchdog.observe_tool_call("fred_search", {"query": "inflation"}, i) is None

    reason = watchdog.observe_tool_call("fred_search", {"query": "inflation"}, 41.0)

    assert reason is not None
    assert "fred_search budget exceeded" in reason


def test_incomplete_streaming_tool_call_detection():
    assert is_incomplete_streaming_tool_call("", {}) is True
    assert is_incomplete_streaming_tool_call(None, None) is True
    assert is_incomplete_streaming_tool_call("fred_get_series", {}) is False
    assert is_incomplete_streaming_tool_call("", {"series_id": "GDP"}) is False


def test_watchdog_stops_on_fred_search_budget():
    watchdog = Watchdog(
        max_runtime_seconds=900,
        max_tool_calls=60,
        max_identical_tool_calls=99,
        max_fred_search_calls=2,
        max_model_messages=80,
    )

    assert watchdog.observe_tool_call("fred_search", {"query": "GDP"}, 1.0) is None
    assert watchdog.observe_tool_call("fred_search", {"query": "CPI"}, 2.0) is None

    reason = watchdog.observe_tool_call("fred_search", {"query": "unemployment"}, 3.0)

    assert reason is not None
    assert "fred_search budget exceeded" in reason


def test_runner_marks_stream_errors_as_stopped_early(monkeypatch, tmp_path):
    async def fake_stream_research(**_kwargs):
        yield {
            "error": {
                "type": "fred_mcp_required",
                "message": "FRED MCP probe failed",
            }
        }

    monkeypatch.setattr("tests.runner.stream_research", fake_stream_research)
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))

    watchdog = Watchdog(
        max_runtime_seconds=900,
        max_tool_calls=60,
        max_identical_tool_calls=2,
        max_fred_search_calls=10,
        max_model_messages=80,
    )

    asyncio.run(run_research_loop("query", "job-test", watchdog))

    log_text = (tmp_path / "job-test" / "agent_execution.log").read_text()
    assert "fred_mcp_required: FRED MCP probe failed" in log_text
    assert "STOPPED_EARLY" in log_text
    assert "STOP_REASON: fred_mcp_required: FRED MCP probe failed" in log_text


def test_runner_marks_setup_stream_errors_as_setup_failed(monkeypatch, tmp_path):
    async def fake_stream_research(**_kwargs):
        yield {
            "error": {
                "type": "fred_mcp_required",
                "message": "FRED MCP probe failed",
                "phase": "setup",
                "retryable": False,
            }
        }

    monkeypatch.setattr("tests.runner.stream_research", fake_stream_research)
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))

    watchdog = Watchdog(
        max_runtime_seconds=900,
        max_tool_calls=60,
        max_identical_tool_calls=2,
        max_fred_search_calls=10,
        max_model_messages=80,
    )

    asyncio.run(run_research_loop("query", "job-test", watchdog))

    log_text = (tmp_path / "job-test" / "agent_execution.log").read_text()
    assert "fred_mcp_required: FRED MCP probe failed" in log_text
    assert "SETUP_FAILED" in log_text
    assert "STOPPED_EARLY" not in log_text
    assert "STOP_REASON: fred_mcp_required: FRED MCP probe failed" in log_text


def test_format_stream_error_includes_setup_metadata():
    reason = format_stream_error(
        {
            "type": "fred_mcp_required",
            "message": "FRED MCP probe failed",
            "phase": "setup",
            "retryable": False,
            "agent_recoverable": False,
            "hint": "Verify FRED_API_KEY.",
        }
    )

    assert reason.startswith("fred_mcp_required: FRED MCP probe failed")
    assert "phase=setup" in reason
    assert "retryable=False" in reason
    assert "agent_recoverable=False" in reason
    assert "hint=Verify FRED_API_KEY." in reason


def test_is_setup_error_only_matches_setup_phase():
    assert is_setup_error({"phase": "setup"}) is True
    assert is_setup_error({"phase": "execution"}) is False
    assert is_setup_error({}) is False
    assert is_setup_error(None) is False


def test_update_summary_handles_interrupt_tuple():
    summary = format_update_summary(
        (FakeInterrupt({"type": "research_approval_needed"}),)
    )

    assert summary.startswith("tuple:")
    assert "research_approval_needed" in summary


def test_detects_approval_interrupt_update():
    assert (
        is_approval_interrupt_update(
            {"__interrupt__": (FakeInterrupt({"type": "research_approval_needed"}),)}
        )
        is True
    )
    assert is_approval_interrupt_update({"__interrupt__": (FakeInterrupt({}),)}) is False
    assert is_approval_interrupt_update({"other": {}}) is False


def test_runner_auto_approves_approval_interrupt(monkeypatch, tmp_path):
    calls = []

    async def fake_stream_research(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            yield {
                "type": "updates",
                "data": {
                    "evaluate_intake": {"research_summary": "summary"},
                    "__interrupt__": (
                        FakeInterrupt({"type": "research_approval_needed"}),
                    ),
                },
            }
            return
        yield {
            "type": "updates",
            "data": {"execute": {"messages": []}},
        }

    monkeypatch.setattr("tests.runner.stream_research", fake_stream_research)
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))

    watchdog = Watchdog(
        max_runtime_seconds=900,
        max_tool_calls=60,
        max_identical_tool_calls=2,
        max_fred_search_calls=10,
        max_model_messages=80,
    )

    asyncio.run(run_research_loop("query", "job-test", watchdog))

    log_text = (tmp_path / "job-test" / "agent_execution.log").read_text()
    assert len(calls) == 2
    assert calls[0]["messages"] is None
    assert calls[1]["messages"][0]["metadata"]["action"] == "commence_research"
    assert "AUTO APPROVE" in log_text
    assert "COMPLETED" in log_text


def test_runner_forces_execution_after_incomplete_intake(monkeypatch, tmp_path):
    calls = []

    async def fake_stream_research(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            yield {
                "type": "updates",
                "data": {"evaluate_intake": {}},
            }
            return
        yield {
            "type": "updates",
            "data": {"execute": {"messages": []}},
        }

    monkeypatch.setattr("tests.runner.stream_research", fake_stream_research)
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))

    watchdog = Watchdog(
        max_runtime_seconds=900,
        max_tool_calls=60,
        max_identical_tool_calls=2,
        max_fred_search_calls=10,
        max_model_messages=80,
    )

    asyncio.run(run_research_loop("ambiguous query", "job-test", watchdog))

    log_text = (tmp_path / "job-test" / "agent_execution.log").read_text()
    assert len(calls) == 2
    assert calls[0]["messages"] is None
    assert calls[1]["messages"][0]["metadata"]["action"] == "commence_research"
    assert "FORCE EXECUTE" in log_text
    assert "COMPLETED" in log_text


@pytest.mark.asyncio
async def test_stream_research_yields_fred_setup_error(monkeypatch):
    async def raise_fred_error(**_kwargs):
        raise FredMCPRequiredError("FRED MCP probe failed")

    monkeypatch.setattr(orchestrator, "create_orchestrator", raise_fred_error)

    events = [
        event
        async for event in orchestrator.stream_research(
            query="query",
            job_id="job-test",
        )
    ]

    assert events[0]["error"]["type"] == "fred_mcp_required"
    assert events[0]["error"]["message"] == "FRED MCP probe failed"
    assert events[0]["error"]["phase"] == "setup"
    assert events[0]["error"]["retryable"] is False
    assert events[0]["error"]["agent_recoverable"] is False
    assert "FRED is required" in events[0]["error"]["hint"]


@pytest.mark.asyncio
async def test_stream_research_fred_fetch_failure_hint_is_network_specific(monkeypatch):
    async def raise_fred_error(**_kwargs):
        raise FredMCPRequiredError(
            "FRED MCP is required but the GDP probe failed. "
            "Original error: FRED MCP request 'fred_get_series(GDP)' failed: fetch failed"
        )

    monkeypatch.setattr(orchestrator, "create_orchestrator", raise_fred_error)

    events = [
        event
        async for event in orchestrator.stream_research(
            query="query",
            job_id="job-test",
        )
    ]

    assert events[0]["error"]["type"] == "fred_mcp_required"
    assert events[0]["error"]["phase"] == "setup"
    assert events[0]["error"]["retryable"] is True
    assert events[0]["error"]["agent_recoverable"] is False
    assert "outbound FRED API request failed" in events[0]["error"]["hint"]
    assert "do not re-enable FMP" in events[0]["error"]["hint"]
