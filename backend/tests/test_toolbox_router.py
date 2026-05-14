import pytest
from langchain_core.messages import HumanMessage

from agents.orchestrator import toolbox_router
from agents.orchestrator.toolbox_router import ToolboxRoute, route_toolbox_node


class FakeStructuredModel:
    def __init__(self, route):
        self.route = route
        self.messages = None

    async def ainvoke(self, messages):
        self.messages = messages
        return self.route


class FakeChatModel:
    def __init__(self, route):
        self.structured = FakeStructuredModel(route)
        self.schema = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self.structured


def _state(query: str) -> dict:
    return {
        "research_summary": query,
        "messages": [HumanMessage(content=f"Job ID: job-router\n\nResearch Query: {query}")],
    }


async def _route(monkeypatch, providers, confidence=0.9, rationale="test route"):
    fake = FakeChatModel(
        ToolboxRoute(
            providers=providers,
            confidence=confidence,
            rationale=rationale,
            unavailable_needs=[],
        )
    )
    monkeypatch.setattr(toolbox_router, "init_chat_model", lambda _model: fake)
    result = await route_toolbox_node(_state(rationale))
    return result["data_toolbox"], fake


@pytest.mark.asyncio
async def test_toolbox_router_selects_sec_for_microsoft_fundamentals(monkeypatch):
    toolbox, fake = await _route(
        monkeypatch,
        ["sec"],
        rationale="Analyze Microsoft revenue, margins, and cash flow.",
    )

    assert fake.schema is ToolboxRoute
    assert toolbox["providers"] == ["sec"]
    assert toolbox["fallback"] is False


@pytest.mark.asyncio
async def test_toolbox_router_selects_sec_and_fred_for_company_macro_sensitivity(monkeypatch):
    toolbox, _fake = await _route(
        monkeypatch,
        ["fred", "sec"],
        rationale="Analyze Microsoft fundamentals and sensitivity to rates and inflation.",
    )

    assert toolbox["providers"] == ["fred", "sec"]
    assert toolbox["fallback"] is False


@pytest.mark.asyncio
async def test_toolbox_router_selects_fred_and_census_for_consumer_stress_by_state(
    monkeypatch,
):
    toolbox, _fake = await _route(
        monkeypatch,
        ["fred", "census"],
        rationale="Assess consumer stress nationally and by state.",
    )

    assert toolbox["providers"] == ["fred", "census"]


@pytest.mark.asyncio
async def test_toolbox_router_selects_fred_and_worldbank_for_cross_country_inflation(
    monkeypatch,
):
    toolbox, _fake = await _route(
        monkeypatch,
        ["fred", "worldbank"],
        rationale="Compare inflation in the US, Canada, Germany, and Japan.",
    )

    assert toolbox["providers"] == ["fred", "worldbank"]


@pytest.mark.asyncio
async def test_toolbox_router_low_confidence_empty_output_falls_back_to_broad_toolbox(
    monkeypatch,
):
    toolbox, _fake = await _route(
        monkeypatch,
        [],
        confidence=0.2,
        rationale="Ambiguous request.",
    )

    assert toolbox["providers"] == ["fred", "bls", "census", "worldbank", "sec"]
    assert toolbox["fallback"] is True
    assert "low confidence" in toolbox["rationale"].lower()
