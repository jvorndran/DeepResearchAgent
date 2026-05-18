import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.runner import Watchdog
from tests.runner import discover_artifacts
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


def test_runner_artifact_discovery_prefers_generated_script_path(tmp_path):
    output_dir = tmp_path / "job-test"
    code_dir = output_dir / "code"
    code_dir.mkdir(parents=True)
    generated_script = code_dir / "analysis_v2.py"
    generated_script.write_text("# fallback generator\n", encoding="utf-8")
    (code_dir / "analysis.py").write_text("# stale generator\n", encoding="utf-8")
    (output_dir / "report.json").write_text("{}", encoding="utf-8")
    (output_dir / "charts.json").write_text("{}", encoding="utf-8")
    (output_dir / "execution_summary.json").write_text(
        json.dumps({"generated_by": {"script_path": str(generated_script)}}),
        encoding="utf-8",
    )

    artifacts = discover_artifacts(output_dir)

    assert artifacts["analysis_py"] == str(generated_script)


def test_loop_prompts_and_skill_docs_use_trace_artifacts():
    removed_log_name = "agent_execution" + ".log"
    repo_root = Path(__file__).resolve().parents[2]
    paths = [
        repo_root / "scripts" / "codex_improve_loop.sh",
        repo_root / "scripts" / "improve_loop" / "prompts" / "analyze.md",
        repo_root / "scripts" / "improve_loop" / "prompts" / "plan.md",
        repo_root / "scripts" / "improve_loop" / "prompts" / "build.md",
        repo_root / "scripts" / "improve_loop" / "prompts" / "review.md",
        repo_root / "scripts" / "improve_loop" / "prompts" / "fix.md",
        repo_root / "scripts" / "codex_feature_loop.sh",
        repo_root / ".agents" / "skills" / "agent-improver" / "SKILL.md",
    ]

    for path in paths:
        text = path.read_text()
        assert removed_log_name not in text
        assert "trace-digest.md" in text


def test_improve_loop_uses_full_run_analysis_plan_build_review_fix_phases():
    repo_root = Path(__file__).resolve().parents[2]
    loop_text = (repo_root / "scripts" / "codex_improve_loop.sh").read_text()
    runner_text = (repo_root / "backend" / "tests" / "runner.py").read_text()
    skill_text = (
        repo_root / ".agents" / "skills" / "agent-improver" / "SKILL.md"
    ).read_text()

    assert "run_agent_phase" in loop_text
    assert "run_codex_phase analyze" in loop_text
    assert "run_codex_phase plan" in loop_text
    assert "run_codex_phase build" in loop_text
    assert "run_codex_phase review" in loop_text
    assert "run_codex_phase fix" in loop_text
    assert "MAX_FIX_ATTEMPTS" in loop_text
    assert "scripts/improve_loop/queries.txt" in loop_text
    assert "scripts/improve_loop/prompts" in loop_text
    assert "run-summary.md" in loop_text
    assert "current-diff.patch" in loop_text
    assert "memory.md" in loop_text
    assert "--no-watchdog-stop" not in loop_text
    assert "--no-watchdog-stop" not in runner_text
    assert "watchdog_stop" not in runner_text
    assert "watch ->" not in loop_text

    for required in (
        "RUN_RESULT",
        "RUN_TRACE_DIGEST",
        "IMPROVE_ANALYSIS_RESULT",
        "IMPROVE_PLAN_RESULT",
        "IMPROVE_TARGET",
        "IMPROVE_QUALITY_CRITERIA",
        "IMPROVER_RESULT",
        "IMPROVE_REVIEW_RESULT",
        "IMPROVE_FIX_RESULT",
        "IMPROVE_NEXT_SIGNAL",
    ):
        assert required in loop_text
        assert required in skill_text

    forbidden_prompts = (
        "modify the smallest part",
        "Apply surgical improvements only",
        "Patch only the smallest",
        "smallest necessary",
        "smallest responsible",
    )
    for forbidden in forbidden_prompts:
        assert forbidden not in loop_text
        assert forbidden not in skill_text


def test_improve_loop_dry_run_creates_artifacts_and_exercises_fix_review(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    log_root = tmp_path / "improve-loop"
    env = os.environ.copy()
    env.update(
        {
            "LOG_ROOT": str(log_root),
            "RUN_ID": "pytest-dry-run",
            "DRY_RUN_REVIEW_SEQUENCE": "changes_requested,approved",
        }
    )
    env.pop("LOOP_MODE", None)
    env.pop("LOOP_FOCUS", None)

    result = subprocess.run(
        [str(repo_root / "scripts" / "codex_improve_loop.sh"), "--dry-run", "1"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "Pass 1 final review result: approved" in result.stdout
    pass_dir = log_root / "runs" / "pytest-dry-run" / "pass-1"
    expected = [
        "query.txt",
        "run.log",
        "run-summary.md",
        "analysis-prompt.md",
        "analysis-summary.md",
        "plan-prompt.md",
        "plan-summary.md",
        "build-prompt.md",
        "build-summary.md",
        "review-1-prompt.md",
        "review-1-summary.md",
        "fix-1-prompt.md",
        "fix-1-summary.md",
        "review-2-prompt.md",
        "review-2-summary.md",
        "current-diff.patch",
        "current-status.txt",
        "test-evidence.md",
        "summary.md",
    ]
    for name in expected:
        assert (pass_dir / name).exists(), name

    run_summary = (pass_dir / "run-summary.md").read_text()
    assert "RUN_RESULT: completed" in run_summary
    assert "RUN_TRACE_DIGEST:" in run_summary
    assert "Runner stop policy: full agent run" in run_summary
    assert (pass_dir / "run-artifacts" / "trace-digest.md").exists()
    assert (pass_dir / "run-artifacts" / "trace_diagnostics.json").exists()
    assert (pass_dir / "run-artifacts" / "runner_status.json").exists()

    assert "IMPROVE_REVIEW_RESULT: changes_requested" in (
        pass_dir / "review-1-summary.md"
    ).read_text()
    assert "IMPROVE_PLAN_RESULT: planned" in (pass_dir / "plan-summary.md").read_text()
    assert "IMPROVE_FIX_RESULT: patched" in (pass_dir / "fix-1-summary.md").read_text()
    assert "IMPROVE_REVIEW_RESULT: approved" in (
        pass_dir / "review-2-summary.md"
    ).read_text()

    memory = (log_root / "memory.md").read_text()
    assert "## Active Recurring Failure Signals" in memory
    assert "## Last 10 Approved Targets / Files / Tests" in memory
    assert "dry-run-target" in memory
    assert len(memory.splitlines()) <= 50

    analysis_prompt = (pass_dir / "analysis-prompt.md").read_text()
    assert f"Memory path: {log_root / 'memory.md'}" in analysis_prompt
    assert "`run-summary.md`" in analysis_prompt
    assert "## Quality Criteria" in analysis_prompt
    assert "Answer fit" in analysis_prompt
    assert "Chart usefulness" in analysis_prompt
    assert "Trace digest:" not in analysis_prompt
    assert "Trace diagnostics:" not in analysis_prompt
    assert "Report JSON:" not in analysis_prompt

    plan_prompt = (pass_dir / "plan-prompt.md").read_text()
    assert "`analysis-summary.md`" in plan_prompt
    assert "Planning checklist" in plan_prompt
    assert "decision record" in plan_prompt

    build_prompt = (pass_dir / "build-prompt.md").read_text()
    assert "`plan-summary.md`" in build_prompt
    assert "`analysis-summary.md`" in build_prompt
    assert "RUN_TRACE_DIGEST:" not in build_prompt


def test_improve_loop_rejects_removed_loop_mode_and_focus(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["LOG_ROOT"] = str(tmp_path / "improve-loop")
    env["RUN_ID"] = "pytest-loop-mode"
    env["LOOP_MODE"] = "refactor"

    result = subprocess.run(
        [str(repo_root / "scripts" / "codex_improve_loop.sh"), "--dry-run", "1"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 2
    assert "no longer supports LOOP_MODE or LOOP_FOCUS" in result.stderr
    assert "scripts/codex_refactor_loop.sh" in result.stderr


def test_improve_loop_prompts_and_skill_docs_stay_small_and_unembedded():
    repo_root = Path(__file__).resolve().parents[2]
    skill_text = (
        repo_root / ".agents" / "skills" / "agent-improver" / "SKILL.md"
    ).read_text()
    loop_text = (repo_root / "scripts" / "codex_improve_loop.sh").read_text()

    prompt_dir = repo_root / "scripts" / "improve_loop" / "prompts"
    for prompt_path in prompt_dir.glob("*.md"):
        text = prompt_path.read_text()
        line_limit = 45 if prompt_path.name == "analyze.md" else 25
        assert len(text.splitlines()) <= line_limit
        assert len(text) <= 2500

    assert len(skill_text.splitlines()) <= 140
    analyze_text = (prompt_dir / "analyze.md").read_text()
    assert "Answer fit" in analyze_text
    assert "Chart usefulness" in analyze_text
    assert "Artifact integrity" in analyze_text
    assert "Analysis Workflow" in analyze_text
    assert "Read the report as the user" in analyze_text
    assert "Compare two or three candidate" in analyze_text
    assert "agent-engineering failure class" in analyze_text
    assert "skill vs prompt placement" in analyze_text
    assert "tool/schema affordance" in analyze_text
    assert "tech-debt risk" in analyze_text
    assert "broadest reusable agent-quality lift" in analyze_text
    assert "general failure class" in analyze_text
    assert "code quality risks" in analyze_text
    assert "Analysis Summary Shape" in analyze_text
    assert "Prefer holistic fixes" in skill_text
    assert "Code quality is a phase gate" in skill_text
    plan_text = (prompt_dir / "plan.md").read_text()
    assert "Planning checklist" in plan_text
    assert "agent-engineering lens" in plan_text
    assert "simple/composable" in plan_text
    assert "tool for high-impact data/action" in plan_text
    assert "typed inputs" in plan_text
    assert "compact outputs" in plan_text
    assert "actionable errors" in plan_text
    assert "skill for reusable on-demand" in plan_text
    assert "edit prompts only for concise roles" in plan_text
    assert "sequence, boundaries, or edge cases" in plan_text
    assert "handoff changes" in plan_text
    assert "tests/evals to run" in plan_text
    assert "decision record" in plan_text
    assert "IMPROVE_PLAN_RESULT" in plan_text
    assert "no edits" in plan_text.lower()
    for prompt_name in ("plan.md", "build.md", "review.md", "fix.md"):
        prompt_text = (prompt_dir / prompt_name).read_text()
        assert "Holistic improvement gate" in prompt_text
        assert "Code quality gate" in prompt_text

    forbidden_skill_text = (
        "Example Query Bank",
        "Refactor Mode",
        "Free integration rules",
        "Free integration expansion",
        "Chart-mode priority",
        "Playwright CLI diagnostic guidance",
        "LOOP_FOCUS",
        "LOOP_MODE",
        "watch-summary.md",
        "WATCH_RESULT",
        "report_quality_criteria.md",
    )
    for forbidden in forbidden_skill_text:
        assert forbidden not in skill_text

    forbidden_loop_text = (
        "COMBINED_QUERIES",
        "CHART_QUERIES",
        "write_refactor_signal_prompt_file",
        "write_refactor_build_prompt_file",
        "refactor-signal",
        "Chart-mode priority",
        "Playwright CLI diagnostic guidance",
        "Example Query Bank",
        "watch-summary.md",
        "WATCH_RESULT",
        "watch ->",
    )
    for forbidden in forbidden_loop_text:
        assert forbidden not in loop_text


def test_improve_loop_queries_are_realistic_and_varied():
    repo_root = Path(__file__).resolve().parents[2]
    query_file = repo_root / "scripts" / "improve_loop" / "queries.txt"
    queries = [
        line.strip()
        for line in query_file.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]

    assert len(queries) >= 12
    assert max(len(query) for query in queries) <= 260
    assert sum("?" in query for query in queries) >= 8
    assert sum("FRED" in query for query in queries) <= 1
    assert sum("investment committee" in query.lower() for query in queries) <= 1

    combined = "\n".join(queries).lower()
    for theme in (
        "recession",
        "consumer",
        "jobs",
        "inflation",
        "nvidia",
        "apple",
        "regions",
        "dashboard",
        "watch",
    ):
        assert theme in combined
