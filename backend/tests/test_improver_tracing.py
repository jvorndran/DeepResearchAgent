import asyncio
import json
from pathlib import Path

import pytest

from tests.runner import Watchdog
from tests.runner import run_research_loop


class FakeMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


def read_json(path: Path):
    return json.loads(path.read_text())


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def local_runner_tracing(monkeypatch):
    monkeypatch.setenv("RUNNER_TRACE_EXPORT_MODE", "local")
    monkeypatch.delenv("RUNNER_REQUIRE_PHOENIX", raising=False)


def test_runner_writes_trace_artifacts_without_text_log(monkeypatch, tmp_path):
    async def fake_stream_research(**_kwargs):
        yield {
            "type": "messages",
            "data": (
                FakeMessage(
                    tool_calls=[
                        {"name": "fred_get_series", "args": {"series_id": "GDP"}},
                        {"name": "fred_get_series", "args": {"series_id": "GDP"}},
                    ]
                ),
                {"langgraph_node": "data_engineer"},
            ),
        }
        yield {
            "type": "messages",
            "data": (FakeMessage("Done"), {"langgraph_node": "technical_writer"}),
        }
        yield {"type": "updates", "data": {"execute": {"messages": []}}}

    monkeypatch.setattr("tests.runner.stream_research", fake_stream_research)
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))

    watchdog = Watchdog(
        max_runtime_seconds=900,
        max_tool_calls=60,
        max_identical_tool_calls=25,
        max_fred_search_calls=10,
        max_model_messages=80,
    )

    asyncio.run(run_research_loop("query", "job-test", watchdog))

    job_dir = tmp_path / "job-test"
    spans_path = job_dir / "phoenix_spans.jsonl"
    diagnostics_path = job_dir / "trace_diagnostics.json"
    digest_path = job_dir / "trace-digest.md"
    status_path = job_dir / "runner_status.json"

    assert spans_path.exists()
    assert diagnostics_path.exists()
    assert digest_path.exists()
    assert status_path.exists()
    assert not (job_dir / ("agent_execution" + ".log")).exists()

    spans = read_jsonl(spans_path)
    diagnostics = read_json(diagnostics_path)
    status = read_json(status_path)
    digest = digest_path.read_text()

    assert status["status"] == "COMPLETED"
    assert status["trace_artifacts"]["trace_digest_md"] == str(digest_path)
    assert diagnostics["span_count"] == len(spans)
    assert diagnostics["tool_counts"] == {"fred_get_series": 2}
    assert diagnostics["model_message_count"] == 1
    assert diagnostics["repeated_tool_signatures"] == [
        {"count": 2, "signature": 'fred_get_series:{"series_id":"GDP"}'}
    ]
    assert "Primary trace signal: repeated tool loop" in digest
    assert "1. trace-digest.md" in digest
    assert "2. trace_diagnostics.json" in digest
    assert "3. phoenix_spans.jsonl" in digest


def test_loop_prompts_and_skill_docs_use_trace_artifacts():
    removed_log_name = "agent_execution" + ".log"
    repo_root = Path(__file__).resolve().parents[2]
    paths = [
        repo_root / "scripts" / "codex_improve_loop.sh",
        repo_root / "scripts" / "codex_feature_loop.sh",
        repo_root / ".agents" / "skills" / "agent-improver" / "SKILL.md",
    ]

    for path in paths:
        text = path.read_text()
        assert removed_log_name not in text
        assert "trace-digest.md" in text


def test_improve_loop_uses_plan_build_phases_and_best_fix_policy():
    repo_root = Path(__file__).resolve().parents[2]
    loop_text = (repo_root / "scripts" / "codex_improve_loop.sh").read_text()
    skill_text = (
        repo_root / ".agents" / "skills" / "agent-improver" / "SKILL.md"
    ).read_text()
    combined = loop_text + "\n" + skill_text

    assert "write_improve_plan_prompt_file" in loop_text
    assert "write_improve_build_prompt_file" in loop_text
    assert 'run_codex_phase "improve-plan pass $i"' in loop_text
    assert 'run_codex_phase "improve-build pass $i"' in loop_text
    assert "This phase must not modify code" in loop_text
    assert "Improve Plan Summary" in loop_text
    assert "Improve Build Summary" in loop_text

    assert "Do not optimize for minimal diff size" in combined
    assert "best root-cause fix" in combined
    assert "broad phrase-matching tables" in combined
    assert "structured contracts over prose inference" in combined
    assert "workaround smells" in combined
    assert "`improve-plan` owns exactly one agent test" in skill_text
    assert "`improve-build` owns one coherent root-cause" in skill_text

    forbidden_prompts = (
        "modify the smallest part",
        "Apply surgical improvements only",
        "Patch only the smallest",
        "smallest necessary",
        "smallest responsible",
    )
    for forbidden in forbidden_prompts:
        assert forbidden not in combined
