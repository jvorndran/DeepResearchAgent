"""Shared data-provider toolbox metadata for routed research execution."""

from collections.abc import Iterable
from typing import Any, Literal

DATA_TOOLBOX_PREFERENCE_KEY = "data_toolbox"

ProviderName = Literal["fred", "bls", "bea", "census", "worldbank", "sec", "market"]

PROVIDER_ORDER: tuple[ProviderName, ...] = (
    "fred",
    "bls",
    "bea",
    "census",
    "worldbank",
    "sec",
    "market",
)

PROVIDER_LABELS: dict[str, str] = {
    "fred": "FRED",
    "bls": "BLS",
    "bea": "BEA",
    "census": "Census",
    "worldbank": "World Bank",
    "sec": "SEC EDGAR",
    "market": "Market valuation availability",
}

TOOLBOX_CONFIDENCE_FALLBACK_THRESHOLD = 0.55


def normalize_provider_list(providers: Iterable[Any] | None) -> list[ProviderName]:
    """Return valid provider names in canonical order, without duplicates."""
    requested = {str(provider).strip().lower() for provider in providers or []}
    return [provider for provider in PROVIDER_ORDER if provider in requested]


def make_data_toolbox(
    *,
    providers: Iterable[Any] | None,
    confidence: float,
    rationale: str,
    unavailable_needs: Iterable[Any] | None = None,
    fallback: bool = False,
) -> dict[str, Any]:
    """Build the normalized toolbox dict stored in graph state/runtime context."""
    needs = [str(need).strip() for need in unavailable_needs or [] if str(need).strip()]
    return {
        "providers": normalize_provider_list(providers),
        "confidence": float(confidence),
        "rationale": str(rationale).strip(),
        "unavailable_needs": needs,
        "fallback": bool(fallback),
    }


def broad_data_toolbox(
    rationale: str,
    *,
    confidence: float = 0.0,
    unavailable_needs: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Return the pre-router broad toolbox behavior: every public provider visible."""
    return make_data_toolbox(
        providers=PROVIDER_ORDER,
        confidence=confidence,
        rationale=rationale,
        unavailable_needs=unavailable_needs,
        fallback=True,
    )


def normalize_data_toolbox(
    toolbox: Any,
    *,
    broad_if_missing: bool = True,
) -> dict[str, Any] | None:
    """Normalize persisted toolbox metadata, preserving broad behavior for old state."""
    if toolbox is None:
        if broad_if_missing:
            return broad_data_toolbox("No routed toolbox was available; using all providers.")
        return None

    if isinstance(toolbox, dict):
        providers = normalize_provider_list(toolbox.get("providers"))
        if not providers:
            return broad_data_toolbox(
                "Routed toolbox had no valid providers; using all providers.",
                confidence=float(toolbox.get("confidence") or 0.0),
                unavailable_needs=toolbox.get("unavailable_needs") or [],
            )
        return make_data_toolbox(
            providers=providers,
            confidence=float(toolbox.get("confidence") or 0.0),
            rationale=str(toolbox.get("rationale") or "").strip(),
            unavailable_needs=toolbox.get("unavailable_needs") or [],
            fallback=bool(toolbox.get("fallback", False)),
        )

    if isinstance(toolbox, (list, tuple, set)):
        providers = normalize_provider_list(toolbox)
        if providers:
            return make_data_toolbox(
                providers=providers,
                confidence=1.0,
                rationale="Provider list supplied directly.",
            )

    if broad_if_missing:
        return broad_data_toolbox("Malformed routed toolbox; using all providers.")
    return None


def format_data_toolbox_for_prompt(toolbox: Any) -> str:
    """Compact one-line provider metadata for execution kickoff prompts."""
    normalized = normalize_data_toolbox(toolbox)
    assert normalized is not None
    providers = normalized["providers"]
    labels = ", ".join(f"{PROVIDER_LABELS[p]} (`{p}`)" for p in providers)
    prefix = "Selected data providers for `data-engineer`"
    if normalized.get("fallback"):
        return f"{prefix}: {labels}. Router fallback kept the broad public-data toolbox."
    return f"{prefix}: {labels}."
