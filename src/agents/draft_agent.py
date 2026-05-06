"""draft_agent: schrijft elke rapport-sectie op basis van analyst-output en critique."""

import json
from pathlib import Path

from loguru import logger

from src.agents.analyst_runner import _format_evidence_cards
from src.agents.base import Agent
from src.models import EvidenceCard, Project
from src.prompts import load_prompt, render_prompt
from src.schemas.analyse import CritiqueResult
from src.state import get_session
from src.utils import load_yaml

_BASE_DIR = Path(__file__).parent.parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"
_OUTPUT_TYPES_PATH = _BASE_DIR / "config" / "output_types.yaml"
_STIJLGIDS_PATH = _BASE_DIR / "config" / "stijlgids.md"


def _load_stijlgids() -> str:
    """Laad de stijlgids uit config/stijlgids.md."""
    if _STIJLGIDS_PATH.exists():
        return _STIJLGIDS_PATH.read_text(encoding="utf-8")
    return "(geen stijlgids beschikbaar)"


def _aggregate_critique(
    critiques: list[CritiqueResult],
) -> tuple[set[str], dict[str, str]]:
    """
    Aggregeer critique-resultaten naar weak_sections en section_feedback.

    Geeft (weak_sections, section_feedback) terug.
    weak_sections zijn secties die minstens één high-severity critique kregen.
    """
    weak_sections: set[str] = set()
    section_feedback: dict[str, str] = {}

    for result in critiques:
        if result.needs_redo and result.severity == "high":
            for sec_id in result.weak_sections:
                weak_sections.add(sec_id)
                existing = section_feedback.get(sec_id, "")
                new = result.section_feedback.get(sec_id, result.general_feedback)
                section_feedback[sec_id] = (existing + "\n\n" + new).strip() if existing else new

    return weak_sections, section_feedback


class DraftAgent(Agent):
    """Schrijft elke rapport-sectie, met redo voor zwakke secties na critique."""

    agent_name = "draft"

    def _set_status(self, status: str) -> None:
        """Zet de projectstatus in de database."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with get_session() as session:
            project = session.get(Project, self.project_id)
            if project is not None:
                project.status = status
                project.updated_at = now
                session.commit()
        logger.info(f"project status bijgewerkt: project={self.project_id} status={status}")

    def _draft_one_section(
        self,
        section: dict,
        primary_category: str,
        interpreted_goal: str,
        output_type: str,
        analyst_outputs_text: str,
        evidence_cards_text: str,
        stijlgids: str,
        critique_feedback: str = "",
    ) -> str:
        """Draft één sectie via een llm-call. Geeft de markdown-inhoud terug."""
        prompt_template = load_prompt("draft_sectie")

        if critique_feedback:
            critique_block = (
                f"# critique-feedback voor deze sectie\n\n{critique_feedback}\n\n"
                "Verwerk bovenstaande feedback bij het schrijven van deze sectie."
            )
        else:
            critique_block = ""

        user_prompt = render_prompt(
            prompt_template,
            {
                "output_type": output_type,
                "primary_category": primary_category,
                "interpreted_goal": interpreted_goal,
                "section_id": section["id"],
                "section_title": section["title"],
                "section_purpose": section.get("purpose", ""),
                "estimated_length_words": str(section.get("estimated_length_words", 300)),
                "stijlgids": stijlgids,
                "evidence_cards": evidence_cards_text,
                "analyst_outputs": analyst_outputs_text,
                "critique_block": critique_block,
            },
        )

        return self._call_llm(
            profile="longform_model",
            user_prompt=user_prompt,
            role_name=section["id"],
        )

    def run(
        self,
        analyst_outputs: dict[str, str],
        critiques: list[CritiqueResult],
    ) -> dict[str, str]:
        """
        Draft alle secties sequentieel, met redo voor high-severity weak_sections.

        Geeft dict van section_id -> uiteindelijke markdown-inhoud terug.
        """
        self._set_status("drafting")

        with get_session() as session:
            project = session.get(Project, self.project_id)
            if project is None:
                logger.error(f"project niet gevonden: project={self.project_id}")
                return {}
            primary_category = project.primary_category or ""
            output_type = project.output_type or ""

        plan_path = _PROJECTS_DIR / self.project_id / "plan.json"
        plan_data = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {}
        interpreted_goal = plan_data.get("interpreted_goal", "")

        # secties ophalen uit output_types.yaml, met lengtes uit research_plan als die bestaan
        ot_config = load_yaml(str(_OUTPUT_TYPES_PATH))
        ot_data = ot_config.get("output_types", {}).get(output_type, {})
        required_sections = ot_data.get("required_sections", [])
        optional_sections = ot_data.get("optional_sections", [])
        all_sections = required_sections + optional_sections

        # voeg geschatte lengte toe vanuit research_plan als die beschikbaar is
        research_sections = {
            s["id"]: s.get("estimated_length_words", 300)
            for s in plan_data.get("research_plan", {}).get("report_sections", [])
        }
        for sec in all_sections:
            if sec["id"] in research_sections:
                sec["estimated_length_words"] = research_sections[sec["id"]]
            else:
                sec.setdefault("estimated_length_words", 300)

        # evidence en stijlgids laden
        with get_session() as session:
            cards = (
                session.query(EvidenceCard)
                .filter(
                    EvidenceCard.project_id == self.project_id,
                    EvidenceCard.human_status == "approved",
                )
                .order_by(EvidenceCard.id)
                .all()
            )
        evidence_cards_text = _format_evidence_cards(cards)
        stijlgids = _load_stijlgids()

        analyst_outputs_text = "\n\n".join(
            f"## {role}\n\n{content}" for role, content in analyst_outputs.items()
        )

        # critique aggregeren
        weak_sections, section_feedback = _aggregate_critique(critiques)

        drafts_dir = _PROJECTS_DIR / self.project_id / "drafts"
        drafts_dir.mkdir(parents=True, exist_ok=True)

        section_drafts: dict[str, str] = {}

        for section in all_sections:
            sec_id = section["id"]

            # eerste draft
            content = self._draft_one_section(
                section=section,
                primary_category=primary_category,
                interpreted_goal=interpreted_goal,
                output_type=output_type,
                analyst_outputs_text=analyst_outputs_text,
                evidence_cards_text=evidence_cards_text,
                stijlgids=stijlgids,
            )
            (drafts_dir / f"section_{sec_id}.md").write_text(content, encoding="utf-8")
            logger.info(
                f"draft klaar: project={self.project_id} sectie={sec_id}"
            )

            # redo als critique high-severity feedback geeft voor deze sectie
            if sec_id in weak_sections:
                feedback = section_feedback.get(sec_id, "")
                logger.info(
                    f"redo gestart: project={self.project_id} sectie={sec_id}"
                )
                content = self._draft_one_section(
                    section=section,
                    primary_category=primary_category,
                    interpreted_goal=interpreted_goal,
                    output_type=output_type,
                    analyst_outputs_text=analyst_outputs_text,
                    evidence_cards_text=evidence_cards_text,
                    stijlgids=stijlgids,
                    critique_feedback=feedback,
                )
                (drafts_dir / f"section_{sec_id}_v2.md").write_text(content, encoding="utf-8")
                logger.info(
                    f"redo klaar: project={self.project_id} sectie={sec_id}"
                )

            section_drafts[sec_id] = content

        return section_drafts
