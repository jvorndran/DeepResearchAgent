"""LLM-routed data-provider toolbox selection for the orchestrator."""

import logging
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..data_toolbox import (
    PROVIDER_ORDER,
    ProviderName,
    TOOLBOX_CONFIDENCE_FALLBACK_THRESHOLD,
    broad_data_toolbox,
    format_data_toolbox_for_prompt,
    make_data_toolbox,
    normalize_data_toolbox,
)

logger = logging.getLogger(__name__)

_TOOLBOX_ROUTER_MODEL = "deepseek:deepseek-chat"


class ToolboxRoute(BaseModel):
    """Structured LLM output for data-provider routing."""

    providers: list[ProviderName] = Field(
        default_factory=list,
        description="Relevant data providers from: fred, bls, bea, census, worldbank, sec.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence that the provider set covers the approved query.",
    )
    rationale: str = Field(
        description="Brief reason for the selected provider set.",
    )
    unavailable_needs: list[str] = Field(
        default_factory=list,
        description="Requested data needs not covered by the available provider set.",
    )


TOOLBOX_ROUTER_PROMPT = """\
You are a deterministic toolbox router for a financial research pipeline.
Choose only the data-provider toolboxes that are relevant to the approved query.

Valid providers:
- `fred`: US macro time series, rates, inflation, labor-market aggregates,
  recession indicators, credit, production, consumption, housing, sentiment.
- `bls`: direct BLS source checks for labor, wages, CPI/PPI, payrolls,
  productivity, and employment series when the query asks for source fidelity.
- `bea`: BEA national accounts: GDP, real GDP, personal income, PCE,
  corporate profits, and other NIPA table evidence.
- `census`: US state/county demographics, income, population, housing, and
  regional context.
- `worldbank`: cross-country annual macro comparisons such as inflation or GDP
  growth outside the US.
- `sec`: public-company fundamentals and filing facts: revenue, net income,
  margins, cash flow, balance sheet, shares, R&D, SG&A, EPS, 10-K/10-Q metadata.

Routing examples:
- Microsoft/company fundamentals, revenue, margins, cash flow, earnings risk,
  or balance-sheet questions -> `sec`, not `fred`.
- Microsoft fundamentals plus inflation/rates sensitivity -> `sec` and `fred`.
- Macro rates, inflation, labor, credit, recession, NBER windows -> `fred`.
- GDP, GDI, income, consumption/PCE, or corporate-profits national-account
  evidence -> `bea`; add `fred` only when broader macro time-series context is
  also needed.
- Consumer stress by state or regional consumer context -> `fred` and `census`.
- Cross-country inflation or GDP-growth comparisons -> `fred` and `worldbank`.
- Direct BLS validation of payrolls, CPI, wages, or employment -> `bls` plus any
  broader macro provider needed by the query.

Return the smallest provider set that covers the query. If no provider is
clearly relevant, return an empty provider list with low confidence.
"""


def _selection_from_route(route: ToolboxRoute) -> dict[str, Any]:
    """Normalize LLM output, falling back to the broad toolbox when uncertain."""
    if not route.providers or route.confidence < TOOLBOX_CONFIDENCE_FALLBACK_THRESHOLD:
        return broad_data_toolbox(
            ("Toolbox router was low confidence or selected no providers; " "using all providers."),
            confidence=route.confidence,
            unavailable_needs=route.unavailable_needs,
        )
    return make_data_toolbox(
        providers=route.providers,
        confidence=route.confidence,
        rationale=route.rationale,
        unavailable_needs=route.unavailable_needs,
    )


def _message_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("content") or ""))
            else:
                parts.append(str(part))
        return "".join(parts)
    return str(content)


def _latest_approved_user_request(state: dict) -> str:
    for message in reversed(state.get("messages") or []):
        if not isinstance(message, HumanMessage):
            continue
        text = _message_content_text(message.content).strip()
        if not text:
            continue
        marker = "Research Query:"
        marker_index = text.lower().rfind(marker.lower())
        return text[marker_index + len(marker) :].strip() if marker_index >= 0 else text
    return ""


def _router_input_text(state: dict) -> str:
    approved_request = _latest_approved_user_request(state)
    research_summary = str(state.get("research_summary") or "").strip()
    if approved_request and research_summary:
        return f"Research summary: {research_summary}\nFull approved request: {approved_request}"
    if approved_request:
        return f"Full approved request: {approved_request}"
    if research_summary:
        return f"Research summary: {research_summary}"
    return "No approved request text was available."


async def route_toolbox_node(state: dict) -> dict[str, Any]:
    """Select provider toolboxes after intake completion and before approval."""
    try:
        llm = init_chat_model(_TOOLBOX_ROUTER_MODEL).with_structured_output(ToolboxRoute)
        route: ToolboxRoute = await llm.ainvoke(
            [
                SystemMessage(content=TOOLBOX_ROUTER_PROMPT),
                HumanMessage(content=_router_input_text(state)),
            ]
        )
        selection = _selection_from_route(route)
    except Exception as e:
        logger.warning("Toolbox router failed; falling back to broad toolbox: %s", e)
        selection = broad_data_toolbox(
            "Toolbox router failed; using all providers.",
            unavailable_needs=[f"router_error: {type(e).__name__}"],
        )

    logger.info(
        "Toolbox route providers=%s fallback=%s confidence=%s",
        selection.get("providers", PROVIDER_ORDER),
        selection.get("fallback"),
        selection.get("confidence"),
    )
    return {"data_toolbox": selection}


__all__ = [
    "TOOLBOX_ROUTER_PROMPT",
    "ToolboxRoute",
    "format_data_toolbox_for_prompt",
    "normalize_data_toolbox",
    "route_toolbox_node",
]
