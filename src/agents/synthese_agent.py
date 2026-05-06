"""synthese_agent: assembleert alle secties tot een eindrapport en genereert een actieplan."""

from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from src.agents.base import Agent
from src.agents.draft_agent import _load_stijlgids
from src.models import Flag, Project
from src.prompts import load_prompt, render_prompt
from src.state import get_session
from src.utils import load_yaml

_BASE_DIR = Path(__file__).parent.parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"
_OUTPUT_TYPES_PATH = _BASE_DIR / "config" / "output_types.yaml"

_MIN_WORDS_PER_SECTION = 80
_MAX_WORDS_PER_SECTION = 4000


class SyntheseAgent(Agent):
    """Assembleert secties tot een eindrapport en genereert een actieplan."""

    agent_name = "synthese"

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

    def _add_flag(
        self, flag_type: str, severity: str, description: str, section_id: str | None = None
    ) -> None:
        """Voeg een vlag toe aan het project."""
        flag = Flag(
            project_id=self.project_id,
            type=flag_type,
            severity=severity,
            description=description,
            section_id=section_id,
            resolved=False,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with get_session() as session:
            session.add(flag)
            session.commit()

    def _post_processing_checks(
        self, section_drafts: dict[str, str], output_type: str
    ) -> None:
        """Controleer woordaantal per sectie en voeg flags toe bij afwijkingen."""
        ot_config = load_yaml(str(_OUTPUT_TYPES_PATH))
        ot_data = ot_config.get("output_types", {}).get(output_type, {})
        required_sections = {
            s["id"]: s for s in ot_data.get("required_sections", [])
        }

        for sec_id, content in section_drafts.items():
            word_count = len(content.split())
            if word_count < _MIN_WORDS_PER_SECTION:
                self._add_flag(
                    "section_too_short",
                    "medium",
                    f"sectie {sec_id} heeft slechts {word_count} woorden "
                    f"(minimum: {_MIN_WORDS_PER_SECTION})",
                    section_id=sec_id,
                )
                logger.warning(
                    f"post-processing: sectie te kort: project={self.project_id} "
                    f"sectie={sec_id} woorden={word_count}"
                )
            elif word_count > _MAX_WORDS_PER_SECTION:
                self._add_flag(
                    "section_too_long",
                    "low",
                    f"sectie {sec_id} heeft {word_count} woorden "
                    f"(maximum: {_MAX_WORDS_PER_SECTION})",
                    section_id=sec_id,
                )

        for req_id in required_sections:
            if req_id not in section_drafts or not section_drafts[req_id].strip():
                self._add_flag(
                    "required_section_missing",
                    "high",
                    f"verplichte sectie {req_id} ontbreekt of is leeg",
                    section_id=req_id,
                )
                logger.error(
                    f"post-processing: verplichte sectie ontbreekt: "
                    f"project={self.project_id} sectie={req_id}"
                )

    def run(self, section_drafts: dict[str, str]) -> str:
        """
        Assembleer alle secties, schrijf output.md en action_plan.md.

        Geeft het pad naar output.md terug als string.
        """
        self._set_status("synthesising")

        with get_session() as session:
            project = session.get(Project, self.project_id)
            if project is None:
                logger.error(f"project niet gevonden: project={self.project_id}")
                return ""
            primary_category = project.primary_category or ""
            output_type = project.output_type or ""

        # plan.json voor interpreted_goal
        import json
        plan_path = _PROJECTS_DIR / self.project_id / "plan.json"
        plan_data = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {}
        interpreted_goal = plan_data.get("interpreted_goal", "")

        # output-type config
        ot_config = load_yaml(str(_OUTPUT_TYPES_PATH))
        ot_data = ot_config.get("output_types", {}).get(output_type, {})
        action_plan_style = ot_data.get("action_plan_style", "prioritized_list")
        display_name = ot_data.get("display_name", output_type)

        stijlgids = _load_stijlgids()

        # post-processing checks
        self._post_processing_checks(section_drafts, output_type)

        # secties samenvoegen voor synthese-prompt
        combined_sections = "\n\n".join(
            content for content in section_drafts.values() if content.strip()
        )

        # rapport-titel afleiden uit output_type
        report_title = f"{display_name}: {interpreted_goal[:80]}"

        # synthese-call
        synthese_prompt = load_prompt("synthese")
        synthese_user = render_prompt(
            synthese_prompt,
            {
                "output_type": display_name,
                "primary_category": primary_category,
                "interpreted_goal": interpreted_goal,
                "stijlgids": stijlgids,
                "section_drafts": combined_sections,
                "report_title": report_title,
            },
        )

        final_report = self._call_llm(
            profile="writing_model",
            user_prompt=synthese_user,
            role_name="synthese",
        )

        # output.md wegschrijven
        final_dir = _PROJECTS_DIR / self.project_id / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        output_path = final_dir / "output.md"
        output_path.write_text(final_report, encoding="utf-8")
        logger.info(f"output.md geschreven: project={self.project_id}")

        # actieplan genereren
        action_prompt = load_prompt("action_plan")
        action_user = render_prompt(
            action_prompt,
            {
                "primary_category": primary_category,
                "interpreted_goal": interpreted_goal,
                "action_plan_style": action_plan_style,
                "final_report": final_report,
            },
        )

        action_plan = self._call_llm(
            profile="writing_model",
            user_prompt=action_user,
            role_name="action_plan",
        )

        (final_dir / "action_plan.md").write_text(action_plan, encoding="utf-8")
        logger.info(f"action_plan.md geschreven: project={self.project_id}")

        self._set_status("done")
        return str(output_path)
