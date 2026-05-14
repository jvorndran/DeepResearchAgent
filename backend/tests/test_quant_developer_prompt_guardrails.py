import json
from pathlib import Path
from types import SimpleNamespace

from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

import agents.quantitative_developer as quant_dev
import agents.quantitative_developer.middleware as quant_middleware
from agents.quantitative_developer import (
    QUANT_DEVELOPER_SUBAGENT,
    QUANT_DEVELOPER_SYSTEM_PROMPT,
    QuantDeveloperToolBoundaryMiddleware,
)
from agents.quantitative_developer.handoff import _has_successful_quant_handoff

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_QUANT_SKILL_DIR = _BACKEND_ROOT / "skills" / "quant-developer"
_QUANT_NATIVE_SKILLS = (
    "quant-script-workflow",
    "quant-sandbox-environment",
    "quant-macro-helper-workflows",
    "quant-chart-generation",
    "quant-code-execution-errors",
)


def _quant_skill_text(*names: str) -> str:
    files = names or tuple(f"{name}/SKILL.md" for name in _QUANT_NATIVE_SKILLS)
    parts = []
    for name in files:
        path = _QUANT_SKILL_DIR / name
        if path.is_dir():
            path = path / "SKILL.md"
        parts.append(path.read_text(encoding="utf-8"))
    text = "\n".join(parts)
    return " ".join(text.split())


def _native_skill_text(name: str) -> str:
    return (_QUANT_SKILL_DIR / name / "SKILL.md").read_text(encoding="utf-8")


class _Request:
    def __init__(self, tools, messages=None, runtime=None):
        self.tools = tools
        self.messages = messages or []
        self.runtime = runtime

    def override(self, **kwargs):
        return _Request(
            kwargs.get("tools", self.tools),
            messages=kwargs.get("messages", self.messages),
            runtime=kwargs.get("runtime", self.runtime),
        )


class _DroppingOverrideRequest(_Request):
    def override(self, **kwargs):
        return _Request(
            kwargs.get("tools", self.tools),
            messages=[],
            runtime=kwargs.get("runtime", self.runtime),
        )


def test_quant_prompt_is_compact_skill_router():
    assert len(QUANT_DEVELOPER_SYSTEM_PROMPT) < 3_200
    assert "Native skill router" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "build_recession_dashboard_artifacts" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "build_consumer_stress_dashboard_artifacts" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "build_historical_replay_chart_pack_artifacts" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "build_unemployment_forecast_chart_pack_artifacts" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "build_macro_cycle_chart_pack_artifacts" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "quant-script-workflow" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "quant-sandbox-environment" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "quant-macro-helper-workflows" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "quant-chart-generation" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "quant-code-execution-errors" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Always read `quant-chart-generation` when the task asks for charts" in (
        QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "Assistant message content must be empty whenever you call tools" in (
        QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "never emit literal DSML/XML tool tags" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "statistical_summary_excerpt" in QUANT_DEVELOPER_SYSTEM_PROMPT

    migrated_details = [
        "SCRIPT BUDGET & RECOVERY",
        "For broad macro + equity + regional + international prompts",
        "direct_ols_forecast(data, target_col",
        "Every pie chart MUST include",
        "Pairwise correlation safety",
        "supportive but not consistent/guaranteed",
        "Only inspect `charts.json`",
    ]
    for detail in migrated_details:
        assert detail not in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_skills_are_native_deepagents_shape():
    expected = set(_QUANT_NATIVE_SKILLS)
    actual = {path.parent.name for path in _QUANT_SKILL_DIR.glob("*/SKILL.md")}

    assert actual == expected
    for name in expected:
        skill = _native_skill_text(name)
        assert f"name: {name}" in skill
        assert "description:" in skill


def test_quant_native_skill_metadata_stays_compact():
    metadata_text = "\n".join(
        _native_skill_text(name).split("---", 2)[1] for name in _QUANT_NATIVE_SKILLS
    )

    for detail in [
        "direct_ols_forecast(data, target_col",
        "Every pie chart MUST include",
        "Pairwise correlation safety",
        "SCRIPT BUDGET & RECOVERY",
        "pd.read_csv(path, usecols",
    ]:
        assert detail not in metadata_text


def test_quant_native_subskills_keep_details_focused():
    script_skill = _native_skill_text("quant-script-workflow")
    macro_skill = _native_skill_text("quant-macro-helper-workflows")
    chart_skill = _native_skill_text("quant-chart-generation")
    error_skill = _native_skill_text("quant-code-execution-errors")

    assert "For broad macro + equity + regional + international prompts" in script_skill
    assert 'execution_summary["source_context_files"]' in script_skill
    assert "classify_recession_regime(scored_frame" in macro_skill
    assert 'recession_col="USREC"' in macro_skill
    assert "Pairwise correlation safety" in macro_skill
    assert "Every pie chart MUST include" in chart_skill
    assert "Pandas scalar date safety" in error_skill

    assert "Every pie chart MUST include" not in macro_skill
    assert "direct_ols_forecast(data, target_col" not in chart_skill
    assert "target under 120 lines" not in error_skill


def test_quant_chart_skill_requires_unique_axis_labels():
    chart_skill = _native_skill_text("quant-chart-generation")

    assert "Every axis chart must have at most one data row per" in chart_skill
    assert "assert the final chart frame has no duplicate labels" in chart_skill
    assert "Use a right axis only when series have materially different" in chart_skill
    assert "share the left axis so the chart does not imply a false divergence" in chart_skill
    assert "create a rich pack of 6-8" in chart_skill
    assert "distinct renderable charts" in chart_skill
    assert "ask whether each chart makes the report" in chart_skill
    assert "more insightful than a table or sentence" in chart_skill
    assert "Do not return an empty chart map for a chart" in chart_skill


def test_quant_skill_contains_migrated_script_budget_and_workflows():
    skill_text = _quant_skill_text()
    for detail in [
        "SCRIPT BUDGET & RECOVERY",
        "target under 120 lines",
        "For broad macro + equity + regional + international prompts",
        "keep the first draft FRED/helper-centered",
        "compact summary rows in",
        'execution_summary["source_context_files"]',
        "one `load_series(key)` helper",
        "no deep joins",
        "no narrative-only placeholders",
        "summarize_sec_company_facts(path)",
        "impossible margins",
        "final compact rewrite opportunity",
        "no nested f-string dict literals",
        "do not delete/rewrite with shell",
        "analysis_v2.py",
        "A successful script stdout that includes",
        "Do not edit a successful script merely to make a conclusion field more positive",
        "supportive but not consistent/guaranteed",
        "validate_scenario_table",
        "Do not pass dataframe/forecast arguments",
        "`historical_scenario_replay(...)`",
        "signal_framework_backtest",
        "do not defer those keys to a second enrichment script",
        "analog fast path",
        "save_quant_outputs",
        "Never import `agents.quant_utils`",
        "Execute the script with the default sandbox timeout",
        "FMP remains disabled and unavailable",
    ]:
        assert detail in skill_text


def test_quant_subagent_registers_tool_boundary_middleware():
    assert any(
        isinstance(item, QuantDeveloperToolBoundaryMiddleware)
        for item in QUANT_DEVELOPER_SUBAGENT["middleware"]
    )
    assert [tool.name for tool in QUANT_DEVELOPER_SUBAGENT["tools"]] == [
        "build_recession_dashboard_artifacts",
        "build_inflation_policy_chart_pack_artifacts",
        "build_consumer_stress_dashboard_artifacts",
        "build_historical_replay_chart_pack_artifacts",
        "build_unemployment_forecast_chart_pack_artifacts",
        "build_macro_cycle_chart_pack_artifacts",
    ]


def test_quant_middleware_exposes_skill_load_and_write_file_before_script_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = _Request(
        [
            SimpleNamespace(name="load_skill"),
            SimpleNamespace(name="build_recession_dashboard_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="execute"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="edit_file"),
            SimpleNamespace(name="ls"),
            SimpleNamespace(name="glob"),
            SimpleNamespace(name="grep"),
        ],
        messages=[AIMessage(content="need to inspect files")],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "load_skill",
        "build_recession_dashboard_artifacts",
        "write_file",
        "read_file",
    ]


def test_quant_middleware_forces_matching_recession_dashboard_tool_before_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "T10Y3M": "/tmp/T10Y3M.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "INDPRO": "/tmp/INDPRO.csv",
        "USREC": "/tmp/USREC.csv",
        "DRALACBN": "/tmp/DRALACBN.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="load_skill"),
            SimpleNamespace(name="build_recession_dashboard_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="execute"),
        ],
        messages=[
            SystemMessage(content=QUANT_DEVELOPER_SYSTEM_PROMPT),
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Create a "
                    "recession-dashboard report with 6-8 charts.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "load_skill",
        "build_recession_dashboard_artifacts",
        "read_file",
    ]


def test_quant_middleware_forces_matching_gdp_recession_cycle_tool_before_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "GDPC1": "/tmp/GDPC1.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "INDPRO": "/tmp/INDPRO.csv",
        "USREC": "/tmp/USREC.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="load_skill"),
            SimpleNamespace(name="build_recession_dashboard_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="execute"),
        ],
        messages=[
            SystemMessage(content=QUANT_DEVELOPER_SYSTEM_PROMPT),
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Compare real GDP "
                    "growth, unemployment, recession periods, and industrial production. "
                    "Produce 6-8 governed renderable charts.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "load_skill",
        "build_recession_dashboard_artifacts",
        "read_file",
    ]


def test_quant_middleware_forces_matching_consumer_stress_tool_before_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "PSAVERT": "/tmp/PSAVERT.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "AHETPI": "/tmp/AHETPI.csv",
        "UMCSENT": "/tmp/UMCSENT.csv",
        "DPCERA3M086SBEA": "/tmp/DPCERA3M086SBEA.csv",
        "TOTALSL": "/tmp/TOTALSL.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="load_skill"),
            SimpleNamespace(name="build_consumer_stress_dashboard_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="execute"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Analyze "
                    "consumer stress with a 6-8 chart dashboard.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "load_skill",
        "build_consumer_stress_dashboard_artifacts",
        "read_file",
    ]


def test_quant_middleware_routes_consumer_stress_despite_recession_skill_text():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "PSAVERT": "/tmp/PSAVERT.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "AHETPI": "/tmp/AHETPI.csv",
        "UMCSENT": "/tmp/UMCSENT.csv",
        "PCE": "/tmp/PCE.csv",
        "TOTALSL": "/tmp/TOTALSL.csv",
        "T10Y3M": "/tmp/stale_T10Y3M.csv",
        "INDPRO": "/tmp/stale_INDPRO.csv",
        "USREC": "/tmp/stale_USREC.csv",
    }
    query = (
        "Analyze whether the US consumer is under stress using FRED macro data. "
        "Build a 6-8 chart dashboard with savings, wages, unemployment, "
        "inflation, sentiment, consumption, and credit stress."
    )
    request = _Request(
        [
            SimpleNamespace(name="build_recession_dashboard_artifacts"),
            SimpleNamespace(name="build_consumer_stress_dashboard_artifacts"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="write_file"),
        ],
        messages=[
            SystemMessage(content=QUANT_DEVELOPER_SYSTEM_PROMPT),
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    f"Full approved user request for `original_query`: {query}\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            ),
            ToolMessage(
                content=(
                    "---\nname: quant-macro-helper-workflows\n---\n"
                    "Use build_recession_dashboard_artifacts for recession charts."
                ),
                tool_call_id="call-read-skill",
            ),
        ],
        runtime=SimpleNamespace(context={"job_id": "improver-loop"}),
    )
    handler_called = False

    def handler(req):
        nonlocal handler_called
        handler_called = True
        return ModelResponse(result=[AIMessage(content="I will inspect files first.")])

    response = middleware.wrap_model_call(request, handler)

    assert handler_called is False
    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_consumer_stress_dashboard_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    assert tool_call["args"]["data_files"] == data_files
    assert "consumer is under stress" in tool_call["args"]["query"]


def test_quant_middleware_forces_consumer_stress_tool_with_fred_substitutes():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "PSAVERT": "/tmp/PSAVERT.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "CES0500000003": "/tmp/CES0500000003.csv",
        "DSPIC96": "/tmp/DSPIC96.csv",
        "UMCSENT": "/tmp/UMCSENT.csv",
        "PCEC96": "/tmp/PCEC96.csv",
        "DRCCLACBS": "/tmp/DRCCLACBS.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="load_skill"),
            SimpleNamespace(name="build_consumer_stress_dashboard_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="execute"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Analyze "
                    "whether the US consumer is under stress with a chart dashboard.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "load_skill",
        "build_consumer_stress_dashboard_artifacts",
        "read_file",
    ]


def test_quant_middleware_forces_consumer_stress_tool_without_consumption_file():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "PSAVERT": "/tmp/PSAVERT.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "DSPIC96": "/tmp/DSPIC96.csv",
        "UMCSENT": "/tmp/UMCSENT.csv",
        "TOTALSL": "/tmp/TOTALSL.csv",
        "PCEPILFE": "/tmp/PCEPILFE.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="load_skill"),
            SimpleNamespace(name="build_consumer_stress_dashboard_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="execute"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Analyze "
                    "whether the US consumer is under stress using FRED macro "
                    "data. Build a 6-8 chart dashboard with sentiment or "
                    "consumption where available.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "load_skill",
        "build_consumer_stress_dashboard_artifacts",
        "read_file",
    ]


def test_quant_middleware_forces_matching_inflation_policy_tool_before_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "CPILFESL": "/tmp/CPILFESL.csv",
        "FEDFUNDS": "/tmp/FEDFUNDS.csv",
        "USREC": "/tmp/USREC.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="load_skill"),
            SimpleNamespace(name="build_inflation_policy_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="execute"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Build a "
                    "chart-heavy macro report comparing headline CPI inflation, "
                    "core CPI inflation, and the effective federal funds rate.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "load_skill",
        "build_inflation_policy_chart_pack_artifacts",
        "read_file",
    ]


def test_quant_middleware_recognizes_line_numbered_skill_reads_for_inflation_helper():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "CPILFESL": "/tmp/CPILFESL.csv",
        "FEDFUNDS": "/tmp/FEDFUNDS.csv",
        "USREC": "/tmp/USREC.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="build_inflation_policy_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Research Query: Build a chart-heavy macro report comparing "
                    "headline CPI inflation, core CPI inflation, and the effective "
                    "federal funds rate since 1990. Produce 6-8 governed charts.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            ),
            ToolMessage(
                content=(
                    "1\t---\n"
                    "2\tname: quant-macro-helper-workflows\n"
                    "3\tdescription: Deterministic macro helper routes.\n"
                    "4\t---\n"
                ),
                name="read_file",
                tool_call_id="call-skill-read",
            ),
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_inflation_policy_chart_pack_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    assert tool_call["args"]["data_files"] == data_files
    assert "headline CPI inflation" in tool_call["args"]["query"]


def test_quant_middleware_routes_research_summary_to_inflation_helper_without_stale_paths():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "CPIAUCSL": "/tmp/current/CPIAUCSL.csv",
        "CPILFESL": "/tmp/current/CPILFESL.csv",
        "FEDFUNDS": "/tmp/current/FEDFUNDS.csv",
        "USREC": "/tmp/current/USREC.csv",
    }
    stale_path = "/tmp/stale/fred_get_series_CPIAUCSL_1111111111111111_abcdef.csv"
    request = _Request(
        [
            SimpleNamespace(name="build_inflation_policy_chart_pack_artifacts"),
            SimpleNamespace(name="build_macro_cycle_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="execute"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Research summary: Build a chart-heavy macro report comparing "
                    "headline CPI inflation, core CPI inflation, and the effective "
                    "federal funds rate since 1990. Produce 6-8 governed renderable "
                    "charts.\n"
                    f'"data_files": {json.dumps(data_files)}\n'
                    f"Earlier context mentioned this stale path: {stale_path}"
                )
            ),
            ToolMessage(
                content=_native_skill_text("quant-macro-helper-workflows"),
                name="read_file",
                tool_call_id="call-read-quant-macro-skill",
            ),
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_inflation_policy_chart_pack_artifacts"
    assert tool_call["args"]["data_files"] == data_files
    assert stale_path not in tool_call["args"]["data_files"].values()
    assert "effective federal funds rate" in tool_call["args"]["query"]


def test_quant_middleware_forces_matching_historical_replay_tool_before_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "UNRATE": "/tmp/UNRATE.csv",
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "FEDFUNDS": "/tmp/FEDFUNDS.csv",
        "INDPRO": "/tmp/INDPRO.csv",
        "USREC": "/tmp/USREC.csv",
        "ICSA": "/tmp/ICSA.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="load_skill"),
            SimpleNamespace(name="build_historical_replay_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="execute"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Make a "
                    "historical replay report with 6-8 governed charts.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "load_skill",
        "build_historical_replay_chart_pack_artifacts",
        "read_file",
    ]


def test_quant_middleware_recovers_named_historical_replay_helper_prose_with_autosaves():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    fred_paths = {
        key: f"/tmp/fred_get_series_{key}_1111111111111111_abcdef.csv"
        for key in ("UNRATE", "CPIAUCSL", "FEDFUNDS", "INDPRO", "USREC")
    }
    autosaved_text = "\n".join(
        json.dumps({"status": "auto_saved", "file_path": path}) for path in fred_paths.values()
    )
    request = _Request(
        [
            SimpleNamespace(name="build_historical_replay_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Make a "
                    "historical replay report with 6-8 governed charts.\n"
                    '"data_files": {"CES0000000001": '
                    '"/tmp/CES0000000001_bls_public.csv"}\n'
                    f"{autosaved_text}"
                )
            )
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        "Since this is a historical replay chart pack, I should use "
                        "`build_historical_replay_chart_pack_artifacts` now."
                    )
                )
            ]
        ),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_historical_replay_chart_pack_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    for key, path in fred_paths.items():
        assert tool_call["args"]["data_files"][key] == path
    assert tool_call["args"]["data_files"]["CES0000000001"] == "/tmp/CES0000000001_bls_public.csv"


def test_quant_skill_read_is_not_successful_artifact_handoff():
    message = ToolMessage(
        content=_native_skill_text("quant-script-workflow"),
        name="read_file",
        tool_call_id="call-read-quant-script-skill",
    )

    assert not _has_successful_quant_handoff([message])


def test_quant_middleware_forces_historical_replay_after_full_skill_read():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "UNRATE": "/tmp/UNRATE.csv",
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "FEDFUNDS": "/tmp/FEDFUNDS.csv",
        "INDPRO": "/tmp/INDPRO.csv",
        "USREC": "/tmp/USREC.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="build_historical_replay_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Research Query: Make a historical replay report comparing "
                    "current labor, inflation, rates, production, and consumer "
                    "stress. Produce 6-8 governed renderable charts.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            ),
            ToolMessage(
                content=_native_skill_text("quant-script-workflow"),
                name="read_file",
                tool_call_id="call-read-quant-script-skill",
            ),
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_historical_replay_chart_pack_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    assert tool_call["args"]["data_files"] == data_files


def test_quant_middleware_prioritizes_historical_replay_over_generic_recession_dashboard():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "UNRATE": "/tmp/UNRATE.csv",
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "FEDFUNDS": "/tmp/FEDFUNDS.csv",
        "INDPRO": "/tmp/INDPRO.csv",
        "USREC": "/tmp/USREC.csv",
        "GDPC1": "/tmp/GDPC1.csv",
        "TOTALSL": "/tmp/TOTALSL.csv",
        "PSAVERT": "/tmp/PSAVERT.csv",
        "UMCSENT": "/tmp/UMCSENT.csv",
        "AHETPI": "/tmp/AHETPI.csv",
    }
    query = (
        "Make a historical replay report comparing current labor, inflation, "
        "rates, production, and consumer-stress indicators with the 2001, "
        "2008, 2020, and post-pandemic cycle windows. Produce 6-8 governed "
        "renderable charts."
    )
    request = _Request(
        [
            SimpleNamespace(name="build_recession_dashboard_artifacts"),
            SimpleNamespace(name="build_inflation_policy_chart_pack_artifacts"),
            SimpleNamespace(name="build_consumer_stress_dashboard_artifacts"),
            SimpleNamespace(name="build_historical_replay_chart_pack_artifacts"),
            SimpleNamespace(name="build_macro_cycle_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    f"Research Query: {query}\n\n"
                    "The data includes USREC recession windows and consumer-stress "
                    "series, but the requested chart pack is a historical replay.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            ),
            ToolMessage(
                content=_native_skill_text("quant-script-workflow"),
                name="read_file",
                tool_call_id="call-read-quant-script-skill",
            ),
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_historical_replay_chart_pack_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    assert tool_call["args"]["data_files"] == data_files
    assert tool_call["args"]["query"] == query


def test_quant_middleware_forces_matching_macro_cycle_tool_before_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "FEDFUNDS": "/tmp/FEDFUNDS.csv",
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "DGS10": "/tmp/DGS10.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "PAYEMS": "/tmp/PAYEMS.csv",
        "INDPRO": "/tmp/INDPRO.csv",
        "GDPC1": "/tmp/GDPC1.csv",
        "PSAVERT": "/tmp/PSAVERT.csv",
        "UMCSENT": "/tmp/UMCSENT.csv",
        "USREC": "/tmp/USREC.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="load_skill"),
            SimpleNamespace(name="build_macro_cycle_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="execute"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Create a "
                    "macro cycle chart pack for an investment committee with "
                    "6-8 governed charts.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "load_skill",
        "build_macro_cycle_chart_pack_artifacts",
        "read_file",
    ]


def test_quant_middleware_routes_macro_cycle_with_curve_and_consumer_proxies():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "FEDFUNDS": "/tmp/FEDFUNDS.csv",
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "T10Y2Y": "/tmp/T10Y2Y.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "PAYEMS": "/tmp/PAYEMS.csv",
        "INDPRO": "/tmp/INDPRO.csv",
        "GDPC1": "/tmp/GDPC1.csv",
        "PSAVERT": "/tmp/PSAVERT.csv",
        "DSPIC96": "/tmp/DSPIC96.csv",
        "USREC": "/tmp/USREC.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="load_skill"),
            SimpleNamespace(name="build_recession_dashboard_artifacts"),
            SimpleNamespace(name="build_macro_cycle_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="execute"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Create a "
                    "macro cycle chart pack for an investment committee covering "
                    "rates/inflation, labor, output/production, consumer stress, "
                    "historical analogs, and a synthesis view. Produce 6-8 "
                    "governed renderable charts.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "load_skill",
        "build_macro_cycle_chart_pack_artifacts",
        "read_file",
    ]


def test_quant_middleware_forces_macro_regime_tool_without_saving_rate():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "FEDFUNDS": "/tmp/FEDFUNDS.csv",
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "DGS10": "/tmp/DGS10.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "PAYEMS": "/tmp/PAYEMS.csv",
        "INDPRO": "/tmp/INDPRO.csv",
        "GDPC1": "/tmp/GDPC1.csv",
        "UMCSENT": "/tmp/UMCSENT.csv",
        "USREC": "/tmp/USREC.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="load_skill"),
            SimpleNamespace(name="build_macro_cycle_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="execute"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Test whether "
                    "current macro conditions look like a soft landing, delayed "
                    "recession, or reacceleration. Produce 6-8 governed charts.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "load_skill",
        "build_macro_cycle_chart_pack_artifacts",
        "read_file",
    ]


def test_quant_middleware_keeps_macro_cycle_tool_available_before_match():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = _Request(
        [
            SimpleNamespace(name="load_skill"),
            SimpleNamespace(name="build_macro_cycle_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="execute"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Test whether "
                    "current macro conditions look like a soft landing, delayed "
                    "recession, or reacceleration. Produce 6-8 governed charts.\n"
                    '"data_files": {"FEDFUNDS": "/tmp/FEDFUNDS.csv"}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "load_skill",
        "build_macro_cycle_chart_pack_artifacts",
        "write_file",
        "read_file",
    ]


def test_quant_middleware_allows_macro_cycle_tool_before_script_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "build_macro_cycle_chart_pack_artifacts",
            "id": "call-macro-cycle",
            "args": {
                "job_id": "improver-loop",
                "data_files": {"FEDFUNDS": "/tmp/FEDFUNDS.csv"},
            },
        },
        state={"messages": [AIMessage(content="use deterministic macro helper")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content='{"chart_ids": ["macro_cycle_profile"]}',
            name="build_macro_cycle_chart_pack_artifacts",
            tool_call_id="call-macro-cycle",
        ),
    )

    assert response.status != "error"
    assert response.name == "build_macro_cycle_chart_pack_artifacts"


def test_quant_middleware_forces_matching_unemployment_forecast_tool_before_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "UNRATE_FRED": "/tmp/UNRATE.csv",
        "PAYEMS_FRED": "/tmp/PAYEMS.csv",
        "ICSA_FRED": "/tmp/ICSA.csv",
        "CPIAUCSL_FRED": "/tmp/CPIAUCSL.csv",
        "GDPC1_FRED": "/tmp/GDPC1.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="load_skill"),
            SimpleNamespace(name="build_unemployment_forecast_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="execute"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Build an "
                    "unemployment forecast-overlay report with 6-8 governed charts.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "load_skill",
        "build_unemployment_forecast_chart_pack_artifacts",
        "read_file",
    ]


def test_quant_middleware_forces_unemployment_forecast_tool_without_claims():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "UNRATE_FRED": "/tmp/UNRATE.csv",
        "PAYEMS_FRED": "/tmp/PAYEMS.csv",
        "U6RATE_FRED": "/tmp/U6RATE.csv",
        "DGS10_FRED": "/tmp/DGS10.csv",
        "FEDFUNDS_FRED": "/tmp/FEDFUNDS.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="build_unemployment_forecast_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="read_file"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Build an "
                    "unemployment forecast-overlay report with 6-8 governed charts.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "build_unemployment_forecast_chart_pack_artifacts",
        "read_file",
    ]


def test_quant_middleware_allows_skill_load_before_script_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={"name": "load_skill", "id": "call-skill", "args": {}},
        state={"messages": [AIMessage(content="need quant instructions")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Loaded skill quant-developer",
            name="load_skill",
            tool_call_id="call-skill",
        ),
    )

    assert response.status != "error"
    assert response.content == "Loaded skill quant-developer"


def test_quant_middleware_allows_native_skill_read_before_script_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    skill_path = _QUANT_SKILL_DIR / "quant-script-workflow" / "SKILL.md"
    request = SimpleNamespace(
        tool_call={
            "name": "read_file",
            "id": "call-read-skill",
            "args": {"file_path": str(skill_path)},
        },
        state={"messages": [AIMessage(content="need focused skill instructions")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Loaded quant-script-workflow",
            name="read_file",
            tool_call_id="call-read-skill",
        ),
    )

    assert response.status != "error"
    assert response.content == "Loaded quant-script-workflow"


def test_quant_middleware_blocks_non_skill_read_before_script_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "read_file",
            "id": "call-read-data",
            "args": {"file_path": "/tmp/data.csv"},
        },
        state={"messages": [AIMessage(content="try to inspect raw data")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "Blocked tool `read_file` for quant-developer" in response.content


def test_quant_middleware_allows_repair_tools_after_script_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = _Request(
        [
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="execute"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="edit_file"),
            SimpleNamespace(name="ls"),
            SimpleNamespace(name="glob"),
        ],
        messages=[
            ToolMessage(
                content="Updated file /tmp/outputs/job/code/analysis.py",
                name="write_file",
                tool_call_id="call-write",
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "write_file",
        "execute",
        "read_file",
        "edit_file",
    ]


def test_quant_middleware_allows_repair_tools_after_fallback_script_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = _Request(
        [
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="execute"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="edit_file"),
            SimpleNamespace(name="ls"),
            SimpleNamespace(name="glob"),
        ],
        messages=[
            ToolMessage(
                content="Updated file /tmp/outputs/job/code/analysis_v2.py",
                name="write_file",
                tool_call_id="call-write-v2",
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == [
        "write_file",
        "execute",
        "read_file",
        "edit_file",
    ]


def test_quant_middleware_does_not_treat_blocked_write_as_script_written():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = _Request(
        [
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="execute"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="edit_file"),
        ],
        messages=[
            ToolMessage(
                content=(
                    "Blocked oversized quant analysis script before writing. "
                    "Proposed script has 538 lines and 25594 characters."
                ),
                name="write_file",
                tool_call_id="call-blocked-write",
                status="error",
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == ["write_file", "read_file"]


def test_quant_middleware_allows_final_rewrite_after_three_prewrite_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", str(tmp_path))
    middleware = QuantDeveloperToolBoundaryMiddleware()
    messages = [
        AIMessage(content="Use outputs/improver-loop/code/analysis.py"),
        *[
            ToolMessage(
                content=(
                    "Blocked quant analysis script before writing because "
                    "Python syntax validation failed."
                ),
                name="write_file",
                tool_call_id=f"call-blocked-{idx}",
                status="error",
            )
            for idx in range(3)
        ],
    ]
    request = _Request([SimpleNamespace(name="write_file")], messages=messages)

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(result=[AIMessage(content="final compact rewrite")]),
    )

    assert response.result[0].content == "final compact rewrite"
    assert not (tmp_path / "improver-loop" / "execution_summary.json").exists()


def test_quant_middleware_allows_final_rewrite_tool_call_after_three_prewrite_blocks(
    tmp_path,
):
    middleware = QuantDeveloperToolBoundaryMiddleware()
    usrec_path = tmp_path / "fred_get_series_USREC.csv"
    usrec_path.write_text("date,value\n2024-01-01,0\n", encoding="utf-8")
    messages = [
        AIMessage(content="Use outputs/improver-loop/code/analysis.py"),
        *[
            ToolMessage(
                content=(
                    "Blocked quant analysis script before writing because "
                    "advisory helper guidance was not followed."
                ),
                name="write_file",
                tool_call_id=f"call-blocked-{idx}",
                status="error",
            )
            for idx in range(3)
        ],
    ]
    script = (
        f"DATA_FILES = {{'USREC': {str(usrec_path)!r}}}\n"
        "execution_summary = {'recession_risk': {'latest_index_value': 0.4}}\n"
    )
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-final-write",
            "args": {
                "file_path": "/tmp/outputs/improver-loop/code/analysis.py",
                "content": script,
            },
        },
        state={"messages": messages},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Updated file /tmp/outputs/improver-loop/code/analysis.py",
            name="write_file",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    assert response.status == "success"


def test_quant_middleware_returns_failure_handoff_after_repeated_prewrite_blocks(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", str(tmp_path))
    middleware = QuantDeveloperToolBoundaryMiddleware()
    messages = [
        AIMessage(content="Use outputs/improver-loop/code/analysis.py"),
        *[
            ToolMessage(
                content=(
                    "Blocked quant analysis script before writing because "
                    "Python syntax validation failed."
                ),
                name="write_file",
                tool_call_id=f"call-blocked-{idx}",
                status="error",
            )
            for idx in range(4)
        ],
    ]
    request = _Request([SimpleNamespace(name="write_file")], messages=messages)

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(result=[AIMessage(content="still retrying")]),
    )

    handoff = json.loads(response.result[0].content)
    assert handoff["status"] == "failed"
    assert handoff["chart_ids"] == []
    assert handoff["charts_json"] == str(tmp_path / "improver-loop" / "charts.json")
    assert handoff["execution_summary_json"] == str(
        tmp_path / "improver-loop" / "execution_summary.json"
    )
    summary = json.loads((tmp_path / "improver-loop" / "execution_summary.json").read_text())
    assert summary["blocked_attempt_count"] == 4
    assert summary["failure_stage"] == "quant_initial_script_write"


def test_quant_middleware_failure_handoff_uses_runtime_job_id_over_prompt_examples(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", str(tmp_path))
    middleware = QuantDeveloperToolBoundaryMiddleware()
    messages = [
        AIMessage(content="Example path only: /app/outputs/job_a61b3825/charts.json"),
        *[
            ToolMessage(
                content=(
                    "Blocked quant analysis script before writing because "
                    "Python syntax validation failed."
                ),
                name="write_file",
                tool_call_id=f"call-blocked-{idx}",
                status="error",
            )
            for idx in range(4)
        ],
    ]
    request = _Request([SimpleNamespace(name="write_file")], messages=messages)
    request.runtime = SimpleNamespace(context=SimpleNamespace(job_id="job_6299bc0b"))

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(result=[AIMessage(content="still retrying")]),
    )

    handoff = json.loads(response.result[0].content)
    output_dir = tmp_path / "job_6299bc0b"
    assert handoff["charts_json"] == str(output_dir / "charts.json")
    assert handoff["execution_summary_json"] == str(output_dir / "execution_summary.json")
    assert (output_dir / "execution_summary.json").is_file()
    assert not (tmp_path / "job_a61b3825").exists()


def test_quant_middleware_preserves_prior_artifacts_after_repair_retry_budget(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", str(tmp_path))
    output_dir = tmp_path / "improver-loop"
    output_dir.mkdir()
    (output_dir / "charts.json").write_text(
        json.dumps({"macro_signal": {"id": "macro_signal", "data": [{"x": 1}]}}),
        encoding="utf-8",
    )
    prior_summary = {
        "status": "success",
        "statistical_summary": "Computed macro signal.",
        "chart_ids": ["macro_signal"],
    }
    (output_dir / "execution_summary.json").write_text(
        json.dumps(prior_summary),
        encoding="utf-8",
    )

    middleware = QuantDeveloperToolBoundaryMiddleware()
    messages = [
        AIMessage(content="Use outputs/improver-loop/code/analysis.py"),
        *[
            ToolMessage(
                content=(
                    "Blocked quant analysis script before writing because "
                    "Python syntax validation failed."
                ),
                name="write_file",
                tool_call_id=f"call-blocked-{idx}",
                status="error",
            )
            for idx in range(4)
        ],
    ]
    request = _Request([SimpleNamespace(name="write_file")], messages=messages)

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(result=[AIMessage(content="still retrying")]),
    )

    handoff = json.loads(response.result[0].content)
    assert handoff["status"] == "failed"
    assert handoff["preserved_prior_artifacts"] is True
    assert handoff["chart_ids"] == ["macro_signal"]
    assert handoff["charts_json"] == str(output_dir / "charts.json")
    assert handoff["execution_summary_json"] == str(output_dir / "execution_summary.json")
    assert handoff["failure_summary_json"] == str(output_dir / "quant_failure_summary.json")
    assert (
        json.loads((output_dir / "charts.json").read_text(encoding="utf-8"))["macro_signal"]["id"]
        == "macro_signal"
    )
    assert (
        json.loads((output_dir / "execution_summary.json").read_text(encoding="utf-8"))
        == prior_summary
    )
    failure_summary = json.loads(
        (output_dir / "quant_failure_summary.json").read_text(encoding="utf-8")
    )
    assert failure_summary["failure_stage"] == "quant_initial_script_write"
    assert failure_summary["preserved_prior_artifacts"] is True


def test_quant_middleware_does_not_fail_handoff_after_wrong_tool_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", str(tmp_path))
    middleware = QuantDeveloperToolBoundaryMiddleware()
    messages = [
        AIMessage(content="Use outputs/improver-loop/code/analysis.py"),
        *[
            ToolMessage(
                content=(
                    "Blocked tool `execute` for quant-developer. First write a "
                    "compact analysis.py from the provided data_files and "
                    "schema_summary."
                ),
                name="execute",
                tool_call_id=f"call-blocked-{idx}",
                status="error",
            )
            for idx in range(4)
        ],
    ]
    request = _Request([SimpleNamespace(name="write_file")], messages=messages)

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(result=[AIMessage(content="retry with write_file")]),
    )

    assert response.result[0].content == "retry with write_file"
    assert not (tmp_path / "improver-loop" / "execution_summary.json").exists()


def test_quant_middleware_does_not_treat_root_analysis_as_script_written():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = _Request(
        [
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="execute"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="edit_file"),
        ],
        messages=[
            ToolMessage(
                content="Updated file /tmp/outputs/job/analysis.py",
                name="write_file",
                tool_call_id="call-root-write",
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert [tool.name for tool in response.tools] == ["write_file", "read_file"]


def test_quant_middleware_blocks_execute_after_failed_initial_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={"name": "execute", "id": "call-execute-after-failed-write", "args": {}},
        state={
            "messages": [
                ToolMessage(
                    content=("Error invoking tool 'write_file' with kwargs {'content': '...'}"),
                    name="write_file",
                    tool_call_id="call-failed-write",
                    status="error",
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-execute-after-failed-write"
    assert response.status == "error"
    assert "Blocked tool `execute`" in response.content
    assert "First write a compact analysis.py" in response.content
    assert "/code/analysis.py" in response.content
    assert "exactly one `write_file` call" in response.content


def test_quant_middleware_redirects_initial_write_when_analysis_py_exists(tmp_path):
    script_path = tmp_path / "outputs" / "job-1" / "code" / "analysis.py"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("print('old failed draft')\n")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-write-existing",
            "args": {
                "file_path": str(script_path),
                "content": "print('new draft')\n",
            },
        },
        state={"messages": [AIMessage(content=f"Use {script_path}")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-write-existing"
    assert response.status == "error"
    assert "analysis.py` already exists" in response.content
    assert str(script_path.with_name("analysis_v2.py")) in response.content
    assert "do not inspect, delete, or overwrite" in response.content


def test_quant_middleware_converts_initial_write_runtime_exception_to_tool_error(tmp_path):
    script_path = tmp_path / "outputs" / "job-1" / "code" / "analysis.py"
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-write-fails-empty",
            "args": {
                "file_path": str(script_path),
                "content": "print('compact draft')\n",
            },
        },
        state={"messages": [AIMessage(content=f"Use {script_path}")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError()),
    )

    assert response.tool_call_id == "call-write-fails-empty"
    assert response.name == "write_file"
    assert response.status == "error"
    assert "Recoverable `write_file` tool runtime error" in response.content
    assert "AssertionError: <empty exception message>" in response.content
    assert "The initial analysis script was not confirmed written" in response.content
    assert "exactly one compact `write_file` call" in response.content


def test_quant_middleware_converts_initial_write_guardrail_exception_to_tool_error(
    tmp_path, monkeypatch
):
    script_path = tmp_path / "outputs" / "job-1" / "code" / "analysis.py"
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-write-guardrail-fails-empty",
            "args": {
                "file_path": str(script_path),
                "content": "print('compact draft')\n",
            },
        },
        state={"messages": [AIMessage(content=f"Use {script_path}")]},
    )

    def fail_budget_check(_request):
        raise AssertionError()

    monkeypatch.setattr(middleware, "_script_budget_message", fail_budget_check)

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-write-guardrail-fails-empty"
    assert response.name == "write_file"
    assert response.status == "error"
    assert "Recoverable `write_file` tool runtime error" in response.content
    assert "AssertionError: <empty exception message>" in response.content
    assert "The initial analysis script was not confirmed written" in response.content


def test_quant_middleware_blocks_quant_macro_stats_source_reads():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "read_file",
            "id": "call-read-helper",
            "args": {"file_path": str(quant_dev._BACKEND_DIR / "agents" / "quant_macro_stats.py")},
        },
        state={
            "messages": [
                ToolMessage(
                    content="Updated file /tmp/outputs/job/code/analysis.py",
                    name="write_file",
                    tool_call_id="call-write",
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-read-helper"
    assert response.status == "error"
    assert "Blocked helper-source inspection" in response.content
    assert "direct_ols_forecast(forecast_frame" in response.content
    assert "classify_recession_regime(scored_frame" in response.content
    assert "historical_scenario_replay(panel, signal_cols=signal_cols" in response.content
    assert 'event_signal_backtest(panel, signal_col="composite"' in response.content
    assert "Use `read_file` only for the generated analysis script" in response.content


def test_quant_middleware_blocks_execute_before_script_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={"name": "execute", "id": "call-1", "args": {"command": "head x.csv"}},
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-1"
    assert response.status == "error"
    assert "Blocked tool `execute`" in response.content
    assert "First write a compact analysis.py" in response.content
    assert "next assistant response should contain only the `write_file` tool call" in (
        response.content
    )
    assert "Do not read `agents/quant_macro_stats.py`" in response.content
    assert "under 120 lines" in response.content
    assert "FRED/helper-centered" in response.content
    assert "international peers, regional consumers, or company earnings risk" in (response.content)
    assert "compact table-style summaries" in response.content
    assert 'execution_summary["source_context_files"]' in response.content
    assert "direct_ols_forecast" in response.content
    assert "do not import `statsmodels`" in response.content
    assert "save_quant_outputs" in response.content
    assert "do not import `agents.quant_utils`" in response.content


def test_quant_script_budget_message_routes_historical_simulation_to_replay_helpers(tmp_path):
    middleware = QuantDeveloperToolBoundaryMiddleware()
    oversized_content = "\n".join(
        [
            "from agents.quant_macro_stats import save_quant_outputs",
            "DATA_FILES = {'UNRATE': '/tmp/unrate.csv'}",
            *[f"metric_{idx} = {idx}" for idx in range(370)],
        ]
    )
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-oversized-historical-sim",
            "args": {
                "file_path": str(tmp_path / "outputs" / "job" / "code" / "analysis.py"),
                "content": oversized_content,
            },
        },
        state={"messages": [AIMessage(content="historical simulation what happened next")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "historical-simulation path" in response.content
    assert "compare_analog_windows" in response.content
    assert "historical_scenario_replay" in response.content
    assert "direct forecast path when the user explicitly asks for a point forecast" in (
        response.content
    )


def test_quant_middleware_allows_execute_after_script_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={"name": "execute", "id": "call-2", "args": {"command": "python analysis.py"}},
        state={
            "messages": [
                ToolMessage(
                    content="Updated file /tmp/outputs/job/code/analysis.py",
                    name="write_file",
                    tool_call_id="call-write",
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="ok",
            name="execute",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    assert response.content == "ok"


def test_quant_middleware_blocks_execute_package_install_after_script_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "execute",
            "id": "call-install",
            "args": {"command": "/usr/bin/python3 -m pip install -t backend pandas"},
        },
        state={
            "messages": [
                ToolMessage(
                    content="Updated file /tmp/outputs/job/code/analysis.py",
                    name="write_file",
                    tool_call_id="call-write",
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "Blocked quant-developer runtime package installation" in response.content
    assert "already includes the backend Python dependencies" in response.content


def test_quant_middleware_blocks_script_runtime_package_install():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-write-installer",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "import subprocess\n"
                    "subprocess.check_call(['pip', 'install', 'statsmodels'])\n"
                    "print('done')\n"
                ),
            },
        },
        state={"messages": []},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "attempts runtime package installation" in response.content
    assert "already includes pandas, numpy, and scipy" in response.content


def test_quant_middleware_removes_tools_after_successful_handoff():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = _Request(
        [
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="execute"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="edit_file"),
        ],
        messages=[
            ToolMessage(
                content=(
                    '{"charts_json": "/tmp/job/charts.json", '
                    '"execution_summary_json": "/tmp/job/execution_summary.json", '
                    '"chart_ids": ["chart_1"]}'
                ),
                name="execute",
                tool_call_id="call-execute",
                status="success",
            )
        ],
    )

    response = middleware.wrap_model_call(request, lambda req: req)

    assert response.tools == []


def test_quant_middleware_returns_compact_handoff_after_successful_execute():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    handoff = (
        '{"charts_json": "/tmp/job/charts.json", '
        '"execution_summary_json": "/tmp/job/execution_summary.json", '
        '"chart_ids": ["chart_1"]}'
    )
    request = _Request(
        [SimpleNamespace(name="execute"), SimpleNamespace(name="read_file")],
        messages=[
            ToolMessage(
                content=handoff,
                name="execute",
                tool_call_id="call-execute",
                status="success",
            )
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(result=[AIMessage(content="Let me verify first.")]),
    )

    assert response.result[0].content == handoff


def test_quant_middleware_uses_original_messages_after_tool_filtering():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    handoff = (
        '{"charts_json": "/tmp/job/charts.json", '
        '"execution_summary_json": "/tmp/job/execution_summary.json", '
        '"chart_ids": ["chart_1"]}'
    )
    request = _DroppingOverrideRequest(
        [SimpleNamespace(name="execute"), SimpleNamespace(name="read_file")],
        messages=[
            ToolMessage(
                content=handoff,
                name="execute",
                tool_call_id="call-execute",
                status="success",
            )
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(content=('<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="read_file">'))
            ]
        ),
    )

    assert response.result[0].content == handoff


def test_quant_middleware_returns_failure_handoff_after_pseudo_tool_call_markup(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", str(tmp_path))
    middleware = QuantDeveloperToolBoundaryMiddleware()
    messages = [
        AIMessage(
            content=(
                "Write /home/vorndranj/projects/DeepResearchAgent/backend/outputs/"
                "improver-loop/code/analysis.py"
            )
        )
    ]
    request = _Request([SimpleNamespace(name="write_file")], messages=messages)

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=('<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="write_file">')
                )
            ]
        ),
    )

    handoff = json.loads(response.result[0].content)
    output_dir = tmp_path / "improver-loop"
    assert handoff["status"] == "failed"
    assert handoff["failure_stage"] == "quant_malformed_tool_call"
    assert handoff["chart_ids"] == []
    assert handoff["methods_used"] == ["quant_malformed_tool_call_guard"]
    assert handoff["charts_json"] == str(output_dir / "charts.json")
    assert handoff["execution_summary_json"] == str(output_dir / "execution_summary.json")
    assert json.loads((output_dir / "charts.json").read_text(encoding="utf-8")) == []
    summary = json.loads((output_dir / "execution_summary.json").read_text(encoding="utf-8"))
    assert summary["failure_stage"] == "quant_malformed_tool_call"
    assert summary["methods_used"] == ["quant_malformed_tool_call_guard"]


def test_quant_middleware_recovers_recession_dashboard_pseudo_write_as_tool_call():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "T10Y3M": "/tmp/T10Y3M.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "INDPRO": "/tmp/INDPRO.csv",
        "USREC": "/tmp/USREC.csv",
        "DRALACBN": "/tmp/DRALACBN.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="build_recession_dashboard_artifacts"),
            SimpleNamespace(name="write_file"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Write /tmp/outputs/improver-loop/code/analysis.py\n"
                    "Full approved user request for `original_query`: Create a "
                    "recession-dashboard report with 6-8 charts.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        "The helper fits, but I will write a file. "
                        '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="write_file">'
                    )
                )
            ]
        ),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_recession_dashboard_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    assert tool_call["args"]["data_files"] == data_files
    assert "recession-dashboard report" in tool_call["args"]["query"]


def test_quant_middleware_recovers_recession_dashboard_pseudo_call_with_runtime_job_id():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "T10Y3M": "/tmp/T10Y3M.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "INDPRO": "/tmp/INDPRO.csv",
        "USREC": "/tmp/USREC.csv",
        "BAA10YM": "/tmp/BAA10YM.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="build_recession_dashboard_artifacts"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="write_file"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Full approved user request for `original_query`: Create a "
                    "recession-dashboard report over the last 40 years. Produce "
                    "6-8 governed renderable charts.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
        runtime=SimpleNamespace(context={"job_id": "improver-loop"}),
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        "I should use `build_recession_dashboard_artifacts`, "
                        "but I will emit markup. "
                        "<｜｜DSML｜｜tool_calls> "
                        '<｜｜DSML｜｜invoke name="build_recession_dashboard_artifacts">'
                    )
                )
            ]
        ),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_recession_dashboard_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    assert tool_call["args"]["data_files"] == data_files
    assert "6-8 governed renderable charts" in tool_call["args"]["query"]


def test_quant_middleware_forces_recession_helper_after_skill_reads():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "GDPC1": "/tmp/GDPC1.csv",
        "A191RL1Q225SBEA": "/tmp/A191RL1Q225SBEA.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "INDPRO": "/tmp/INDPRO.csv",
        "USREC": "/tmp/USREC.csv",
    }
    query = (
        "Compare real GDP growth, unemployment, recession periods, and "
        "industrial production since 1980. Produce 6-8 governed renderable "
        "charts that preserve all chart IDs into the report."
    )
    request = _Request(
        [
            SimpleNamespace(name="build_recession_dashboard_artifacts"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="write_file"),
        ],
        messages=[
            AIMessage(
                content=(
                    f"Full approved user request for `original_query`: {query}\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            ),
            ToolMessage(
                content=(
                    "---\nname: quant-macro-helper-workflows\n---\n"
                    "Use build_recession_dashboard_artifacts for recession charts."
                ),
                name="read_file",
                tool_call_id="call-read-skill",
            ),
        ],
        runtime=SimpleNamespace(context={"job_id": "improver-78d48a20"}),
    )
    handler_called = False

    def handler(req):
        nonlocal handler_called
        handler_called = True
        return ModelResponse(result=[AIMessage(content="I will call it now.")])

    response = middleware.wrap_model_call(request, handler)

    assert handler_called is False
    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_recession_dashboard_artifacts"
    assert tool_call["args"]["job_id"] == "improver-78d48a20"
    assert tool_call["args"]["data_files"] == data_files
    assert "Compare real GDP growth" in tool_call["args"]["query"]


def test_quant_middleware_forces_recession_helper_from_natural_fred_chart_prompt(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(quant_middleware, "_BACKEND_DIR", tmp_path)
    auto_dir = tmp_path / "data" / "_auto"
    auto_dir.mkdir(parents=True)
    base_timestamp = quant_middleware.time.time_ns() - 5_000_000_000
    required_series = ["T10Y3M", "UNRATE", "INDPRO", "USREC", "BAA10YM"]
    expected_paths = {}
    for index, series_id in enumerate(required_series):
        path = auto_dir / f"fred_get_series_{series_id}_{base_timestamp + index}_abcdef.csv"
        path.write_text("date,value\n2025-01-01,1\n", encoding="utf-8")
        expected_paths[series_id] = str(path)

    query = (
        "Create a recession-dashboard report using FRED time series for the "
        "10-year minus 3-month Treasury spread, unemployment, industrial "
        "production, credit conditions, and recession indicators over the "
        "last 40 years. Produce 6-8 governed renderable charts."
    )
    request = _Request(
        [
            SimpleNamespace(name="build_recession_dashboard_artifacts"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="execute"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    f"Full approved user request for `original_query`: {query}\n"
                    "The FRED fetch succeeded, but the handoff omitted exact paths."
                )
            ),
            ToolMessage(
                content=(
                    "1\t---\n"
                    "2\tname: quant-macro-helper-workflows\n"
                    "3\tdescription: Deterministic macro helper routes.\n"
                    "4\t---\n"
                    "5\tUse build_recession_dashboard_artifacts for recession charts."
                ),
                tool_call_id="call-read-skill",
            ),
        ],
    )
    handler_called = False

    def handler(req):
        nonlocal handler_called
        handler_called = True
        return ModelResponse(result=[AIMessage(content="I will inspect files first.")])

    response = QuantDeveloperToolBoundaryMiddleware().wrap_model_call(request, handler)

    assert handler_called is False
    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_recession_dashboard_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    assert tool_call["args"]["data_files"] == expected_paths
    assert "10-year minus 3-month Treasury spread" in tool_call["args"]["query"]


def test_quant_middleware_recovers_consumer_stress_pseudo_write_as_tool_call():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "PSAVERT": "/tmp/PSAVERT.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "AHETPI": "/tmp/AHETPI.csv",
        "UMCSENT": "/tmp/UMCSENT.csv",
        "DPCERA3M086SBEA": "/tmp/DPCERA3M086SBEA.csv",
        "TOTALSL": "/tmp/TOTALSL.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="build_consumer_stress_dashboard_artifacts"),
            SimpleNamespace(name="write_file"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Write /tmp/outputs/improver-loop/code/analysis.py\n"
                    "Full approved user request for `original_query`: Analyze "
                    "consumer stress with a chart dashboard.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        "I will write a script. "
                        '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="write_file">'
                    )
                )
            ]
        ),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_consumer_stress_dashboard_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    assert tool_call["args"]["data_files"] == data_files
    assert "consumer stress" in tool_call["args"]["query"]


def test_quant_middleware_recovers_consumer_stress_pseudo_helper_with_substitutes():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "PSAVERT": "/tmp/PSAVERT.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "CES0500000003": "/tmp/CES0500000003.csv",
        "DSPIC96": "/tmp/DSPIC96.csv",
        "UMCSENT": "/tmp/UMCSENT.csv",
        "DPCERA3M086SBEA": "/tmp/DPCERA3M086SBEA.csv",
        "DRCCLACBS": "/tmp/DRCCLACBS.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="build_consumer_stress_dashboard_artifacts"),
            SimpleNamespace(name="write_file"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Full approved user request for `original_query`: Analyze "
                    "whether the US consumer is under stress. Build a 6-8 chart "
                    "dashboard.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
        runtime=SimpleNamespace(context={"job_id": "improver-loop"}),
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        "This matches `build_consumer_stress_dashboard_artifacts`. "
                        "<｜｜DSML｜｜tool_calls>"
                        '<｜｜DSML｜｜invoke name="build_consumer_stress_dashboard_artifacts">'
                    )
                )
            ]
        ),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_consumer_stress_dashboard_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    assert tool_call["args"]["data_files"] == data_files
    assert "consumer is under stress" in tool_call["args"]["query"]


def test_quant_middleware_recovers_consumer_stress_pseudo_todos_without_consumption():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "PSAVERT": "/tmp/PSAVERT.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "DSPIC96": "/tmp/DSPIC96.csv",
        "UMCSENT": "/tmp/UMCSENT.csv",
        "TOTALSL": "/tmp/TOTALSL.csv",
        "PCEPILFE": "/tmp/PCEPILFE.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="build_consumer_stress_dashboard_artifacts"),
            SimpleNamespace(name="write_file"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Full approved user request for `original_query`: Analyze "
                    "whether the US consumer is under stress using FRED macro data. "
                    "Build a 6-8 chart dashboard with sentiment or consumption "
                    "where available.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
        runtime=SimpleNamespace(context={"job_id": "improver-loop"}),
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        "This is a consumer-stress dashboard task. I should use "
                        "`build_consumer_stress_dashboard_artifacts`. "
                        "<｜｜DSML｜｜tool_calls>"
                        '<｜｜DSML｜｜invoke name="write_todos">'
                    )
                )
            ]
        ),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_consumer_stress_dashboard_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    assert tool_call["args"]["data_files"] == data_files
    assert "consumer is under stress" in tool_call["args"]["query"]


def test_quant_middleware_recovers_inflation_policy_pseudo_skill_read_as_tool_call():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "CPILFESL": "/tmp/CPILFESL.csv",
        "FEDFUNDS": "/tmp/FEDFUNDS.csv",
        "USREC": "/tmp/USREC.csv",
    }
    data_file_lines = "\n".join(f"- {key}: {path}" for key, path in data_files.items())
    request = _Request(
        [
            SimpleNamespace(name="build_inflation_policy_chart_pack_artifacts"),
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="write_file"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Build a "
                    "chart-heavy macro report comparing headline CPI inflation, "
                    "core CPI inflation, and the effective federal funds rate.\n"
                    f"data_files:\n{data_file_lines}\n"
                )
            )
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        "This is a perfect match for "
                        "`build_inflation_policy_chart_pack_artifacts`. "
                        "<｜｜DSML｜｜tool_calls>"
                        '<｜｜DSML｜｜invoke name="read_file">'
                        '<｜｜DSML｜｜parameter name="file_path" string="true">'
                        "/home/vorndranj/projects/DeepResearchAgent/backend/skills/"
                        "quant-developer/quant-macro-helper-workflows/SKILL.md"
                        "</｜｜DSML｜｜parameter>"
                    )
                )
            ]
        ),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_inflation_policy_chart_pack_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    assert tool_call["args"]["data_files"] == data_files
    assert "headline CPI inflation" in tool_call["args"]["query"]


def test_quant_middleware_recovers_pseudo_quant_skill_read_when_no_helper_matches():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    skill_path = (
        "/home/vorndranj/projects/DeepResearchAgent/backend/skills/"
        "quant-developer/quant-macro-helper-workflows/SKILL.md"
    )
    request = _Request(
        [
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="write_file"),
        ],
        messages=[AIMessage(content="Job ID: improver-loop\nNo chart helper fits yet.")],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        "<｜｜DSML｜｜tool_calls>"
                        '<｜｜DSML｜｜invoke name="read_file">'
                        '<｜｜DSML｜｜parameter name="file_path" string="true">'
                        f"{skill_path}</｜｜DSML｜｜parameter>"
                    )
                )
            ]
        ),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "read_file"
    assert tool_call["args"]["file_path"] == skill_path


def test_quant_middleware_recovers_historical_replay_pseudo_write_as_tool_call():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "UNRATE": "/tmp/UNRATE.csv",
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "FEDFUNDS": "/tmp/FEDFUNDS.csv",
        "INDPRO": "/tmp/INDPRO.csv",
        "USREC": "/tmp/USREC.csv",
        "DSPIC96": "/tmp/DSPIC96.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="build_historical_replay_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Write /tmp/outputs/improver-loop/code/analysis.py\n"
                    "Full approved user request for `original_query`: Make a "
                    "historical replay report with a chart pack.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        "I will write a script. "
                        '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="write_file">'
                    )
                )
            ]
        ),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_historical_replay_chart_pack_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    assert tool_call["args"]["data_files"] == data_files
    assert "historical replay" in tool_call["args"]["query"]


def test_quant_middleware_recovers_macro_cycle_pseudo_write_as_tool_call():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "FEDFUNDS": "/tmp/FEDFUNDS.csv",
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "DGS10": "/tmp/DGS10.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "PAYEMS": "/tmp/PAYEMS.csv",
        "INDPRO": "/tmp/INDPRO.csv",
        "GDP": "/tmp/GDP.csv",
        "PSAVERT": "/tmp/PSAVERT.csv",
        "UMCSENT": "/tmp/UMCSENT.csv",
        "USREC": "/tmp/USREC.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="build_macro_cycle_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Write /tmp/outputs/improver-loop/code/analysis.py\n"
                    "Full approved user request for `original_query`: Create a "
                    "macro cycle chart pack for an investment committee.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        "I will write a script. "
                        '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="write_file">'
                    )
                )
            ]
        ),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_macro_cycle_chart_pack_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    assert tool_call["args"]["data_files"] == data_files
    assert "macro cycle chart pack" in tool_call["args"]["query"]


def test_quant_middleware_recovers_macro_regime_pseudo_write_without_saving_rate():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "FEDFUNDS": "/tmp/FEDFUNDS.csv",
        "CPIAUCSL": "/tmp/CPIAUCSL.csv",
        "DGS10": "/tmp/DGS10.csv",
        "UNRATE": "/tmp/UNRATE.csv",
        "PAYEMS": "/tmp/PAYEMS.csv",
        "INDPRO": "/tmp/INDPRO.csv",
        "GDP": "/tmp/GDP.csv",
        "UMCSENT": "/tmp/UMCSENT.csv",
        "USREC": "/tmp/USREC.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="build_macro_cycle_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Write /tmp/outputs/improver-loop/code/analysis.py\n"
                    "Full approved user request for `original_query`: Test whether "
                    "current macro conditions look like a soft landing, delayed "
                    "recession, or reacceleration. Produce 6-8 governed charts.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        "I will write a script. "
                        '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="write_file">'
                    )
                )
            ]
        ),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_macro_cycle_chart_pack_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    assert tool_call["args"]["data_files"] == data_files
    assert "soft landing" in tool_call["args"]["query"]


def test_quant_middleware_recovers_macro_cycle_execute_markup_from_recent_autosaves(
    tmp_path, monkeypatch
):
    middleware = QuantDeveloperToolBoundaryMiddleware()
    monkeypatch.setattr(quant_middleware, "_BACKEND_DIR", tmp_path)
    auto_dir = tmp_path / "data" / "_auto"
    auto_dir.mkdir(parents=True)
    base_timestamp = quant_middleware.time.time_ns() - 5_000_000_000
    required_series = [
        "FEDFUNDS",
        "CPIAUCSL",
        "DGS10",
        "UNRATE",
        "PAYEMS",
        "INDPRO",
        "GDPC1",
        "UMCSENT",
        "USREC",
    ]
    expected_paths = {}
    for index, series_id in enumerate(required_series):
        path = auto_dir / f"fred_get_series_{series_id}_{base_timestamp + index}_abcdef.csv"
        path.write_text("date,value\n2025-01-01,1\n", encoding="utf-8")
        expected_paths[series_id] = str(path)

    request = _Request(
        [
            SimpleNamespace(name="build_macro_cycle_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="execute"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Create a "
                    "macro cycle chart pack for an investment committee.\n"
                    "Fetched required FRED series: "
                    f"{', '.join(required_series)}."
                )
            )
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        "According to the skill, I should use "
                        "`build_macro_cycle_chart_pack_artifacts` first. "
                        "<｜｜DSML｜｜tool_calls>"
                        '<｜｜DSML｜｜invoke name="execute">'
                        '<｜｜DSML｜｜parameter name="command" string="true">'
                        "ls /tmp"
                    )
                )
            ]
        ),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_macro_cycle_chart_pack_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    assert tool_call["args"]["data_files"] == expected_paths
    assert "macro cycle chart pack" in tool_call["args"]["query"]


def test_quant_middleware_recovers_unemployment_forecast_pseudo_write_as_tool_call():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    data_files = {
        "UNRATE_FRED": "/tmp/UNRATE.csv",
        "PAYEMS_FRED": "/tmp/PAYEMS.csv",
        "ICSA_FRED": "/tmp/ICSA.csv",
    }
    request = _Request(
        [
            SimpleNamespace(name="build_unemployment_forecast_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Write /tmp/outputs/improver-loop/code/analysis.py\n"
                    "Full approved user request for `original_query`: Build an "
                    "unemployment forecast-overlay report with charts.\n"
                    f'"data_files": {json.dumps(data_files)}'
                )
            )
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        "I will write a script. "
                        '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="write_file">'
                    )
                )
            ]
        ),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_unemployment_forecast_chart_pack_artifacts"
    assert tool_call["args"]["job_id"] == "improver-loop"
    assert tool_call["args"]["data_files"] == data_files
    assert "unemployment forecast-overlay" in tool_call["args"]["query"]


def test_quant_middleware_recovers_unemployment_forecast_from_truncated_autosaves(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(quant_middleware, "_BACKEND_DIR", tmp_path)
    auto_dir = tmp_path / "data" / "_auto"
    auto_dir.mkdir(parents=True)
    anchor = 1778643634249922198
    paths = {
        "UNRATE": auto_dir / f"fred_get_series_UNRATE_{anchor}_e7fa783c.csv",
        "PAYEMS": auto_dir / f"fred_get_series_PAYEMS_{anchor - 451276854}_711111cf.csv",
        "ICSA": auto_dir / f"fred_get_series_ICSA_{anchor + 342227150}_69137aee.csv",
    }
    for path in paths.values():
        path.write_text("date,value\n2026-01-01,1\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = _Request(
        [
            SimpleNamespace(name="build_unemployment_forecast_chart_pack_artifacts"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="write_todos"),
        ],
        messages=[
            AIMessage(
                content=(
                    "Job ID: improver-loop\n"
                    "Full approved user request for `original_query`: Build a "
                    "forecast-overlay report for US unemployment with charts.\n"
                    f'"data_files": {{"UNRATE": "{paths["UNRATE"]}"}}\n'
                    "The data-engineer result was truncated before PAYEMS and ICSA."
                )
            )
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        "Now let me check if the "
                        "`build_unemployment_forecast_chart_pack_artifacts` tool "
                        "is available: "
                        '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="write_todos">'
                    )
                )
            ]
        ),
    )

    message = response.result[0]
    assert message.content == ""
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "build_unemployment_forecast_chart_pack_artifacts"
    assert tool_call["args"]["data_files"]["UNRATE"] == str(paths["UNRATE"])
    assert tool_call["args"]["data_files"]["PAYEMS"] == str(paths["PAYEMS"])
    assert tool_call["args"]["data_files"]["ICSA"] == str(paths["ICSA"])


def test_quant_middleware_recovers_complete_pseudo_write_file_markup():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = _Request([SimpleNamespace(name="write_file")])

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="write_file">'
                        '<｜｜DSML｜｜parameter name="file_path" string="true">'
                        "/tmp/outputs/improver-loop/code/analysis.py"
                        "</｜｜DSML｜｜parameter>"
                        '<｜｜DSML｜｜parameter name="content" string="true">'
                        "print('saved')\n"
                        "</｜｜DSML｜｜parameter>"
                        "</｜｜DSML｜｜invoke></｜｜DSML｜｜tool_calls>"
                    )
                )
            ]
        ),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "write_file"
    assert tool_call["args"]["file_path"] == ("/tmp/outputs/improver-loop/code/analysis.py")
    assert tool_call["args"]["content"] == "print('saved')"


def test_quant_middleware_recovers_unterminated_pseudo_write_file_markup():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = _Request([SimpleNamespace(name="write_file")])

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=(
                        "Now let me write the script: "
                        '<｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="write_file">'
                        '<｜｜DSML｜｜parameter name="file_path" string="true">'
                        "/tmp/outputs/improver-loop/code/analysis.py"
                        "</｜｜DSML｜｜parameter>"
                        '<｜｜DSML｜｜parameter name="content" string="true">'
                        "#!/usr/bin/env python\nprint('saved')\n"
                    )
                )
            ]
        ),
    )

    message = response.result[0]
    assert message.content == ""
    assert len(message.tool_calls) == 1
    tool_call = message.tool_calls[0]
    assert tool_call["name"] == "write_file"
    assert tool_call["args"]["file_path"] == ("/tmp/outputs/improver-loop/code/analysis.py")
    assert tool_call["args"]["content"] == "#!/usr/bin/env python\nprint('saved')"


def test_quant_middleware_rejects_pseudo_tool_markup_even_with_real_tool_call(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", str(tmp_path))
    middleware = QuantDeveloperToolBoundaryMiddleware()
    messages = [
        AIMessage(
            content=(
                "Write /home/vorndranj/projects/DeepResearchAgent/backend/outputs/"
                "improver-loop/code/analysis.py"
            )
        )
    ]
    request = _Request([SimpleNamespace(name="write_file")], messages=messages)

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(
            result=[
                AIMessage(
                    content=('I will call the tool now. <｜｜DSML｜｜invoke name="write_file">'),
                    tool_calls=[
                        {
                            "name": "read_file",
                            "args": {"file_path": "x"},
                            "id": "call-read",
                        }
                    ],
                )
            ]
        ),
    )

    handoff = json.loads(response.result[0].content)
    assert handoff["status"] == "failed"
    assert handoff["failure_stage"] == "quant_malformed_tool_call"
    assert handoff["methods_used"] == ["quant_malformed_tool_call_guard"]


def test_quant_middleware_detects_handoff_without_tool_name_metadata():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    handoff = (
        '{"charts_json": "/tmp/job/charts.json", '
        '"execution_summary_json": "/tmp/job/execution_summary.json", '
        '"chart_ids": ["chart_1"]}'
    )
    request = _Request(
        [SimpleNamespace(name="execute"), SimpleNamespace(name="read_file")],
        messages=[
            ToolMessage(
                content=handoff,
                tool_call_id="call-execute",
                status="success",
            )
        ],
    )

    response = middleware.wrap_model_call(
        request,
        lambda req: ModelResponse(result=[AIMessage(content="Let me verify first.")]),
    )

    assert response.result[0].content == handoff


def test_quant_middleware_blocks_tools_after_successful_handoff():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={"name": "execute", "id": "call-after-success", "args": {"command": "cat x"}},
        state={
            "messages": [
                ToolMessage(
                    content=(
                        '{"charts_json": "/tmp/job/charts.json", '
                        '"execution_summary_json": "/tmp/job/execution_summary.json", '
                        '"chart_ids": ["chart_1"]}'
                    ),
                    name="execute",
                    tool_call_id="call-execute",
                    status="success",
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-after-success"
    assert response.status == "error"
    assert "Blocked post-success quant tool call" in response.content
    assert "Return only that compact JSON now" in response.content


def test_quant_middleware_blocks_oversized_python_write_before_sandbox():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    large_script = "\n".join(f"print({i})" for i in range(361))
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-large-write",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": large_script,
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-large-write"
    assert response.status == "error"
    assert "Blocked oversized quant analysis script" in response.content
    assert "limit is 360 lines" in response.content
    assert "Rewrite a compact analysis.py under 120 lines" in response.content
    assert "Produce 3-4 computed charts for ordinary prompts" in response.content
    assert "6-8 distinct renderable charts for explicit chart" in response.content
    assert "only exact paths you will load" in response.content
    assert "at most one compact non-FRED summary block" in response.content
    assert "World Bank, Census, SEC EDGAR, or BLS CSVs were handed off" in (response.content)
    assert 'execution_summary["source_context_files"]' in response.content
    assert "minimum viable broad-macro shape" in response.content
    assert "`historical_scenario_replay(...)`" in response.content
    assert "prior-cycle, historical-simulation, replay" in response.content
    assert "never leave requested provider sections as `not processed` placeholders" in (
        response.content
    )
    assert "analog fast path instead of the full broad macro template" in response.content
    assert "Do not add unemployment forecast, scenario, or regime-classifier" in (response.content)


def test_quant_middleware_allows_near_limit_python_write_before_sandbox():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    near_limit_script = "\n".join(f"print({i})" for i in range(323))
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-near-limit-write",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": near_limit_script,
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Updated file /tmp/outputs/job/code/analysis.py",
            name="write_file",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    assert response.tool_call_id == "call-near-limit-write"
    assert response.status == "success"


def test_quant_middleware_blocks_positional_sec_company_metrics(tmp_path):
    middleware = QuantDeveloperToolBoundaryMiddleware()
    sec_path = tmp_path / "AAPL_sec_edgar_company_facts_job.csv"
    sec_path.write_text(
        "fiscal_year,revenue,net_income,assets,liabilities,shares\n"
        "2025,416161000000,112010000000,359241000000,285508000000,15004697000\n",
        encoding="utf-8",
    )
    script = f"""
import pandas as pd
DATA_FILES = {{"AAPL": "{sec_path}"}}
df = pd.read_csv(DATA_FILES["AAPL"])
nr = df.select_dtypes(include=["number"])
metric = nr.iloc[:, -1].iloc[-1]
print(metric)
"""
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-sec-positional",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": script,
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-sec-positional"
    assert response.status == "error"
    assert "Blocked SEC company-facts analysis" in response.content
    assert "positional numeric columns" in response.content
    assert "summarize_sec_company_facts" in response.content


def test_quant_middleware_blocks_unsorted_sec_growth_metrics(tmp_path):
    middleware = QuantDeveloperToolBoundaryMiddleware()
    sec_path = tmp_path / "NVDA_sec_edgar_company_facts_job.csv"
    sec_path.write_text(
        "fiscal_year,revenue,net_income,operating_cash_flow\n"
        "2026,215940000000,120070000000,102720000000\n"
        "2025,130500000000,72880000000,64090000000\n"
        "2024,60920000000,29760000000,28090000000\n",
        encoding="utf-8",
    )
    script = f"""
import pandas as pd
df = pd.read_csv({str(sec_path)!r})
df["fiscal_year"] = df["fiscal_year"].astype(int)
df["revenue_growth_pct"] = df["revenue"].pct_change() * 100
cagr = (df["revenue"].values[-1] / df["revenue"].values[0]) ** (1 / 2) - 1
execution_summary = {{"statistical_summary": {{"revenue_cagr_pct": cagr * 100}}}}
"""
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-sec-unsorted-growth",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": script,
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-sec-unsorted-growth"
    assert response.status == "error"
    assert "Blocked SEC company-facts analysis" in response.content
    assert "sorting rows by `fiscal_year` ascending" in response.content
    assert "latest-first" in response.content


def test_quant_middleware_allows_sorted_sec_growth_metrics(tmp_path):
    middleware = QuantDeveloperToolBoundaryMiddleware()
    sec_path = tmp_path / "NVDA_sec_edgar_company_facts_job.csv"
    sec_path.write_text(
        "fiscal_year,revenue,net_income\n"
        "2026,215940000000,120070000000\n"
        "2025,130500000000,72880000000\n",
        encoding="utf-8",
    )
    script = f"""
import pandas as pd
df = pd.read_csv({str(sec_path)!r})
df = df.sort_values("fiscal_year").reset_index(drop=True)
df["revenue_growth_pct"] = df["revenue"].pct_change() * 100
cagr = (df["revenue"].values[-1] / df["revenue"].values[0]) - 1
execution_summary = {{"statistical_summary": {{"revenue_cagr_pct": cagr * 100}}}}
"""
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-sec-sorted-growth",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": script,
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Updated file /tmp/outputs/job/code/analysis.py",
            name="write_file",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    assert response.status == "success"


def test_quant_middleware_allows_sec_helper_summary_with_latest_field_names(tmp_path):
    middleware = QuantDeveloperToolBoundaryMiddleware()
    sec_path = tmp_path / "AAPL_sec_edgar_company_facts_job.csv"
    sec_path.write_text(
        "fiscal_year,revenue,net_income\n2025,416161000000,112010000000\n",
        encoding="utf-8",
    )
    script = f"""
from agents.quant_macro_stats import summarize_sec_company_facts
DATA_FILES = {{"AAPL": "{sec_path}"}}
summary = summarize_sec_company_facts(DATA_FILES["AAPL"])
execution_summary = {{"apple_earnings_risk": {{
    "latest_fiscal_year": summary.get("latest_fiscal_year"),
    "revenue_cagr_pct": summary.get("revenue_cagr_pct"),
    "net_income_growth_pct": summary.get("net_income_growth_pct"),
}}}}
"""
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-sec-helper-latest-fields",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": script,
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Updated file /tmp/outputs/job/code/analysis.py",
            name="write_file",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    assert response.status == "success"


def test_quant_middleware_blocks_root_analysis_write_before_sandbox():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-root-analysis",
            "args": {
                "file_path": "/tmp/outputs/job/analysis.py",
                "content": "print('ok')\n",
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-root-analysis"
    assert response.status == "error"
    assert "outside the required code artifact location" in response.content
    assert "code/analysis.py" in response.content
    assert "job output root" in response.content


def test_quant_middleware_blocks_truncated_write_path_before_sandbox():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-truncated-path",
            "args": {
                "file_path": "/tmp/outputs/impro",
                "content": "print('ok')\n",
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-truncated-path"
    assert response.status == "error"
    assert "outside the required code artifact location" in response.content
    assert "code/analysis.py" in response.content


def test_quant_middleware_empty_path_error_uses_concrete_job_paths(monkeypatch):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", "/tmp/outputs")
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-empty-path",
            "args": {"file_path": "", "content": "print('ok')\n"},
        },
        state={
            "messages": [
                AIMessage(
                    content=(
                        "Use outputs/improver-abc123/charts.json and "
                        "outputs/improver-abc123/execution_summary.json."
                    )
                )
            ]
        },
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-empty-path"
    assert response.status == "error"
    assert "target path is empty" in response.content
    assert "/tmp/outputs/improver-abc123/code/analysis.py" in response.content
    assert "/tmp/outputs/improver-abc123/code/analysis_v2.py" in response.content
    assert "do not omit it" in response.content


def test_quant_middleware_bad_path_error_infers_job_from_path(monkeypatch):
    monkeypatch.setattr(quant_dev, "OUTPUT_BASE_DIR", "/tmp/outputs")
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-test-py",
            "args": {
                "file_path": "/tmp/outputs/improver-xyz/code/test.py",
                "content": "print('ok')\n",
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "/tmp/outputs/improver-xyz/code/analysis.py" in response.content
    assert "/tmp/outputs/improver-xyz/code/analysis_v2.py" in response.content
    assert "file_path" in response.content


def test_quant_middleware_blocks_truncated_argument_marker_before_sandbox():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-truncated-content",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": "#!/usr/bin/env pytho...(argument truncated)",
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-truncated-content"
    assert response.status == "error"
    assert "tool-argument truncation marker" in response.content
    assert "Rewrite a much smaller complete analysis.py" in response.content


def test_quant_middleware_allows_compact_python_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-small-write",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": "print('ok')\n",
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Updated file /tmp/outputs/job/code/analysis.py",
            name="write_file",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    assert response.status == "success"


def test_quant_middleware_blocks_bad_data_files_manifest_suffix(tmp_path):
    csv_path = tmp_path / "fred_get_series_UMCSENT.csv"
    csv_path.write_text("date,value\n2024-01-01,75\n", encoding="utf-8")
    bad_path = csv_path.with_suffix(".png")
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-bad-manifest",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    f"DATA_FILES = {{\n    'UMCSENT': {str(bad_path)!r},\n}}\nprint(DATA_FILES)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "Blocked quant analysis script before writing" in response.content
    assert "non-data extension" in response.content
    assert "Copy exact CSV paths" in response.content
    assert "for only the DATA_FILES keys the script will load" in response.content


def test_quant_middleware_allows_existing_data_files_manifest(tmp_path):
    csv_path = tmp_path / "fred_get_series_UMCSENT.csv"
    csv_path.write_text("date,value\n2024-01-01,75\n", encoding="utf-8")
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-good-manifest",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    f"DATA_FILES = {{\n    'UMCSENT': {str(csv_path)!r},\n}}\nprint(DATA_FILES)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Updated file /tmp/outputs/job/code/analysis.py",
            name="write_file",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    assert response.status == "success"


def test_quant_middleware_repairs_unique_auto_saved_manifest_suffix(tmp_path):
    actual_path = tmp_path / "fred_get_series_UMCSENT_1777660567048294467_3d2d927b.csv"
    actual_path.write_text("date,value\n2024-01-01,75\n", encoding="utf-8")
    typo_path = tmp_path / "fred_get_series_UMCSENT_1777660567048294467_3d2d757b.csv"
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-near-miss-manifest",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    f"DATA_FILES = {{\n    'UMCSENT': {str(typo_path)!r},\n}}\nprint(DATA_FILES)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )
    seen_content = {}

    def handler(req):
        seen_content["content"] = req.tool_call["args"]["content"]
        return ToolMessage(
            content="Updated file /tmp/outputs/job/code/analysis.py",
            name="write_file",
            tool_call_id=req.tool_call["id"],
            status="success",
        )

    response = middleware.wrap_tool_call(request, handler)

    assert response.status == "success"
    assert str(actual_path) in seen_content["content"]
    assert str(typo_path) not in seen_content["content"]


def test_quant_middleware_repairs_nearby_auto_saved_manifest_timestamp(tmp_path):
    actual_path = tmp_path / "fred_get_series_USREC_1777755598026543227_aae2f573.csv"
    actual_path.write_text("date,value\n2024-01-01,0\n", encoding="utf-8")
    typo_path = tmp_path / "fred_get_series_USREC_1777755598046162015_aae2f573.csv"
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-timestamp-drift-manifest",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    f"DATA_FILES = {{\n    'USREC': {str(typo_path)!r},\n}}\nprint(DATA_FILES)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )
    seen_content = {}

    def handler(req):
        seen_content["content"] = req.tool_call["args"]["content"]
        return ToolMessage(
            content="Updated file /tmp/outputs/job/code/analysis.py",
            name="write_file",
            tool_call_id=req.tool_call["id"],
            status="success",
        )

    response = middleware.wrap_tool_call(request, handler)

    assert response.status == "success"
    assert str(actual_path) in seen_content["content"]
    assert str(typo_path) not in seen_content["content"]


def test_quant_middleware_blocks_mixed_frequency_fred_without_alignment_helper(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    yield_path = tmp_path / "fred_get_series_T10Y2Y.csv"
    claims_path = tmp_path / "fred_get_series_ICSA.csv"
    for path in [unrate_path, yield_path, claims_path]:
        path.write_text("date,value\n2024-01-01,1\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-mixed-frequency",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "DATA_FILES = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    f"    'T10Y2Y': {str(yield_path)!r},\n"
                    f"    'ICSA': {str(claims_path)!r},\n"
                    "}\n"
                    "print(DATA_FILES)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "Blocked mixed-frequency FRED analysis script" in response.content
    assert "align_period_features" in response.content
    assert "month-start FRED observations" in response.content


def test_quant_middleware_blocks_mixed_frequency_fred_with_compact_df_alias(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    yield_path = tmp_path / "fred_get_series_T10Y2Y.csv"
    for path in [unrate_path, yield_path]:
        path.write_text("date,value\n2024-01-01,1\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-mixed-frequency-df-alias",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "DF = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    f"    'T10Y2Y': {str(yield_path)!r},\n"
                    "}\n"
                    "print(DF)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "Blocked mixed-frequency FRED analysis script" in response.content
    assert "align_period_features" in response.content


def test_quant_middleware_blocks_mixed_frequency_fred_with_single_letter_manifest(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    yield_path = tmp_path / "fred_get_series_T10Y2Y.csv"
    for path in [unrate_path, yield_path]:
        path.write_text("date,value\n2024-01-01,1\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-mixed-frequency-d-alias",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "D = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    f"    'T10Y2Y': {str(yield_path)!r},\n"
                    "}\n"
                    "print(D)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "Blocked mixed-frequency FRED analysis script" in response.content
    assert "align_period_features" in response.content


def test_quant_middleware_blocks_hand_rolled_analog_window_comparison(tmp_path):
    usrec_path = tmp_path / "fred_get_series_USREC.csv"
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    usrec_path.write_text("date,value\n2024-01-01,0\n", encoding="utf-8")
    unrate_path.write_text("date,value\n2024-01-01,4.0\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-analog-handroll",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import align_period_features, save_quant_outputs\n"
                    "DATA_FILES = {\n"
                    f"    'USREC': {str(usrec_path)!r},\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    "}\n"
                    "analog_similarity_ranking = [{'analog': '1995', 'distance': 0.0}]\n"
                    "analogy_breakdown = {'1995': {'top_divergences': []}}\n"
                    "execution_summary = {\n"
                    "    'analog_similarity_ranking': analog_similarity_ranking,\n"
                    "    'analogy_breakdown': analogy_breakdown,\n"
                    "}\n"
                    "save_quant_outputs('/tmp/outputs/job', {}, execution_summary)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "analog window comparison requires `compare_analog_windows`" in response.content


def test_quant_middleware_allows_mixed_frequency_fred_with_alignment_helper(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    yield_path = tmp_path / "fred_get_series_T10Y2Y.csv"
    claims_path = tmp_path / "fred_get_series_ICSA.csv"
    for path in [unrate_path, yield_path, claims_path]:
        path.write_text("date,value\n2024-01-01,1\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-aligned-mixed-frequency",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import align_period_features\n"
                    "DATA_FILES = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    f"    'T10Y2Y': {str(yield_path)!r},\n"
                    f"    'ICSA': {str(claims_path)!r},\n"
                    "}\n"
                    'panel = align_period_features({}, frequency="M", how="inner", timestamp_position="start")\n'
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Updated file /tmp/outputs/job/code/analysis.py",
            name="write_file",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    assert response.status == "success"


def test_quant_middleware_blocks_handrolled_macro_helper_artifacts(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    recession_path = tmp_path / "fred_get_series_USREC.csv"
    for path in [unrate_path, recession_path]:
        path.write_text("date,value\n2024-01-01,1\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-handrolled-macro-artifacts",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import align_period_features\n"
                    "DATA_FILES = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    f"    'USREC': {str(recession_path)!r},\n"
                    "}\n"
                    "panel = align_period_features({}, frequency='M')\n"
                    "execution_summary = {\n"
                    "    'regime_classification': {'label': 'soft_landing'},\n"
                    "    'category_scores': {},\n"
                    "    'evidence_table': [],\n"
                    "    'scenarios': [],\n"
                    "    'composite_risk': {'risk': 0.35},\n"
                    "    'latest_index_value': 0.4,\n"
                    "}\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "Blocked broad macro analysis script" in response.content
    assert "classify_recession_regime" in response.content
    assert "build_scenario_stress_test" in response.content
    assert "build_composite_predictive_indicator" in response.content
    assert "without inspecting helper source" in response.content
    assert 'target="recession_risk"' in response.content
    assert 'topic="macro cycle"' in response.content
    assert "indicator_specs=indicator_specs" in response.content


def test_quant_middleware_allows_helper_backed_macro_artifacts(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    recession_path = tmp_path / "fred_get_series_USREC.csv"
    for path in [unrate_path, recession_path]:
        path.write_text("date,value\n2024-01-01,1\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-helper-backed-macro-artifacts",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import (\n"
                    "    align_period_features,\n"
                    "    classify_recession_regime,\n"
                    "    build_scenario_stress_test,\n"
                    "    build_composite_predictive_indicator,\n"
                    ")\n"
                    "DATA_FILES = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    f"    'USREC': {str(recession_path)!r},\n"
                    "}\n"
                    "panel = align_period_features({}, frequency='M')\n"
                    "regime = classify_recession_regime(panel, indicator_specs=[])\n"
                    "scenario_rows = [\n"
                    "    {'scenario': 'base', 'assumptions': {}, 'indicator_triggers': [], 'confidence': 'medium', 'uncertainty_notes': []},\n"
                    "    {'scenario': 'bull', 'assumptions': {}, 'indicator_triggers': [], 'confidence': 'low', 'uncertainty_notes': []},\n"
                    "    {'scenario': 'bear', 'assumptions': {}, 'indicator_triggers': [], 'confidence': 'low', 'uncertainty_notes': []},\n"
                    "]\n"
                    "scenarios = build_scenario_stress_test(scenario_rows, topic='macro cycle')\n"
                    "risk = build_composite_predictive_indicator(panel, target_col='USREC', feature_cols=[])\n"
                    "execution_summary = {**regime, **scenarios, **risk}\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Updated file /tmp/outputs/job/code/analysis.py",
            name="write_file",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    assert response.status == "success"


def test_quant_middleware_blocks_composite_handoff_without_historical_replay(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    recession_path = tmp_path / "fred_get_series_USREC.csv"
    for path in [unrate_path, recession_path]:
        path.write_text("date,value\n2024-01-01,1\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-composite-without-replay",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import (\n"
                    "    build_composite_predictive_indicator,\n"
                    "    save_quant_outputs,\n"
                    ")\n"
                    "DATA_FILES = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    f"    'USREC': {str(recession_path)!r},\n"
                    "}\n"
                    "panel = None\n"
                    "risk = build_composite_predictive_indicator(panel, target_col='USREC', feature_cols=[])\n"
                    "execution_summary = {'recession_risk': risk}\n"
                    "save_quant_outputs('/tmp/outputs/job', {}, execution_summary)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "historical_scenario_replay" in response.content
    assert "signal_framework_backtest" in response.content
    assert "historical replay rows" in response.content


def test_quant_middleware_blocks_handrolled_signal_framework_evidence(tmp_path):
    recession_path = tmp_path / "fred_get_series_USREC.csv"
    recession_path.write_text("date,value\n2024-01-01,0\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-handrolled-signal-framework",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import save_quant_outputs\n"
                    f"DATA_FILES = {{'USREC': {str(recession_path)!r}}}\n"
                    "false_alarm_episodes = []\n"
                    "pre_recession_scores = {}\n"
                    "execution_summary = {'signal_framework_backtest': {'false_alarm_episodes': false_alarm_episodes, 'pre_recession_scores': pre_recession_scores}}\n"
                    "save_quant_outputs('/tmp/outputs/job', {}, execution_summary)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "signal_framework_backtest" in response.content
    assert "signal framework hit/miss evidence" in response.content


def test_quant_middleware_treats_data_manifest_alias_as_data_files(tmp_path):
    recession_path = tmp_path / "fred_get_series_USREC.csv"
    recession_path.write_text("date,value\n2024-01-01,0\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-data-alias-handrolled-signal",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import save_quant_outputs\n"
                    f"DATA = {{'USREC': {str(recession_path)!r}}}\n"
                    "false_alarm_analysis = {'false_alarms': []}\n"
                    "execution_summary = {'false_alarm_analysis': false_alarm_analysis}\n"
                    "save_quant_outputs('/tmp/outputs/job', {}, execution_summary)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "signal_framework_backtest" in response.content
    assert "signal framework hit/miss evidence" in response.content


def test_quant_middleware_gives_targeted_unemployment_false_alarm_recipe(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    usrec_path = tmp_path / "fred_get_series_USREC.csv"
    for path in [unrate_path, usrec_path]:
        path.write_text("date,value\n2024-01-01,0\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-unemployment-forecast-false-alarm",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import direct_ols_forecast, save_quant_outputs\n"
                    "DATA_FILES = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    f"    'USREC': {str(usrec_path)!r},\n"
                    "}\n"
                    "forecast = direct_ols_forecast(forecast_frame, target_col='UNRATE', feature_cols=['spread'], horizon=6)\n"
                    "false_alarm_summary = {'false_alarms': []}\n"
                    "execution_summary = {**forecast, 'unemployment_forecast': True, 'false_alarm_summary': false_alarm_summary}\n"
                    "save_quant_outputs('/tmp/outputs/job', {}, execution_summary)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "`direct_ols_forecast(...)` and `signal_framework_backtest(...)` are complements" in (
        response.content
    )
    assert "threshold=2" in response.content
    assert "model-vs-baseline RMSE" in response.content


def test_quant_middleware_blocks_signal_framework_with_unrate_recession_col(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    usrec_path = tmp_path / "fred_get_series_USREC.csv"
    for path in [unrate_path, usrec_path]:
        path.write_text("date,value\n2024-01-01,0\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-signal-framework-continuous-target",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import signal_framework_backtest, save_quant_outputs\n"
                    "DATA_FILES = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    f"    'USREC': {str(usrec_path)!r},\n"
                    "}\n"
                    "signal = signal_framework_backtest(panel, component_cols=['curve'], recession_col='UNRATE')\n"
                    "execution_summary = {**signal}\n"
                    "save_quant_outputs('/tmp/outputs/job', {}, execution_summary)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "binary 0/1 event indicator" in response.content
    assert 'recession_col="USREC"' in response.content


def test_quant_middleware_blocks_empty_scenario_helper_rows():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-empty-scenario-rows",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import build_scenario_stress_test\n"
                    "scenarios = build_scenario_stress_test([], topic='US Macro')\n"
                    "execution_summary = {**scenarios}\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "build_scenario_stress_test([])" in response.content
    assert "`base`, `bull`, and `bear`" in response.content
    assert "scenario_rows" in response.content


def test_quant_middleware_blocks_stale_chart_id_handoff_after_save():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-stale-chart-ids",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "import json\n"
                    "from agents.quant_macro_stats import save_quant_outputs\n"
                    "charts = {'dropped_later': {'type': 'line', 'data': [], 'series': []}}\n"
                    "execution_summary = {}\n"
                    "save_quant_outputs('/tmp/outputs/job', charts, execution_summary)\n"
                    "chart_ids = list(charts.keys())\n"
                    "print(json.dumps({'chart_ids': chart_ids}))\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "Blocked stale quant handoff" in response.content
    assert "writer receives only saved chart IDs" in response.content


def test_quant_middleware_blocks_manual_chart_artifact_json_dump(tmp_path):
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-manual-json-dump",
            "args": {
                "file_path": str(tmp_path / "outputs" / "job" / "code" / "analysis.py"),
                "content": (
                    "import json\n"
                    "charts = {'labor_replay': {'type': 'dual_axis', 'data': []}}\n"
                    "execution_summary = {'chart_ids': ['labor_replay']}\n"
                    "with open('/tmp/outputs/job/charts.json', 'w') as f:\n"
                    "    json.dump(charts, f, indent=2)\n"
                    "with open('/tmp/outputs/job/execution_summary.json', 'w') as f:\n"
                    "    json.dump(execution_summary, f, indent=2)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "Blocked manual quant artifact serialization" in response.content
    assert "save_quant_outputs" in response.content
    assert "non-finite values converted to null" in response.content


def test_quant_middleware_blocks_handrolled_regression_forecast(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    unrate_path.write_text("date,value\n2024-01-01,3.9\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-handrolled-forecast",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from sklearn.linear_model import LinearRegression\n"
                    "from agents.quant_macro_stats import direct_ols_forecast\n"
                    "DATA_FILES = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    "}\n"
                    "model = LinearRegression()\n"
                    "forecast_table = []\n"
                    "execution_summary = {'unemployment_forecast': forecast_table}\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "Blocked econometric forecast script" in response.content
    assert "Importing `direct_ols_forecast` is not enough" in response.content
    assert "Do not import sklearn/statsmodels" in response.content
    assert "run_backtests=False" in response.content


def test_quant_middleware_allows_direct_ols_forecast_helper_call(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    unrate_path.write_text("date,value\n2024-01-01,3.9\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-helper-forecast",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import direct_ols_forecast\n"
                    "DATA_FILES = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    "}\n"
                    "forecast = direct_ols_forecast(\n"
                    "    forecast_frame,\n"
                    "    target_col='UNRATE',\n"
                    "    feature_cols=['spread'],\n"
                    "    date_col='date',\n"
                    "    horizon=6,\n"
                    ")\n"
                    "execution_summary = {**forecast}\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Updated file /tmp/outputs/job/code/analysis.py",
            name="write_file",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    assert response.status == "success"


def test_quant_middleware_allows_direct_forecast_statsmodels_method_note(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    unrate_path.write_text("date,value\n2024-01-01,3.9\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-helper-forecast-statsmodels-note",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import direct_ols_forecast, save_quant_outputs\n"
                    "DATA_FILES = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    "}\n"
                    "forecast_result = direct_ols_forecast(\n"
                    "    forecast_frame,\n"
                    "    target_col='UNRATE',\n"
                    "    feature_cols=['spread'],\n"
                    "    date_col='date',\n"
                    "    horizon=6,\n"
                    ")\n"
                    "execution_summary = {**forecast_result}\n"
                    "execution_summary.setdefault('method_notes', []).append('statsmodels_unavailable')\n"
                    "save_quant_outputs('/tmp/outputs/job', {}, execution_summary)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Updated file /tmp/outputs/job/code/analysis.py",
            name="write_file",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    assert response.status == "success"


def test_quant_middleware_allows_preserved_forecast_alias_handoff(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    unrate_path.write_text("date,value\n2024-01-01,3.9\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-helper-forecast-alias",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import direct_ols_forecast, save_quant_outputs\n"
                    "DATA_FILES = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    "}\n"
                    "fc = direct_ols_forecast(\n"
                    "    forecast_frame,\n"
                    "    target_col='UNRATE',\n"
                    "    feature_cols=['spread'],\n"
                    "    date_col='date',\n"
                    "    horizon=6,\n"
                    ")\n"
                    "exe = {**fc, 'methods_used': ['direct_ols_forecast']}\n"
                    "save_quant_outputs('/tmp/outputs/job', {}, exe)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Updated file /tmp/outputs/job/code/analysis.py",
            name="write_file",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    assert response.status == "success"


def test_quant_middleware_blocks_manual_forecast_loop_beside_direct_helper(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    unrate_path.write_text("date,value\n2024-01-01,3.9\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-helper-plus-sklearn-loop",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import direct_ols_forecast, save_quant_outputs\n"
                    "from sklearn.linear_model import LinearRegression\n"
                    "DATA_FILES = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    "}\n"
                    "forecast_result = direct_ols_forecast(\n"
                    "    forecast_frame,\n"
                    "    target_col='UNRATE',\n"
                    "    feature_cols=['spread'],\n"
                    "    date_col='date',\n"
                    "    horizon=6,\n"
                    ")\n"
                    "manual_model = LinearRegression().fit(X, y)\n"
                    "execution_summary = {**forecast_result, 'manual_model': str(manual_model)}\n"
                    "save_quant_outputs('/tmp/outputs/job', {}, execution_summary)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "manual sklearn/statsmodels forecast or replay loop" in response.content
    assert "signal_framework_backtest" in response.content


def test_quant_middleware_blocks_direct_forecast_without_validation_handoff(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    unrate_path.write_text("date,value\n2024-01-01,3.9\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-helper-forecast-stripped",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import direct_ols_forecast, save_quant_outputs\n"
                    "DATA_FILES = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    "}\n"
                    "forecast_result = direct_ols_forecast(\n"
                    "    forecast_frame,\n"
                    "    target_col='UNRATE',\n"
                    "    feature_cols=['spread'],\n"
                    "    date_col='date',\n"
                    "    horizon=6,\n"
                    ")\n"
                    "execution_summary = {\n"
                    "    'forecast_table': forecast_result['forecast_table'],\n"
                    "    'baseline_comparison': {'random_walk_rmse': 1.2},\n"
                    "    'statistical_summary': 'pseudo-OOS validation discussed in prose',\n"
                    "}\n"
                    "save_quant_outputs('/tmp/outputs/job', {}, execution_summary)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "does not preserve the helper's validation packet" in response.content
    assert "backtest_summary" in response.content
    assert "model_comparison" in response.content


def test_quant_middleware_blocks_looped_direct_forecast_without_backtest_skip(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    unrate_path.write_text("date,value\n2024-01-01,3.9\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-looped-helper-forecast",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import direct_ols_forecast\n"
                    "DATA_FILES = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    "}\n"
                    "rows = []\n"
                    "for cut in cut_dates:\n"
                    "    forecast = direct_ols_forecast(\n"
                    "        forecast_frame,\n"
                    "        target_col='UNRATE',\n"
                    "        feature_cols=['spread'],\n"
                    "        date_col='date',\n"
                    "        horizon=6,\n"
                    "    )\n"
                    "    rows.append(forecast['forecast_table'][-1])\n"
                    "current = direct_ols_forecast(\n"
                    "    forecast_frame,\n"
                    "    target_col='UNRATE',\n"
                    "    feature_cols=['spread'],\n"
                    "    date_col='date',\n"
                    "    horizon=6,\n"
                    ")\n"
                    "execution_summary = {**current, 'pseudo_oos_rows': rows}\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "inside a loop" in response.content
    assert "run_backtests=False" in response.content


def test_quant_middleware_allows_looped_direct_forecast_with_backtest_skip(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    unrate_path.write_text("date,value\n2024-01-01,3.9\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-looped-helper-forecast-skip",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import direct_ols_forecast\n"
                    "DATA_FILES = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    "}\n"
                    "rows = []\n"
                    "for cut in cut_dates:\n"
                    "    forecast = direct_ols_forecast(\n"
                    "        forecast_frame,\n"
                    "        target_col='UNRATE',\n"
                    "        feature_cols=['spread'],\n"
                    "        date_col='date',\n"
                    "        horizon=6,\n"
                    "        run_backtests=False,\n"
                    "    )\n"
                    "    rows.append(forecast['forecast_table'][-1])\n"
                    "current = direct_ols_forecast(\n"
                    "    forecast_frame,\n"
                    "    target_col='UNRATE',\n"
                    "    feature_cols=['spread'],\n"
                    "    date_col='date',\n"
                    "    horizon=6,\n"
                    ")\n"
                    "execution_summary = {**current, 'pseudo_oos_rows': rows}\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Updated file /tmp/outputs/job/code/analysis.py",
            name="write_file",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    assert response.status == "success"


def test_quant_middleware_blocks_syntax_invalid_analysis_before_write():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-bad-syntax",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": "result = {'chart_ids': ['a'\n",
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "syntax validation failed" in response.content
    assert "Rewrite a complete compact file" in response.content


def test_quant_middleware_blocks_positional_align_period_features_args():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-positional-align",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import align_period_features\n"
                    "series_frames = {}\n"
                    "panel = align_period_features(series_frames, 'M', 'outer', 'start')\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "accepts only `series_frames` as a positional argument" in response.content
    assert 'frequency="M"' in response.content


def test_quant_middleware_blocks_period_column_after_align_period_features():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-align-period-column",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import align_period_features\n"
                    "series_frames = {}\n"
                    "panel = align_period_features(series_frames, frequency='M')\n"
                    "forecast_frame = panel[['period', 'UNRATE']].dropna()\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "assigned from `align_period_features(...)`" in response.content
    assert "returns only `date` plus one column per series key" in response.content
    assert "use the returned `date` column" in response.content


def test_quant_middleware_blocks_resample_alias_in_to_period():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-bad-to-period",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "import pandas as pd\n"
                    "df = pd.DataFrame({'date': pd.to_datetime(['2026-01-01'])})\n"
                    "df['month'] = df['date'].dt.to_period('ME')\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.status == "error"
    assert "`to_period('ME')` uses a pandas resample alias" in response.content
    assert "`to_period('M')`" in response.content


def test_quant_middleware_allows_period_alias_in_to_period():
    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-good-to-period",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "import pandas as pd\n"
                    "df = pd.DataFrame({'date': pd.to_datetime(['2026-01-01'])})\n"
                    "df['month'] = df['date'].dt.to_period('M')\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Updated file /tmp/outputs/job/code/analysis.py",
            name="write_file",
            tool_call_id=req.tool_call["id"],
            status="success",
        ),
    )

    assert response.status == "success"


def test_quant_prompt_blocks_shell_csv_probe_loops():
    QUANT_DEVELOPER_SYSTEM_PROMPT = _quant_skill_text()
    assert "first tool call MUST be `write_file`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        "Do not call `ls`, `glob`, `read_file`, `execute`, or any other inspection tool before the initial script is written"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "Write the first script only to" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "code/analysis.py" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "regime_classification.py" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Trust the data-engineer schema/file-path handoff" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        "Treat the `data_files` map in the task description as the canonical manifest"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert 'DATA_FILES["UNRATE"]' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do not manually retype long auto-saved filenames" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "FileNotFoundError" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do not use `execute` for shell-based CSV inspection" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "head" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "tail" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "one-off pandas snippets" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        "Put all data loading, cleaning, latest-date checks, and validation inside `analysis.py`"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert (
        "Saved FRED CSVs may contain long quoted `notes` fields with embedded newlines"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert (
        'pd.read_csv(path, usecols=["date", "value"], parse_dates=["date"])'
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )


def test_quant_prompt_aligns_fred_thresholds_to_raw_units():
    QUANT_DEVELOPER_SYSTEM_PROMPT = _quant_skill_text()
    assert "FRED unit/threshold/display safety" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "`ICSA` and `IC4WSA`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "raw `Number` counts" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "ICSA_thousands = ICSA / 1000" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "300000" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "never emit labels such as `210750k`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "do not compare raw counts to abbreviated thresholds" in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_covers_pandas_scalar_date_safety():
    QUANT_DEVELOPER_SYSTEM_PROMPT = _quant_skill_text()
    assert "Pandas scalar date safety" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "numpy.datetime64" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "pd.Timestamp(value).date()" in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_requires_period_key_for_mixed_frequency_fred_merges():
    QUANT_DEVELOPER_SYSTEM_PROMPT = _quant_skill_text()
    assert "FRED frequency alignment" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        "daily or weekly FRED series such as Treasury yields or initial claims"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert 'date.dt.to_period("M")' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert 'quarter = date.dt.to_period("Q")' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Pandas Resampling vs Period Keys" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        "Use `'QE'` for quarterly and `'ME'` for monthly only with `.resample(...)`"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert 'Never call `.to_period("QE")` or `.to_period("ME")`' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "merge on `quarter`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        "quarter-start GDP dates directly against quarter-end resample timestamps"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert (
        "Do not merge month-end dates from resampling directly against month-start FRED dates"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "Mixed-frequency first draft requirement" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        "the initial `analysis.py` must use period-key merges from the start"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert (
        'align_period_features(series_frames, frequency="M", how="outer", timestamp_position="start", fill_method="ffill", fill_limit=2)'
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "quarterly Cartesian joins" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "exposes only `date` plus one column per series key" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert 'do not reference `panel["period"]` or `panel.period`' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert 'resample("ME").mean().to_frame()' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "mixed-frequency FRED merge produced no rows" in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_covers_derived_column_subset_ordering():
    QUANT_DEVELOPER_SYSTEM_PROMPT = _quant_skill_text()
    assert "Derived-column ordering" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "before taking filtered `.copy()` subsets" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "rebuild the subset or explicitly assign the column" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "trace which dataframe actually owns the missing column" in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_covers_pairwise_correlation_self_pair_safety():
    QUANT_DEVELOPER_SYSTEM_PROMPT = _quant_skill_text()
    assert "Pairwise correlation safety" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        "For simple cross-country or cross-series correlation matrices, prefer pandas directly"
        in (QUANT_DEVELOPER_SYSTEM_PROMPT)
    )
    assert "corr = numeric_frame.corr(min_periods=3).round(3).fillna(0)" in (
        QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "Only use `scipy.stats.pearsonr` when p-values are explicitly needed" in (
        QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "do not run `pearsonr` on self-pairs" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "duplicate column selections such as `pivot[[c1, c1]]`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "`valid[c1]` becomes a DataFrame instead of a Series" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Set self-correlations directly to `1.0`/`0.0`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "to_numpy(dtype=float)" in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_covers_fred_helper_and_json_serialization_safety():
    QUANT_DEVELOPER_SYSTEM_PROMPT = _quant_skill_text()
    assert "FRED helper consistency" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        'Do not write helpers that still reference `df["value"]`' in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "JSON serialization safety" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Use `save_quant_outputs` for final artifact writes" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "recursively converts pandas/numpy values" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "referenceLines" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "referenceAreas" in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_covers_pandas_chart_row_construction():
    QUANT_DEVELOPER_SYSTEM_PROMPT = _quant_skill_text()
    assert "Pandas chart-row construction" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "make the object a named Series before iteration" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert 'df["metric"].resample("QE").mean()' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "quarterly.items()" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        "Do not iterate over a single-column DataFrame with `iterrows()`"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert (
        "Use `.fillna(...)`, not nonexistent typo variants such as `.fillname(...)`"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )


def test_quant_prompt_points_macro_stats_to_deterministic_helper():
    QUANT_DEVELOPER_SYSTEM_PROMPT = _quant_skill_text()
    assert "agents/quant_macro_stats.py" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "rolling_correlation" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "lead_lag_correlations" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "recession_window_summary" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "ols_regression" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "direct_ols_forecast" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "align_period_features" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "build_composite_predictive_indicator" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "statsmodels_unavailable" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "forecast_table" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "attach_methods_used" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "methods_used" in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_requires_recession_window_helper_lookbacks():
    QUANT_DEVELOPER_SYSTEM_PROMPT = _quant_skill_text()
    assert "For recession-window prompts" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "MUST call `recession_window_summary(...)`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "`exact_lookbacks`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do not compute pre-recession values with `.tail(...)`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "exclude the start month to avoid lookahead" in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_keeps_scenario_triggers_in_structured_summary():
    QUANT_DEVELOPER_SYSTEM_PROMPT = _quant_skill_text()
    assert "If the user asks for scenario triggers" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert 'do not encode those as a chart with `type="table"`' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "helper-backed `scenario_table` rows" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "technical writer render the markdown table" in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_requires_composite_predictive_indicator_summary_keys():
    QUANT_DEVELOPER_SYSTEM_PROMPT = _quant_skill_text()
    assert "composite predictive indicator" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "MUST call `build_composite_predictive_indicator(...)`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "composite recession-risk indicator prompts" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert 'target_col="USREC"' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "prediction_horizon=1" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do not compute a second F1 grid search" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do not hand-roll full-sample z-scores" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert 'score_history[*]["composite_percentile_0_100"]' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "do not rescale `latest_index_value`, z-scores, or weighted sums yourself" in (
        QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "If one predictor starts much later than the rest" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "`feature_coverage`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Raise `ValueError` if any key is missing" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        "valid only if `analysis.py` validated the required predictive-indicator summary keys"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "predictive indicator" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "guaranteed forecast" in QUANT_DEVELOPER_SYSTEM_PROMPT
    for key in [
        "target",
        "prediction_horizon",
        "input_features",
        "feature_transforms",
        "normalization_method",
        "weights_or_model",
        "backtest_summary",
        "latest_index_value",
        "thresholds",
        "limitations",
    ]:
        assert key in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_requires_recession_regime_helper_summary_keys():
    QUANT_DEVELOPER_SYSTEM_PROMPT = _quant_skill_text()
    assert "recession/regime classification prompts" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        'align_period_features(series_frames, frequency="M", how="outer", timestamp_position="start", fill_method="ffill", fill_limit=2)'
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "MUST call `classify_recession_regime(...)`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        'classify_recession_regime(scored_frame, date_col="date", indicator_specs=indicator_specs, recession_col="USREC", momentum_periods=3, min_categories=3, analog_count=3)'
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert (
        "Do not hand-roll monthly/quarterly/daily resampling loops" in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert (
        "select the latest row that satisfies the helper's minimum category coverage"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "do not run post-success shell probes" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Use this canonical call shape without reading" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "weak_threshold" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "favorable_when" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        "weak_threshold` must always be numerically less than `strong_threshold"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert (
        'use `favorable_when="low"` to make lower raw values score stronger'
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "Do not hand-roll the regime label" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "methods_used` includes `recession_regime_classifier`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    for key in [
        "regime_label",
        "evidence_table",
        "historical_analogs",
        "false_positive_caveat",
        "category_scores",
        "missing_indicators",
        "methods_used",
    ]:
        assert key in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_forbids_runtime_installs_for_optional_statsmodels():
    QUANT_DEVELOPER_SYSTEM_PROMPT = _quant_skill_text()
    assert "No runtime package installation" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Never run `pip`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "`ensurepip`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "`get-pip.py`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Keep free/no-key constraints strict" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "optional `statsmodels` is unavailable" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "local helper's NumPy/SciPy fallback" in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_requires_canonical_econometrics_summary_keys():
    QUANT_DEVELOPER_SYSTEM_PROMPT = _quant_skill_text()
    assert "do not import `statsmodels` directly" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "do not import `sklearn.linear_model`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "hand-roll OLS/ARIMA forecast loops" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Importing `direct_ols_forecast` is not enough" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "do not read" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "rediscover helper signatures" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        'direct_ols_forecast(data, target_col, feature_cols, date_col="date", horizon=6'
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "run_backtests=False" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "recursive pseudo-OOS" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        "Forecast rows always include `date`, `forecast_period`, `forecast`, `lower`, and `upper`"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert 'Use `row["date"]` or `row["forecast_period"]`' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "`lower_80`/`upper_80`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "as top-level keys" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        "Do not rename them to `model_specification`, `estimation_period`"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    for key in [
        "model_spec",
        "estimation_window",
        "target_variable",
        "features",
        "diagnostics",
        "forecast_table",
        "method_notes",
    ]:
        assert key in QUANT_DEVELOPER_SYSTEM_PROMPT


def test_quant_prompt_gives_unemployment_forecast_helper_recipe():
    QUANT_DEVELOPER_SYSTEM_PROMPT = _quant_skill_text()
    assert "six-month unemployment forecast prompts" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "period-key alignment" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "dedicated `forecast_frame`" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do not pass a broad regime/consumer/international panel" in (
        QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "dropna(subset=[target_col, *feature_cols])" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert (
        'align_period_features(series_frames, frequency="M", how="outer", timestamp_position="start", fill_method="ffill", fill_limit=2)'
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert (
        "weekly claims or resampled month-end observations and month-start FRED macro series"
        in QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert 'target_col="UNRATE"' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert '"T10Y2Y", "ICSA", "PAYEMS_CHG", "INDPRO_CHG"' in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "Do not add a second manual OLS implementation" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "custom pseudo-OOS unemployment forecast charts" in QUANT_DEVELOPER_SYSTEM_PROMPT
    assert "where the model failed historically, prior false alarms, missed calls" in (
        QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "threshold=2, lookback_periods=12, false_alarm_lookahead_periods=12" in (
        QUANT_DEVELOPER_SYSTEM_PROMPT
    )
    assert "do not treat `direct_ols_forecast` as a substitute for hit/miss analysis" in (
        QUANT_DEVELOPER_SYSTEM_PROMPT
    )


def test_quant_middleware_does_not_treat_forecast_backtest_as_recession_risk(tmp_path):
    unrate_path = tmp_path / "fred_get_series_UNRATE.csv"
    usrec_path = tmp_path / "fred_get_series_USREC.csv"
    unrate_path.write_text("date,value\n2024-01-01,3.9\n", encoding="utf-8")
    usrec_path.write_text("date,value\n2024-01-01,0\n", encoding="utf-8")

    middleware = QuantDeveloperToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "write_file",
            "id": "call-forecast-backtest",
            "args": {
                "file_path": "/tmp/outputs/job/code/analysis.py",
                "content": (
                    "from agents.quant_macro_stats import direct_ols_forecast, save_quant_outputs\n"
                    "DATA_FILES = {\n"
                    f"    'UNRATE': {str(unrate_path)!r},\n"
                    f"    'USREC': {str(usrec_path)!r},\n"
                    "}\n"
                    "forecast = direct_ols_forecast(\n"
                    "    forecast_frame,\n"
                    "    target_col='UNRATE',\n"
                    "    feature_cols=['spread'],\n"
                    "    date_col='date',\n"
                    "    horizon=6,\n"
                    ")\n"
                    "execution_summary = {**forecast, 'status': 'ok'}\n"
                    "charts = {}\n"
                    "save_quant_outputs('/tmp/outputs/job', charts, execution_summary)\n"
                ),
            },
        },
        state={"messages": [AIMessage(content="starting")]},
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: ToolMessage(
            content="Updated file /tmp/outputs/job/code/analysis.py",
            tool_call_id="call-forecast-backtest",
        ),
    )

    assert response.status != "error"
    assert "recession-risk framework" not in response.content
