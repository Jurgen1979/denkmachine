"""intake-agent: verfijnt het plan na ontvangen van antwoorden van de gebruiker."""

import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from src.agents.base import Agent
from src.prompts import load_prompt, render_prompt
from src.schemas.plan import IntakePlan
from src.state import get_session

_BASE_DIR = Path(__file__).parent.parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"


class IntakeAgent(Agent):
    """Verfijnt het werkplan op basis van antwoorden op clarifying questions."""

    agent_name = "intake"

    def _update_project_status(self, status: str) -> None:
        """Update de projectstatus en timestamp."""
        from src.models import Project

        now = datetime.now(timezone.utc).isoformat()
        with get_session() as session:
            project = session.get(Project, self.project_id)
            if project is None:
                logger.error(f"project niet gevonden: id={self.project_id}")
                return
            project.status = status
            project.updated_at = now
            session.commit()

    def _save_plan_json(self, plan: IntakePlan) -> None:
        """Sla het bevroren of bijgewerkte plan op als plan.json."""
        plan_path = _PROJECTS_DIR / self.project_id / "plan.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    def run(
        self,
        previous_plan: dict,
        user_answers: dict[str, str],
    ) -> IntakePlan:
        """Verwerk de antwoorden en produceer een bijgewerkt of bevroren plan."""
        template = load_prompt("intake")
        prompt = render_prompt(template, {
            "previous_plan": json.dumps(previous_plan, ensure_ascii=False, indent=2),
            "user_answers": json.dumps(user_answers, ensure_ascii=False, indent=2),
        })

        raw = self._call_llm(profile="reasoning_model", user_prompt=prompt)
        data = json.loads(raw.strip())
        plan = IntakePlan.model_validate(data)

        self._save_plan_json(plan)

        if plan.frozen:
            self._update_project_status("plan_approved")
            logger.info(
                f"intake bevroren: project={self.project_id} status=plan_approved"
            )
        else:
            self._update_project_status("awaiting_clarification")
            logger.info(
                f"intake niet bevroren: project={self.project_id} "
                f"status=awaiting_clarification "
                f"nieuwe_vragen={len(plan.clarifying_questions)}"
            )

        return plan
