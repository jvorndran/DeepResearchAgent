from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, SystemMessage

from core.context import ResearchContext
from agents.data_engineer.factory import (
    DataEngineerToolBoundaryMiddleware,
    FredMCPRequiredError,
    _DATA_ENGINEER_TOOL_BOUNDARY_MIDDLEWARE,
    _build_data_engineer_runnable,
    _probe_required_fred_tool,
)
from agents.data_engineer.prompts import DATA_ENGINEER_CORE_PROMPT


class FakeFredGetSeriesTool:
    name = "fred_get_series"

    def __init__(self, failures: dict[str, Exception]):
        self.failures = failures
        self.calls: list[str] = []
        self.payloads: list[dict] = []

    async def ainvoke(self, payload):
        series_id = payload["series_id"]
        self.calls.append(series_id)
        self.payloads.append(payload)
        if series_id in self.failures:
            raise self.failures[series_id]
        return {"series_id": series_id, "data": [{"date": "2024-01-01", "value": "1"}]}


class FakeRequest:
    def __init__(self, tools, runtime=None, system_message=None):
        self.tools = tools
        self.runtime = runtime
        self.system_message = system_message or SystemMessage(content=DATA_ENGINEER_CORE_PROMPT)

    def override(self, **kwargs):
        return FakeRequest(
            kwargs.get("tools", self.tools),
            runtime=self.runtime,
            system_message=kwargs.get("system_message", self.system_message),
        )


def _runtime_with_toolbox(providers):
    return SimpleNamespace(
        context=ResearchContext(
            job_id="job-toolbox",
            preferences={
                "data_toolbox": {
                    "providers": providers,
                    "confidence": 0.9,
                    "rationale": "test route",
                    "unavailable_needs": [],
                    "fallback": False,
                }
            },
        )
    )


def test_data_engineer_tool_boundary_hides_filesystem_and_shell_tools():
    middleware = DataEngineerToolBoundaryMiddleware()
    request = FakeRequest(
        [
            {"name": "fred_get_series"},
            {"name": "save_data"},
            {"name": "execute"},
            {"name": "read_file"},
            {"name": "write_file"},
            {"name": "ls"},
            {"function": {"name": "extract_schema"}},
        ]
    )

    seen_tool_names = []

    def handler(filtered_request):
        seen_tool_names.extend(
            tool.get("name") or tool.get("function", {}).get("name")
            for tool in filtered_request.tools
        )
        return ModelResponse(result=[AIMessage(content="ok")])

    middleware.wrap_model_call(request=request, handler=handler)

    assert seen_tool_names == ["fred_get_series", "save_data", "extract_schema"]


def test_data_engineer_tool_boundary_uses_selection_for_tools_and_prompt_sections():
    middleware = DataEngineerToolBoundaryMiddleware()
    request = FakeRequest(
        [
            {"name": "save_data"},
            {"name": "extract_schema"},
            {"name": "fred_get_series"},
            {"name": "bls_get_series"},
            {"name": "census_get_table"},
            {"name": "worldbank_get_indicator"},
            {"name": "sec_fetch_company_facts"},
        ],
        runtime=_runtime_with_toolbox(["sec"]),
    )

    seen_tool_names = []
    seen_prompt = ""

    def handler(filtered_request):
        nonlocal seen_prompt
        seen_tool_names.extend(tool.get("name") for tool in filtered_request.tools)
        seen_prompt = filtered_request.system_message.content
        return ModelResponse(result=[AIMessage(content="ok")])

    middleware.wrap_model_call(request=request, handler=handler)

    assert seen_tool_names == [
        "save_data",
        "extract_schema",
        "sec_fetch_company_facts",
    ]
    assert "SEC COMPANY FACTS" in seen_prompt
    assert "Common consumer-stress IDs" not in seen_prompt
    assert "BLS DIRECT SOURCE CHECKS" not in seen_prompt
    assert "CENSUS REGIONAL CONTEXT" not in seen_prompt
    assert "WORLD BANK CROSS-COUNTRY MACRO" not in seen_prompt


def test_data_engineer_tool_boundary_pairs_selected_tools_with_selected_sections():
    middleware = DataEngineerToolBoundaryMiddleware()
    request = FakeRequest(
        [
            {"name": "save_data"},
            {"name": "extract_schema"},
            {"name": "fred_search"},
            {"name": "fred_get_series"},
            {"name": "bls_get_series"},
            {"name": "census_get_table"},
            {"name": "worldbank_get_indicator"},
            {"name": "sec_fetch_company_facts"},
        ],
        runtime=_runtime_with_toolbox(["fred", "census"]),
    )

    seen_tool_names = []
    seen_prompt = ""

    def handler(filtered_request):
        nonlocal seen_prompt
        seen_tool_names.extend(tool.get("name") for tool in filtered_request.tools)
        seen_prompt = filtered_request.system_message.content
        return ModelResponse(result=[AIMessage(content="ok")])

    middleware.wrap_model_call(request=request, handler=handler)

    assert seen_tool_names == [
        "save_data",
        "extract_schema",
        "fred_search",
        "fred_get_series",
        "census_get_table",
    ]
    assert "FRED PROVIDER RULES" in seen_prompt
    assert "CENSUS PROVIDER RULES" in seen_prompt
    assert "BLS PROVIDER RULES" not in seen_prompt
    assert "WORLD BANK PROVIDER RULES" not in seen_prompt
    assert "SEC PROVIDER RULES" not in seen_prompt


def test_data_engineer_tool_boundary_exposes_fred_for_macro_context():
    middleware = DataEngineerToolBoundaryMiddleware()
    request = FakeRequest(
        [
            {"name": "save_data"},
            {"name": "extract_schema"},
            {"name": "fred_search"},
            {"name": "fred_browse"},
            {"name": "fred_get_series"},
            {"name": "sec_fetch_company_facts"},
        ],
        runtime=_runtime_with_toolbox(["fred"]),
    )

    seen_tool_names = []

    def handler(filtered_request):
        seen_tool_names.extend(tool.get("name") for tool in filtered_request.tools)
        return ModelResponse(result=[AIMessage(content="ok")])

    middleware.wrap_model_call(request=request, handler=handler)

    assert seen_tool_names == [
        "save_data",
        "extract_schema",
        "fred_search",
        "fred_browse",
        "fred_get_series",
    ]


def test_data_engineer_tool_boundary_broad_fallback_includes_all_provider_tools_and_sections():
    middleware = DataEngineerToolBoundaryMiddleware()
    request = FakeRequest(
        [
            {"name": "save_data"},
            {"name": "extract_schema"},
            {"name": "fred_get_series"},
            {"name": "bls_get_series"},
            {"name": "census_get_table"},
            {"name": "worldbank_get_indicator"},
            {"name": "sec_fetch_company_facts"},
        ]
    )

    seen_tool_names = []
    seen_prompt = ""

    def handler(filtered_request):
        nonlocal seen_prompt
        seen_tool_names.extend(tool.get("name") for tool in filtered_request.tools)
        seen_prompt = filtered_request.system_message.content
        return ModelResponse(result=[AIMessage(content="ok")])

    middleware.wrap_model_call(request=request, handler=handler)

    assert seen_tool_names == [
        "save_data",
        "extract_schema",
        "fred_get_series",
        "bls_get_series",
        "census_get_table",
        "worldbank_get_indicator",
        "sec_fetch_company_facts",
    ]
    assert "FRED PROVIDER RULES" in seen_prompt
    assert "BLS DIRECT SOURCE CHECKS" in seen_prompt
    assert "CENSUS REGIONAL CONTEXT" in seen_prompt
    assert "WORLD BANK CROSS-COUNTRY MACRO" in seen_prompt
    assert "SEC COMPANY FACTS" in seen_prompt


def test_data_engineer_tool_boundary_blocks_inherited_filesystem_tool_calls():
    middleware = DataEngineerToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "execute",
            "id": "call-1",
            "args": {"command": "cp /tmp/source.csv /tmp/target.csv"},
        }
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-1"
    assert response.status == "error"
    assert "Blocked tool `execute`" in response.content
    assert "return those paths directly" in response.content


def test_data_engineer_tool_boundary_blocks_unselected_provider_tool_calls():
    middleware = DataEngineerToolBoundaryMiddleware()
    request = SimpleNamespace(
        tool_call={
            "name": "fred_get_series",
            "id": "call-provider",
            "args": {"series_id": "GDP"},
        },
        runtime=_runtime_with_toolbox(["sec"]),
    )

    response = middleware.wrap_tool_call(
        request,
        lambda req: (_ for _ in ()).throw(AssertionError("handler should not run")),
    )

    assert response.tool_call_id == "call-provider"
    assert response.status == "error"
    assert "Blocked tool `fred_get_series`" in response.content
    assert "SEC EDGAR (`sec`)" in response.content


def test_data_engineer_runnable_uses_only_data_tools(monkeypatch):
    captured = {}

    class FakeAgent:
        def invoke(self, state):
            return state

        async def ainvoke(self, state):
            return state

    def fake_create_agent(model, *, system_prompt, tools, middleware, context_schema, name):
        captured.update(
            {
                "model": model,
                "system_prompt": system_prompt,
                "tools": tools,
                "middleware": middleware,
                "context_schema": context_schema,
                "name": name,
            }
        )
        return FakeAgent()

    monkeypatch.setattr("agents.data_engineer.factory.create_agent", fake_create_agent)
    fred_tool = SimpleNamespace(name="fred_get_series")

    runnable = _build_data_engineer_runnable([fred_tool])

    assert runnable.name == "data-engineer"
    assert captured["model"] == "deepseek:deepseek-chat"
    assert captured["name"] == "data-engineer"
    assert captured["context_schema"] is ResearchContext
    assert _DATA_ENGINEER_TOOL_BOUNDARY_MIDDLEWARE in captured["middleware"]
    assert [getattr(tool, "name", None) for tool in captured["tools"]] == [
        "save_data",
        "extract_schema",
        "bls_search_known_series",
        "bls_get_series",
        "census_get_table",
        "worldbank_get_indicator",
        "sec_fetch_company_facts",
        "fred_get_series",
    ]
    assert "Filesystem and shell tools are blocked" in captured["system_prompt"]
    assert captured["system_prompt"] == DATA_ENGINEER_CORE_PROMPT
    assert "CENSUS REGIONAL CONTEXT" not in captured["system_prompt"]
    assert "WORLD BANK CROSS-COUNTRY MACRO" not in captured["system_prompt"]


@pytest.mark.asyncio
async def test_fred_health_probe_tries_fallback_series_after_gdp_failure():
    tool = FakeFredGetSeriesTool({"GDP": RuntimeError("FRED API error (500)")})

    await _probe_required_fred_tool(tool)

    assert tool.calls == ["GDP", "UNRATE"]
    assert tool.payloads == [
        {"series_id": "GDP", "limit": 1, "sort_order": "desc"},
        {"series_id": "UNRATE", "limit": 1, "sort_order": "desc"},
    ]


@pytest.mark.asyncio
async def test_fred_health_probe_tries_chart_relevant_fallback_series():
    tool = FakeFredGetSeriesTool(
        {
            "GDP": RuntimeError("FRED API error (500)"),
            "UNRATE": RuntimeError("FRED API error (500)"),
        }
    )

    await _probe_required_fred_tool(tool)

    assert tool.calls == ["GDP", "UNRATE", "CPIAUCSL"]
    assert tool.payloads[-1] == {
        "series_id": "CPIAUCSL",
        "limit": 1,
        "sort_order": "desc",
    }


@pytest.mark.asyncio
async def test_fred_health_probe_raises_when_all_probe_series_fail():
    tool = FakeFredGetSeriesTool(
        {
            "GDP": RuntimeError("FRED API error (500)"),
            "UNRATE": RuntimeError("fetch failed"),
            "CPIAUCSL": RuntimeError("FRED API error (500)"),
            "CPILFESL": RuntimeError("FRED API error (500)"),
            "FEDFUNDS": RuntimeError("FRED API error (500)"),
            "USREC": RuntimeError("FRED API error (500)"),
        }
    )

    with pytest.raises(FredMCPRequiredError) as exc_info:
        await _probe_required_fred_tool(tool)

    message = str(exc_info.value)
    assert "health probes failed" in message
    assert "GDP:" in message
    assert "UNRATE:" in message
    assert "CPIAUCSL:" in message
    assert "FEDFUNDS:" in message
