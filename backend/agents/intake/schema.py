"""Structured intake evaluation schema."""
from pydantic import BaseModel, Field

# Structured output schema for the evaluate gate
# ---------------------------------------------------------------------------

class IntakeEvaluation(BaseModel):
    """Structured evaluation of whether intake is complete."""

    complete: bool = Field(
        description="True if the user has provided enough information to begin research"
    )
    summary: str = Field(
        description=(
            "One-sentence summary of the research to be conducted. "
            "Write this even if complete is False (best-effort so far)."
        )
    )
    missing: list[str] = Field(
        default_factory=list,
        description="List of missing pieces of information. Empty when complete is True.",
    )

