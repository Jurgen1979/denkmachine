"""sqlalchemy 2.0 orm-modellen voor denkmachine."""

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Project(Base):
    """een enkel denkmachine-project."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    user_question: Mapped[str] = mapped_column(Text, nullable=False)
    primary_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    secondary_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    cost_eur: Mapped[float] = mapped_column(Float, default=0)
    runtime_seconds: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_runtime_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_name: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentCall(Base):
    """een enkele llm-call uitgevoerd door een agent."""

    __tablename__ = "agent_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("projects.id"), nullable=False)
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    role_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str] = mapped_column(Text, nullable=False)
    profile: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("idx_calls_project", "project_id"),)


class Flag(Base):
    """een vlag gelinkt aan een project."""

    __tablename__ = "flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("projects.id"), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    section_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("idx_flags_project", "project_id"),)


class EvidenceCard(Base):
    """een bewijs-kaart gelinkt aan een project."""

    __tablename__ = "evidence_cards"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("projects.id"), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(Text, nullable=False)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_relevance: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    human_status: Mapped[str] = mapped_column(Text, default="pending")
    human_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("idx_evidence_project", "project_id"),)
