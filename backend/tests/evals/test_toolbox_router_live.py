"""Opt-in live evals for the LLM toolbox router.

These are intentionally not full graph tests. They call ``route_toolbox_node``
with a minimal post-intake state and assert the exact ``data_toolbox`` payload
that would flow into ``emit_approval_message`` / ``prepare_execution``.

Prompts should read like user research questions, not provider-routing hints.
Some cases allow multiple defensible provider sets because the router is an LLM
and because adjacent data needs can reasonably be scoped in or out.
"""

import os
from dataclasses import dataclass

import pytest
from langchain_core.messages import HumanMessage

from agents.orchestrator.toolbox_router import route_toolbox_node

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TOOLBOX_ROUTER_EVALS") != "1",
    reason="live toolbox-router evals require RUN_LIVE_TOOLBOX_ROUTER_EVALS=1",
)


@dataclass(frozen=True)
class RouterEvalCase:
    name: str
    prompt: str
    acceptable_provider_sets: tuple[frozenset[str], ...]


def _sets(*provider_sets: set[str]) -> tuple[frozenset[str], ...]:
    return tuple(frozenset(provider_set) for provider_set in provider_sets)


def _max_attempts() -> int:
    raw = os.getenv("RUN_LIVE_TOOLBOX_ROUTER_EVAL_ATTEMPTS", "3")
    try:
        return max(1, int(raw))
    except ValueError:
        return 3


EVAL_CASES = [
    RouterEvalCase(
        name="microsoft_business_quality",
        prompt=(
            "I need a short investment-committee view on whether Microsoft's business "
            "quality has actually improved over the last few years. Focus on sales "
            "durability, profitability, cash generation, reinvestment, dilution, and "
            "balance-sheet risk."
        ),
        acceptable_provider_sets=_sets({"sec"}),
    ),
    RouterEvalCase(
        name="software_margin_pressure",
        prompt=(
            "Pressure-test a large software company's margins if financing costs stay "
            "high and customers keep pushing back on price increases. Use Microsoft as "
            "the example company and ground the answer in recent financials."
        ),
        acceptable_provider_sets=_sets({"sec", "fred"}),
    ),
    RouterEvalCase(
        name="household_stress_regional",
        prompt=(
            "Are household balance sheets starting to crack, or is the weakness mostly "
            "concentrated in certain parts of the country? I want national evidence and "
            "enough regional context to avoid treating every state the same."
        ),
        acceptable_provider_sets=_sets({"fred", "census"}, {"fred", "bls", "census"}),
    ),
    RouterEvalCase(
        name="inflation_global_context",
        prompt=(
            "Put the US inflation story in context against a few other developed and "
            "nearshore economies. I care about whether the US is uniquely sticky or "
            "just moving with the global cycle."
        ),
        acceptable_provider_sets=_sets({"fred", "worldbank"}, {"worldbank"}),
    ),
    RouterEvalCase(
        name="jobs_data_trust_check",
        prompt=(
            "Labor headlines look noisy. Sanity-check whether the jobs market is really "
            "cooling or whether revisions and survey differences are exaggerating the "
            "slowdown."
        ),
        acceptable_provider_sets=_sets({"fred", "bls"}, {"bls"}),
    ),
    RouterEvalCase(
        name="recession_risk_market_committee",
        prompt=(
            "Prepare a recession-risk dashboard for a portfolio review. The committee "
            "cares about growth, labor, inflation, credit, policy rates, and whether "
            "the signal has worked around prior downturns."
        ),
        acceptable_provider_sets=_sets({"fred"}),
    ),
    RouterEvalCase(
        name="apple_vs_microsoft_earnings_resilience",
        prompt=(
            "Compare Apple and Microsoft on earnings resilience. I want to know which "
            "one has the cleaner revenue mix, margin trajectory, cash conversion, and "
            "balance-sheet flexibility if demand softens."
        ),
        acceptable_provider_sets=_sets({"sec"}),
    ),
]


def _state_for_prompt(prompt: str) -> dict:
    return {
        "research_summary": prompt,
        "messages": [
            HumanMessage(
                content=("Job ID: live-toolbox-router-eval\n\n" f"Research Query: {prompt}")
            )
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("case", EVAL_CASES, ids=[case.name for case in EVAL_CASES])
async def test_live_toolbox_router_selects_expected_providers(case: RouterEvalCase):
    attempts = []
    for attempt in range(1, _max_attempts() + 1):
        result = await route_toolbox_node(_state_for_prompt(case.prompt))
        toolbox = result["data_toolbox"]
        actual_providers = frozenset(toolbox["providers"])
        attempt_payload = {
            "attempt": attempt,
            "case": case.name,
            "acceptable": [sorted(providers) for providers in case.acceptable_provider_sets],
            "actual": sorted(actual_providers),
            "confidence": toolbox["confidence"],
            "fallback": toolbox["fallback"],
            "rationale": toolbox["rationale"],
            "unavailable_needs": toolbox["unavailable_needs"],
        }
        attempts.append(attempt_payload)
        print(attempt_payload)

        if not toolbox["fallback"] and actual_providers in case.acceptable_provider_sets:
            return

    pytest.fail(f"Toolbox router never selected an acceptable provider set: {attempts}")
