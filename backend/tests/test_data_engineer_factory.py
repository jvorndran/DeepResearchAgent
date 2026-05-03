from types import SimpleNamespace

import pytest
from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage

from agents.data_engineer.factory import (
    DataEngineerToolBoundaryMiddleware,
    FredMCPRequiredError,
    _DATA_ENGINEER_TOOL_BOUNDARY_MIDDLEWARE,
    _build_data_engineer_runnable,
    _probe_required_fred_tool,
)


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
    def __init__(self, tools):
        self.tools = tools

    def override(self, **kwargs):
        return FakeRequest(kwargs.get("tools", self.tools))


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


def test_data_engineer_runnable_uses_only_data_tools(monkeypatch):
    captured = {}

    class FakeAgent:
        def invoke(self, state):
            return state

        async def ainvoke(self, state):
            return state

    def fake_create_agent(model, *, system_prompt, tools, middleware, name):
        captured.update(
            {
                "model": model,
                "system_prompt": system_prompt,
                "tools": tools,
                "middleware": middleware,
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
    assert "Census public data" in captured["system_prompt"]
    assert "World Bank annual indicators" in captured["system_prompt"]


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
async def test_fred_health_probe_raises_when_all_probe_series_fail():
    tool = FakeFredGetSeriesTool(
        {
            "GDP": RuntimeError("FRED API error (500)"),
            "UNRATE": RuntimeError("fetch failed"),
        }
    )

    with pytest.raises(FredMCPRequiredError) as exc_info:
        await _probe_required_fred_tool(tool)

    message = str(exc_info.value)
    assert "health probes failed" in message
    assert "GDP:" in message
    assert "UNRATE:" in message
