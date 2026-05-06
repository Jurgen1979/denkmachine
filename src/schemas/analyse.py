"""pydantic-modellen voor de analyse-pipeline (critique, redo-beslissing)."""

from typing import Literal

from pydantic import BaseModel, Field


class CritiqueResult(BaseModel):
    """resultaat van één critique-rol na beoordeling van de analyst-output."""

    needs_redo: bool
    weak_sections: list[str] = Field(default_factory=list)
    general_feedback: str
    section_feedback: dict[str, str] = Field(default_factory=dict)
    severity: Literal["low", "medium", "high"]
