"""critique_runner: voert elk critique-rol uit en beoordeelt de analyst-output."""

import json
from pathlib import Path

from loguru import logger

from src.agents.analyst_runner import _format_evidence_cards, _get_role_description
from src.agents.base import Agent
from src.models import EvidenceCard, Project
from src.prompts import load_prompt, render_prompt
from src.schemas.analyse import CritiqueResult
from src.state import get_session
from src.utils import load_yaml

_BASE_DIR = Path(__file__).parent.parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"
_OUTPUT_TYPES_PATH = _BASE_DIR / "config" / "output_types.yaml"


def _get_section_ids(output_type: str) -> list[str]:
    """Haal de required section-ids op voor het gegeven output-type."""
    config = load_yaml(str(_OUTPUT_TYPES_PATH))
    ot_data = config.get("output_types", {}).get(output_type, {})
    sections = ot_data.get("required_sections", []) + ot_data.get("optional_sections", [])
    return [s["id"] for s in sections]


class CritiqueRunner(Agent):
    """Voert elk critique-rol uit op de gecombineerde analyst-output."""

    agent_name = "critique"

    def run(self, analyst_outputs: dict[str, str]) -> list[CritiqueResult]:
        """Voer alle critique-rollen uit en geef een lijst CritiqueResult terug."""
        with get_session() as session:
            project = session.get(Project, self.project_id)
            if project is None:
                logger.error(f"project niet gevonden: project={self.project_id}")
                return []
            primary_category = project.primary_category or ""
            output_type = project.output_type or ""

        plan_path = _PROJECTS_DIR / self.project_id / "plan.json"
        plan_data = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {}

        critique_roles: list[str] = (
            plan_data.get("active_role_pack", {}).get("critique_roles", [])
        )
        interpreted_goal = plan_data.get("interpreted_goal", "")

        if not critique_roles:
            logger.warning(f"geen critique-rollen gevonden: project={self.project_id}")
            return []

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

        section_ids = _get_section_ids(output_type)
        section_ids_text = ", ".join(section_ids) if section_ids else "(geen secties)"

        combined_analyst = "\n\n".join(
            f"## {role}\n\n{content}" for role, content in analyst_outputs.items()
        )

        analysis_dir = _PROJECTS_DIR / self.project_id / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)

        prompt_template = load_prompt("critique")
        results: list[CritiqueResult] = []

        for role_name in critique_roles:
            role_description = _get_role_description(role_name)
            user_prompt = render_prompt(
                prompt_template,
                {
                    "role_name": role_name,
                    "role_description": role_description,
                    "primary_category": primary_category,
                    "interpreted_goal": interpreted_goal,
                    "section_ids": section_ids_text,
                    "evidence_cards": evidence_cards_text,
                    "analyst_outputs": combined_analyst,
                },
            )

            raw = self._call_llm(
                profile="critique_model",
                user_prompt=user_prompt,
                role_name=role_name,
                response_format={"type": "json_object"},
            )

            out_path = analysis_dir / f"critique_{role_name}.md"
            out_path.write_text(raw, encoding="utf-8")

            critique: CritiqueResult | None = None
            try:
                critique = CritiqueResult.model_validate_json(raw)
            except Exception as exc:
                logger.warning(
                    f"critique parse-fout: project={self.project_id} "
                    f"rol={role_name} fout={exc}"
                )
                # lege critique als fallback zodat de pipeline doorgaat
                critique = CritiqueResult(
                    needs_redo=False,
                    weak_sections=[],
                    general_feedback="(parse-fout, critique overgeslagen)",
                    section_feedback={},
                    severity="low",
                )

            results.append(critique)
            logger.info(
                f"critique klaar: project={self.project_id} rol={role_name} "
                f"needs_redo={critique.needs_redo} severity={critique.severity}"
            )

        return results
