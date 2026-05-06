"""ontleder-agent: classificeert de vraag en stelt een werkplan op."""

import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from src.agents.base import Agent
from src.llm_client import LLMClient
from src.prompts import load_prompt, render_prompt
from src.schemas.plan import Plan
from src.state import get_session
from src.utils import get_cost_caps, load_yaml

_BASE_DIR = Path(__file__).parent.parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"


class OntlederFailure(Exception):
    """Wordt gegooid als de ontleder tweemaal invalide json terugstuurt."""


class OntlederAgent(Agent):
    """Classificeert een vraag en stelt een gestructureerd werkplan op."""

    agent_name = "ontleder"

    def __init__(self, llm_client: LLMClient, project_id: str) -> None:
        """Initialiseer de ontleder met config uit yaml-bestanden."""
        super().__init__(llm_client, project_id)
        self._categories = load_yaml(str(_BASE_DIR / "config" / "categories.yaml"))
        self._output_types = load_yaml(str(_BASE_DIR / "config" / "output_types.yaml"))

    def _build_role_packs_text(self) -> str:
        """Maak een compacte tekstweergave van alle rolpakketten per categorie."""
        lines = []
        for cat_key, cat_data in self._categories.get("categories", {}).items():
            analyst = ", ".join(cat_data.get("analyst_roles", []))
            critique = ", ".join(cat_data.get("critique_roles", []))
            lines.append(f"{cat_key}:")
            lines.append(f"  analyst_roles: {analyst}")
            lines.append(f"  critique_roles: {critique}")
        return "\n".join(lines)

    def _build_available_output_types(self) -> str:
        """Geef een kommalijst van beschikbare output-types."""
        keys = list(self._output_types.get("output_types", {}).keys())
        return ", ".join(keys)

    def _set_status(self, status: str) -> None:
        """Update alleen de projectstatus en timestamp."""
        from src.models import Project

        now = datetime.now(timezone.utc).isoformat()
        with get_session() as session:
            project = session.get(Project, self.project_id)
            if project is None:
                logger.error(f"project niet gevonden bij statusupdate: id={self.project_id}")
                return
            project.status = status
            project.updated_at = now
            session.commit()

    def _update_project(self, plan: Plan, status: str) -> None:
        """Sla plan-velden op in de project-rij en update de timestamp."""
        from src.models import Project

        now = datetime.now(timezone.utc).isoformat()
        with get_session() as session:
            project = session.get(Project, self.project_id)
            if project is None:
                logger.error(f"project niet gevonden bij plan-opslag: id={self.project_id}")
                return
            project.primary_category = plan.primary_category
            project.secondary_category = plan.secondary_category
            project.output_type = plan.output_type
            project.estimated_cost_eur = plan.estimated_cost_eur
            project.estimated_runtime_minutes = int(plan.estimated_runtime_minutes)
            project.status = status
            project.updated_at = now
            session.commit()

    def _write_cost_flag(self, estimated: float, cap: float) -> None:
        """Schrijf een cost_estimate_high-vlag naar de flags-tabel."""
        from src.models import Flag

        now = datetime.now(timezone.utc).isoformat()
        description = (
            f"geschatte kost \u20ac{estimated:.2f} boven hard cap \u20ac{cap:.0f}"
        )
        flag = Flag(
            project_id=self.project_id,
            type="cost_estimate_high",
            severity="high",
            description=description,
            section_id=None,
            created_at=now,
        )
        with get_session() as session:
            session.add(flag)
            session.commit()

    def _save_plan_json(self, plan: Plan) -> None:
        """Sla het plan op als plan.json in de projectmap."""
        plan_path = _PROJECTS_DIR / self.project_id / "plan.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    def _parse_plan(self, raw_text: str) -> Plan:
        """Parseer en valideer het json-antwoord van het llm als Plan."""
        data = json.loads(raw_text.strip())
        return Plan.model_validate(data)

    def run(
        self,
        user_question: str,
        user_context: str | None = None,
        category_hint: str | None = None,
    ) -> Plan:
        """Classificeer de vraag en stel een werkplan op. Geeft een Plan terug."""
        self._set_status("classifying")

        template = load_prompt("ontleder")
        prompt = render_prompt(template, {
            "user_question": user_question,
            "user_context": user_context or "geen extra context",
            "category_hint": category_hint or "geen hint",
            "role_packs": self._build_role_packs_text(),
            "available_output_types": self._build_available_output_types(),
        })

        raw = self._call_llm(profile="reasoning_model", user_prompt=prompt)

        try:
            plan = self._parse_plan(raw)
        except Exception as first_exc:
            logger.warning(
                f"ontleder eerste poging mislukt: {first_exc}. retry met json-instructie."
            )
            retry_prompt = (
                f"{prompt}\n\n"
                "geef alleen valide json terug, geen markdown fences, geen extra tekst."
            )
            raw2 = self._call_llm(profile="reasoning_model", user_prompt=retry_prompt)
            try:
                plan = self._parse_plan(raw2)
            except Exception as second_exc:
                logger.error(
                    f"ontleder tweede poging mislukt: {second_exc}",
                    exc_info=True,
                )
                raise OntlederFailure(
                    f"ontleder kon geen valide json produceren: {second_exc}"
                ) from second_exc

        hard_cap, _ = get_cost_caps()
        needs_clarification = (
            plan.category_confidence < 0.7 or plan.scope_clarity_score < 0.7
        )
        new_status = "awaiting_clarification" if needs_clarification else "plan_review"

        self._save_plan_json(plan)
        self._update_project(plan, new_status)

        if plan.estimated_cost_eur > hard_cap:
            self._write_cost_flag(plan.estimated_cost_eur, hard_cap)
            logger.warning(
                f"cost_pre_flight: project={self.project_id} "
                f"estimated={plan.estimated_cost_eur:.2f} cap={hard_cap:.0f}"
            )

        logger.info(
            f"ontleder klaar: project={self.project_id} "
            f"category={plan.primary_category} confidence={plan.category_confidence:.2f} "
            f"status={new_status}"
        )
        return plan
