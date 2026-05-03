"""Deterministic intake routing heuristics."""
import re

_RESEARCH_QUERY_RE = re.compile(
    r"Research Query:\s*(?P<query>.*)", re.IGNORECASE | re.DOTALL
)
_FRED_MACRO_TERMS = (
    "macro",
    "economic",
    "economy",
    "consumer",
    "labor",
    "inflation",
    "recession",
)
_SCENARIO_DASHBOARD_TERMS = (
    "scenario",
    "scenarios",
    "stress",
    "dashboard",
)
_RESEARCH_ACTION_TERMS = (
    "analyze",
    "compare",
    "build",
    "investigate",
    "answer",
    "are ",
    "is ",
    "should ",
)


def _extract_research_query(text: str) -> str:
    """Extract the user-facing research query from the job envelope."""
    match = _RESEARCH_QUERY_RE.search(text)
    if match:
        return match.group("query").strip()
    return text.strip()


def _is_actionable_fred_macro_request(text: str) -> bool:
    """Return True when a broad FRED macro prompt is ready for analyst execution."""
    query = _extract_research_query(text)
    lowered = query.lower()
    if "fred" not in lowered:
        return False
    if not any(term in lowered for term in _FRED_MACRO_TERMS):
        return False
    if not any(term in lowered for term in _RESEARCH_ACTION_TERMS):
        return False
    return True


def _is_actionable_macro_scenario_request(text: str) -> bool:
    """Return True for broad macro scenario dashboards with analyst-selected inputs."""
    query = _extract_research_query(text)
    lowered = query.lower()
    if not any(term in lowered for term in _FRED_MACRO_TERMS):
        return False
    if not any(term in lowered for term in _SCENARIO_DASHBOARD_TERMS):
        return False
    if not any(term in lowered for term in _RESEARCH_ACTION_TERMS):
        return False
    if not {"base", "bull", "bear"}.issubset(set(re.findall(r"\b\w+\b", lowered))):
        return False
    return True


def _actionable_fred_macro_summary(text: str) -> str:
    query = _extract_research_query(text)
    return (
        "Use FRED macro data to answer the user's question, selecting appropriate "
        f"economic indicators and using the latest available observations: {query}"
    )


def _actionable_macro_scenario_summary(text: str) -> str:
    query = _extract_research_query(text)
    return (
        "Build the requested macro scenario dashboard using available free/local data, "
        "selecting appropriate recession-risk indicators and producing base, bull, "
        "and bear scenario rows with assumptions, trigger indicators, and "
        f"confidence/uncertainty notes: {query}"
    )

