"""pydantic-modellen voor het ontleder- en intake-plan."""

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from src.utils import load_yaml

_BASE_DIR = Path(__file__).parent.parent.parent
_valid_categories: set[str] | None = None
_valid_output_types: set[str] | None = None


def _get_valid_categories() -> set[str]:
    """Laad geldige categorienamen uit categories.yaml (gecached)."""
    global _valid_categories
    if _valid_categories is None:
        data = load_yaml(str(_BASE_DIR / "config" / "categories.yaml"))
        _valid_categories = set(data.get("categories", {}).keys())
    return _valid_categories


def _get_valid_output_types() -> set[str]:
    """Laad geldige output-types uit output_types.yaml (gecached)."""
    global _valid_output_types
    if _valid_output_types is None:
        data = load_yaml(str(_BASE_DIR / "config" / "output_types.yaml"))
        _valid_output_types = set(data.get("output_types", {}).keys())
    return _valid_output_types


class SourceToResearch(BaseModel):
    """een enkele bron om te onderzoeken."""

    type: str
    value: str
    rationale: str


class ReportSection(BaseModel):
    """een sectie in het eindrapport."""

    id: str
    title: str
    purpose: str
    estimated_length_words: int


class ResearchPlan(BaseModel):
    """het onderzoeksplan voor een project."""

    interview_questions: list[str]
    sources_to_research: list[SourceToResearch]
    frameworks_to_apply: list[str]
    report_sections: list[ReportSection]


class RolePack(BaseModel):
    """het actieve rolpakket voor een project."""

    analyst_roles: list[str]
    critique_roles: list[str]


class Plan(BaseModel):
    """het volledige plan zoals geproduceerd door de ontleder."""

    primary_category: str
    secondary_category: Optional[str] = None
    category_confidence: float = Field(..., ge=0.0, le=1.0)
    interpreted_goal: str
    scope: str
    scope_clarity_score: float = Field(..., ge=0.0, le=1.0)
    assumptions: list[str]
    missing_inputs: list[str]
    clarifying_questions: list[str]
    active_role_pack: RolePack
    research_plan: ResearchPlan
    output_type: str
    estimated_runtime_minutes: float
    estimated_cost_eur: float

    @field_validator("primary_category")
    @classmethod
    def primary_category_must_exist(cls, v: str) -> str:
        """Controleer dat de primaire categorie bestaat in categories.yaml."""
        valid = _get_valid_categories()
        if v not in valid:
            raise ValueError(f"onbekende categorie: {v}. geldig: {sorted(valid)}")
        return v

    @field_validator("output_type")
    @classmethod
    def output_type_must_exist(cls, v: str) -> str:
        """Controleer dat het output-type bestaat in output_types.yaml."""
        valid = _get_valid_output_types()
        if v not in valid:
            raise ValueError(f"onbekend output_type: {v}. geldig: {sorted(valid)}")
        return v

    @field_validator("clarifying_questions")
    @classmethod
    def max_three_questions(cls, v: list[str]) -> list[str]:
        """Maximaal 3 clarifying questions."""
        if len(v) > 3:
            raise ValueError(f"maximaal 3 clarifying_questions, gekregen: {len(v)}")
        return v


class IntakePlan(Plan):
    """verfijnd en eventueel bevroren plan na de intake-agent."""

    frozen: bool
