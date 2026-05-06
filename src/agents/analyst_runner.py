"""analyst_runner: voert elk analist-rol uit het rolpakket uit op de bewijskaarten."""

import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from src.agents.base import Agent
from src.models import EvidenceCard, Project
from src.prompts import load_prompt, render_prompt
from src.state import get_session
from src.utils import load_yaml

_BASE_DIR = Path(__file__).parent.parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"
_ROLES_PATH = _BASE_DIR / "config" / "roles.yaml"


def _format_evidence_cards(cards: list) -> str:
    """Zet een lijst EvidenceCard-objecten om naar leesbare tekst voor de prompt."""
    lines = []
    for card in cards:
        tags = json.loads(card.tags) if card.tags else []
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        lines.append(
            f"- [{card.id}] ({card.claim_type}{tag_str}) {card.claim}"
            + (f'\n  quote: "{card.quote}"' if card.quote else "")
        )
    return "\n".join(lines) if lines else "(geen bewijskaarten)"


def _get_role_description(role_name: str) -> str:
    """Haal de beschrijving van een rol op uit roles.yaml."""
    config = load_yaml(str(_ROLES_PATH))
    roles = config.get("roles", {})
    role_data = roles.get(role_name, {})
    return role_data.get(
        "description",
        f"Analyseer het vraagstuk vanuit het perspectief van {role_name}.",
    )


class AnalystRunner(Agent):
    """Voert elk analist-rol uit het rolpakket sequentieel uit."""

    agent_name = "analyst"

    def _set_status(self, status: str) -> None:
        """Zet de projectstatus in de database."""
        now = datetime.now(timezone.utc).isoformat()
        with get_session() as session:
            project = session.get(Project, self.project_id)
            if project is not None:
                project.status = status
                project.updated_at = now
                session.commit()
        logger.info(f"project status bijgewerkt: project={self.project_id} status={status}")

    def run(self) -> dict[str, str]:
        """Voer alle analist-rollen uit en geef een dict van rol -> output terug."""
        self._set_status("analysing")

        # projectgegevens ophalen
        with get_session() as session:
            project = session.get(Project, self.project_id)
            if project is None:
                logger.error(f"project niet gevonden: project={self.project_id}")
                return {}
            primary_category = project.primary_category or ""
            secondary_category = project.secondary_category or ""

        # plan.json inladen
        plan_path = _PROJECTS_DIR / self.project_id / "plan.json"
        if plan_path.exists():
            plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
        else:
            plan_data = {}

        analyst_roles: list[str] = (
            plan_data.get("active_role_pack", {}).get("analyst_roles", [])
        )
        interpreted_goal = plan_data.get("interpreted_goal", "")
        scope = plan_data.get("scope", "")
        research_plan = json.dumps(
            plan_data.get("research_plan", {}), ensure_ascii=False
        )

        if not analyst_roles:
            logger.warning(f"geen analist-rollen gevonden: project={self.project_id}")
            return {}

        # evidence bundle inladen
        bundle_path = _PROJECTS_DIR / self.project_id / "ingested" / "bundle.md"
        evidence_bundle = (
            bundle_path.read_text(encoding="utf-8") if bundle_path.exists() else ""
        )

        # goedgekeurde bewijskaarten ophalen
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

        # analyse-map aanmaken
        analysis_dir = _PROJECTS_DIR / self.project_id / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)

        prompt_template = load_prompt("analist")
        secondary_line = (
            f"\n- secundaire categorie: {secondary_category}" if secondary_category else ""
        )
        outputs: dict[str, str] = {}

        for role_name in analyst_roles:
            role_description = _get_role_description(role_name)
            user_prompt = render_prompt(
                prompt_template,
                {
                    "role_name": role_name,
                    "role_description": role_description,
                    "primary_category": primary_category,
                    "secondary_category_line": secondary_line,
                    "interpreted_goal": interpreted_goal,
                    "scope": scope,
                    "research_plan": research_plan,
                    "evidence_cards": evidence_cards_text,
                    "evidence_bundle": evidence_bundle,
                },
            )

            output = self._call_llm(
                profile="reasoning_model",
                user_prompt=user_prompt,
                role_name=role_name,
            )

            out_path = analysis_dir / f"role_{role_name}.md"
            out_path.write_text(output, encoding="utf-8")
            outputs[role_name] = output
            logger.info(
                f"analyst klaar: project={self.project_id} rol={role_name}"
            )

        return outputs
