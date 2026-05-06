"""pydantic-modellen voor de bewijs-extractor llm-output."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ALLOWED_CLAIM_TYPES = {
    "observation",
    "quote",
    "interpretation",
    "hypothesis",
    "external_fact",
    "competitive_claim",
    "requirement",
    "constraint",
    "assumption",
    "risk_signal",
    "opportunity_signal",
    "process_step",
    "pain_point",
    "user_need",
    "reference_example",
}

ALLOWED_SOURCE_TYPES = {
    "website",
    "interview",
    "document",
    "competitor",
    "external",
    "user_input",
    "domain_knowledge",
}


class EvidenceCardLLM(BaseModel):
    """één bewijskaart zoals geproduceerd door de llm. id en project_id worden later toegevoegd."""

    source_type: Literal[
        "website", "interview", "document", "competitor",
        "external", "user_input", "domain_knowledge",
    ]
    claim: str = Field(..., min_length=1)
    claim_type: str
    quote: str | None = None
    context: str | None = None
    confidence: Literal["high", "medium", "low"]
    tags: list[str] = Field(default_factory=list)
    category_relevance: list[str] = Field(default_factory=list)

    @field_validator("claim_type")
    @classmethod
    def claim_type_must_be_allowed(cls, v: str) -> str:
        """controleer dat het claim_type bestaat in de toegestane lijst."""
        if v not in ALLOWED_CLAIM_TYPES:
            raise ValueError(
                f"onbekend claim_type: {v}. toegestaan: {sorted(ALLOWED_CLAIM_TYPES)}"
            )
        return v


class EvidenceExtractionResult(BaseModel):
    """wrapper voor de json_object-response: {\"cards\": [...]}."""

    cards: list[EvidenceCardLLM]
