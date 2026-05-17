import asyncio
import json

import httpx
import pytest

from agents import orchestrator
from agents.orchestrator import FredMCPRequiredError
from tests.runner import Watchdog
from tests.runner import format_fatal_exception
from tests.runner import format_stream_error
from tests.runner import format_update_summary
from tests.runner import has_uninformative_tool_args
from tests.runner import is_approval_interrupt_update
from tests.runner import is_incomplete_streaming_tool_call
from tests.runner import is_setup_error
from tests.runner import run_research_loop


class FakeInterrupt:
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"FakeInterrupt(value={self.value!r})"


class FakeMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class ToolMessage(FakeMessage):
    def __init__(self, content="", name="task"):
        super().__init__(content=content)
        self.name = name


def read_runner_artifacts(tmp_path):
    job_dir = tmp_path / "job-test"
    status = json.loads((job_dir / "runner_status.json").read_text())
    diagnostics = json.loads((job_dir / "trace_diagnostics.json").read_text())
    digest = (job_dir / "trace-digest.md").read_text()
    spans = [
        json.loads(line)
        for line in (job_dir / "phoenix_spans.jsonl").read_text().splitlines()
        if line.strip()
    ]
    return status, diagnostics, digest, spans


def span_event_types(spans):
    return {
        (span.get("attributes") or {}).get("event_type")
        for span in spans
        if isinstance(span.get("attributes"), dict)
    }


@pytest.fixture(autouse=True)
def local_runner_tracing(monkeypatch):
    monkeypatch.setenv("RUNNER_TRACE_EXPORT_MODE", "local")
    monkeypatch.delenv("RUNNER_REQUIRE_PHOENIX", raising=False)


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


def test_watchdog_does_not_treat_empty_required_tool_args_as_identical():
    watchdog = Watchdog(
        max_runtime_seconds=900,
        max_tool_calls=120,
        max_identical_tool_calls=2,
        max_fred_search_calls=40,
        max_model_messages=80,
    )

    for i in range(10):
        assert watchdog.observe_tool_call("execute", {}, i) is None
        assert watchdog.observe_tool_call("read_file", {}, i) is None
        assert watchdog.observe_tool_call("write_file", {}, i) is None
        assert watchdog.observe_tool_call("edit_file", {}, i) is None
        assert watchdog.observe_tool_call("fred_get_series", {}, i) is None
        assert watchdog.observe_tool_call("bls_get_series", {}, i) is None

    assert watchdog.tool_calls == 60
    assert watchdog.identical_tool_calls["execute:{}"] == 0
    assert watchdog.identical_tool_calls["read_file:{}"] == 0
    assert watchdog.identical_tool_calls["write_file:{}"] == 0
    assert watchdog.identical_tool_calls["edit_file:{}"] == 0
    assert watchdog.identical_tool_calls["fred_get_series:{}"] == 0
    assert watchdog.identical_tool_calls["bls_get_series:{}"] == 0


def test_watchdog_still_flags_repeated_execute_when_args_are_visible():
    watchdog = Watchdog(
        max_runtime_seconds=900,
        max_tool_calls=120,
        max_identical_tool_calls=2,
        max_fred_search_calls=40,
        max_model_messages=80,
    )

    assert watchdog.observe_tool_call("execute", {"cmd": "pytest"}, 1.0) is None
    assert watchdog.observe_tool_call("execute", {"cmd": "pytest"}, 2.0) is None
    reason = watchdog.observe_tool_call("execute", {"cmd": "pytest"}, 3.0)

    assert reason is not None
    assert "identical tool call repeated" in reason


def test_watchdog_still_flags_repeated_read_file_when_args_are_visible():
    watchdog = Watchdog(
        max_runtime_seconds=900,
        max_tool_calls=120,
        max_identical_tool_calls=2,
        max_fred_search_calls=40,
        max_model_messages=80,
    )

    args = {"file_path": "/tmp/analysis.py", "offset": 1}
    assert watchdog.observe_tool_call("read_file", args, 1.0) is None
    assert watchdog.observe_tool_call("read_file", args, 2.0) is None
    reason = watchdog.observe_tool_call("read_file", args, 3.0)

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


def test_uninformative_tool_args_detection_matches_empty_required_arg_tools():
    assert has_uninformative_tool_args("execute", {}) is True
    assert has_uninformative_tool_args("execute", None) is True
    assert has_uninformative_tool_args("execute", {"cmd": "pytest"}) is False
    assert has_uninformative_tool_args("read_file", {}) is True
    assert has_uninformative_tool_args("read_file", {"file_path": "/tmp/a.py"}) is False
    assert has_uninformative_tool_args("write_file", {}) is True
    assert has_uninformative_tool_args("edit_file", {}) is True
    assert has_uninformative_tool_args("fred_get_series", {}) is True
    assert has_uninformative_tool_args("fred_get_series", {"series_id": "GDP"}) is False
    assert has_uninformative_tool_args("bls_get_series", {}) is True


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

    status, diagnostics, digest, spans = read_runner_artifacts(tmp_path)
    assert not (tmp_path / "job-test" / ("agent_execution" + ".log")).exists()
    assert status["status"] == "STOPPED_EARLY"
    assert status["stop_reason"] == "fred_mcp_required: FRED MCP probe failed"
    assert diagnostics["status"] == "STOPPED_EARLY"
    assert diagnostics["error_spans"][0]["message"] == "fred_mcp_required: FRED MCP probe failed"
    assert "Primary trace signal: stream error" in digest
    assert "stream_error" in span_event_types(spans)


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

    status, diagnostics, digest, spans = read_runner_artifacts(tmp_path)
    assert status["status"] == "SETUP_FAILED"
    assert status["stop_reason"].startswith("fred_mcp_required: FRED MCP probe failed")
    assert diagnostics["status"] == "SETUP_FAILED"
    assert diagnostics["primary_trace_signal"] == "setup failure"
    assert "Primary trace signal: setup failure" in digest
    assert "stream_error" in span_event_types(spans)


def test_runner_marks_exhausted_latest_qa_rejection_as_terminal_failure(
    monkeypatch,
    tmp_path,
):
    rejected = {
        "status": "rejected",
        "report_path": str(tmp_path / "job-test" / "report.json"),
        "reason": "Report contradicts execution_summary signal-framework results.",
        "required_fixes": ["Rewrite the report from execution_summary.json."],
    }

    async def fake_stream_research(**_kwargs):
        for _ in range(3):
            yield {
                "type": "messages",
                "data": (ToolMessage(json.dumps(rejected)), {"langgraph_node": "tools"}),
            }
        yield {
            "type": "messages",
            "data": (
                FakeMessage("Report approved: outputs/job-test/report.json"),
                {"langgraph_node": "model"},
            ),
        }
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

    status, diagnostics, digest, spans = read_runner_artifacts(tmp_path)
    assert status["status"] == "QA_REJECTED"
    assert "QA repair budget exhausted after latest rejected decision" in status[
        "stop_reason"
    ]
    assert diagnostics["status"] == "QA_REJECTED"
    assert diagnostics["primary_trace_signal"] == "qa rejection terminal failure"
    assert "Primary trace signal: qa rejection terminal failure" in digest
    assert "qa_terminal_failure" in span_event_types(spans)


def test_runner_logs_traceback_for_empty_message_fatal_exception(monkeypatch, tmp_path):
    async def fake_stream_research(**_kwargs):
        raise AssertionError()
        yield  # pragma: no cover

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

    status, diagnostics, digest, spans = read_runner_artifacts(tmp_path)
    assert status["status"] == "FATAL_ERROR"
    assert status["stop_reason"] == "ERROR: AssertionError: AssertionError()"
    assert "raise AssertionError()" in status["traceback"]
    assert diagnostics["primary_trace_signal"] == "fatal runner error"
    assert "Primary trace signal: fatal runner error" in digest
    assert "fatal_error" in span_event_types(spans)


def test_format_fatal_exception_uses_exception_type_for_empty_message():
    reason, traceback_text = format_fatal_exception(AssertionError())

    assert reason == "ERROR: AssertionError: AssertionError()"
    assert "AssertionError" in traceback_text


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

    status, diagnostics, _digest, spans = read_runner_artifacts(tmp_path)
    assert len(calls) == 2
    assert calls[0]["messages"] is None
    assert calls[1]["messages"][0]["metadata"]["action"] == "commence_research"
    assert status["status"] == "COMPLETED"
    assert diagnostics["status"] == "COMPLETED"
    assert "approval_auto_resume" in span_event_types(spans)


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

    status, diagnostics, _digest, spans = read_runner_artifacts(tmp_path)
    assert len(calls) == 2
    assert calls[0]["messages"] is None
    assert calls[1]["messages"][0]["metadata"]["action"] == "commence_research"
    assert status["status"] == "COMPLETED"
    assert diagnostics["status"] == "COMPLETED"
    assert "forced_execution" in span_event_types(spans)


def test_runner_counts_streamed_text_chunks_as_one_message(monkeypatch, tmp_path):
    async def fake_stream_research(**_kwargs):
        yield {
            "type": "messages",
            "data": (FakeMessage("Hel"), {"langgraph_node": "model"}),
        }
        yield {
            "type": "messages",
            "data": (FakeMessage("lo"), {"langgraph_node": "model"}),
        }
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
        max_model_messages=1,
    )

    asyncio.run(run_research_loop("query", "job-test", watchdog))

    status, diagnostics, _digest, spans = read_runner_artifacts(tmp_path)
    message_spans = [
        span
        for span in spans
        if (span.get("attributes") or {}).get("event_type") == "model_message"
    ]
    assert status["status"] == "COMPLETED"
    assert message_spans[0]["attributes"]["message.text"] == "Hello"
    assert diagnostics["model_message_count"] == 1
    assert diagnostics["stop_reason"] is None
    assert watchdog.model_messages == 1


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


@pytest.mark.asyncio
async def test_stream_research_retries_transient_provider_read_error(monkeypatch):
    class FlakyAgent:
        def __init__(self):
            self.inputs = []

        async def astream(self, graph_input, **_kwargs):
            self.inputs.append(graph_input)
            if len(self.inputs) == 1:
                raise httpx.ReadError("")
            yield {"type": "updates", "data": {"execute": {"phase": "executing"}}}

    agent = FlakyAgent()

    async def fake_resolve_graph_input(*_args, **_kwargs):
        return {"messages": [{"role": "user", "content": "query"}]}

    monkeypatch.setattr(
        orchestrator,
        "resolve_graph_input",
        fake_resolve_graph_input,
    )

    async def no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    events = [
        event
        async for event in orchestrator.stream_research(
            query="query",
            job_id="job-test",
            agent=agent,
        )
    ]

    assert events == [{"type": "updates", "data": {"execute": {"phase": "executing"}}}]
    assert len(agent.inputs) == 2
    assert agent.inputs[0] == {"messages": [{"role": "user", "content": "query"}]}
    assert agent.inputs[1] is None
