"""bewijs-extractor agent: extraheert gestructureerde bewijskaarten uit ingested bronnen."""

import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from src.agents.base import Agent
from src.models import EvidenceCard, Flag, Project
from src.prompts import load_prompt, render_prompt
from src.schemas.evidence import EvidenceExtractionResult
from src.state import get_session
from src.utils import load_yaml

_BASE_DIR = Path(__file__).parent.parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"
_CATEGORIES_PATH = _BASE_DIR / "config" / "categories.yaml"
_EVIDENCE_CAP = 250


class BewijsExtractorAgent(Agent):
    """Extraheert bewijskaarten uit ingested bronnen via llm-calls."""

    agent_name = "bewijs_extractor"

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

    def _add_flag(self, flag_type: str, severity: str, description: str) -> None:
        """Voeg een vlag toe aan het project."""
        flag = Flag(
            project_id=self.project_id,
            type=flag_type,
            severity=severity,
            description=description,
            resolved=False,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with get_session() as session:
            session.add(flag)
            session.commit()

    def _get_relevant_claim_types(self, primary_category: str) -> list[str]:
        """Haal relevant_claim_types op uit categories.yaml voor de primaire categorie."""
        config = load_yaml(str(_CATEGORIES_PATH))
        categories = config.get("categories", {})
        cat_data = categories.get(primary_category, {})
        return cat_data.get("relevant_claim_types", [])

    def _determine_source_type_hint(self, first_line: str) -> str:
        """Bepaal de source_type-hint op basis van de eerste regel van het markdown-bestand."""
        if first_line.strip().startswith("# http"):
            return "website"
        return "document"

    def _extract_source_id(self, filename: str) -> str:
        """Extraheer source_id uit bestandsnaam: alles voor de tweede underscore."""
        parts = filename.split("_", 2)
        if len(parts) >= 2:
            return f"{parts[0]}_{parts[1]}"
        return parts[0]

    def _next_ev_id(self, current_count: int) -> str:
        """Genereer een doorlopend ev-id op basis van het huidige aantal kaarten."""
        return f"ev_{current_count + 1:03d}"

    def _save_card(self, card_data: dict, ev_id: str) -> None:
        """Sla een EvidenceCard op in de database."""
        tags_str = json.dumps(card_data.get("tags", []), ensure_ascii=False)
        relevance_str = json.dumps(card_data.get("category_relevance", []), ensure_ascii=False)
        record = EvidenceCard(
            id=ev_id,
            project_id=self.project_id,
            source_id=card_data["source_id"],
            source_type=card_data["source_type"],
            claim=card_data["claim"],
            claim_type=card_data["claim_type"],
            quote=card_data.get("quote"),
            context=card_data.get("context"),
            confidence=card_data["confidence"],
            tags=tags_str,
            category_relevance=relevance_str,
            human_reviewed=False,
            human_status="pending",
            human_note=None,
            created_by="agent",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with get_session() as session:
            session.add(record)
            session.commit()

    def _write_cards_json(self, cards: list[dict]) -> None:
        """Schrijf de volledige lijst kaarten naar projects/[id]/evidence/cards.json."""
        evidence_dir = _PROJECTS_DIR / self.project_id / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        cards_path = evidence_dir / "cards.json"
        cards_path.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"cards.json geschreven: project={self.project_id} aantal={len(cards)}")

    def _card_to_dict(self, card: EvidenceCard) -> dict:
        """Zet een EvidenceCard orm-object om naar een dict."""
        return {
            "id": card.id,
            "project_id": card.project_id,
            "source_id": card.source_id,
            "source_type": card.source_type,
            "claim": card.claim,
            "claim_type": card.claim_type,
            "quote": card.quote,
            "context": card.context,
            "confidence": card.confidence,
            "tags": json.loads(card.tags) if card.tags else [],
            "category_relevance": (
                json.loads(card.category_relevance) if card.category_relevance else []
            ),
            "human_reviewed": card.human_reviewed,
            "human_status": card.human_status,
            "human_note": card.human_note,
            "created_by": card.created_by,
            "created_at": card.created_at,
        }

    def run(self) -> None:
        """Verwerk alle ingested bronnen en extraheer bewijskaarten."""
        self._set_status("extracting_evidence")

        # project-info ophalen
        with get_session() as session:
            project = session.get(Project, self.project_id)
            if project is None:
                logger.error(f"project niet gevonden: project={self.project_id}")
                return
            primary_category = project.primary_category or ""
            secondary_category = project.secondary_category or ""

        # plan.json inladen voor research_plan
        plan_path = _PROJECTS_DIR / self.project_id / "plan.json"
        if plan_path.exists():
            plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
            research_plan = json.dumps(
                plan_data.get("research_plan", {}), ensure_ascii=False
            )
        else:
            research_plan = ""

        # relevant_claim_types ophalen
        relevant_claim_types = self._get_relevant_claim_types(primary_category)
        if relevant_claim_types:
            claim_types_text = "\n".join(f"- {ct}" for ct in relevant_claim_types)
        else:
            claim_types_text = "(alle types toegestaan)"

        # bron-bestanden verzamelen (alfabetisch, bundle.md overslaan)
        ingested_dir = _PROJECTS_DIR / self.project_id / "ingested"
        if not ingested_dir.exists():
            logger.error(
                f"ingested-map ontbreekt, bewijs-extractie afgebroken: "
                f"project={self.project_id}"
            )
            self._set_status("failed")
            self._add_flag(
                "evidence_extraction_failed",
                "high",
                "ingested-map ontbreekt: bronbestanden zijn niet beschikbaar",
            )
            return

        source_files = sorted(
            f for f in ingested_dir.glob("*.md")
            if f.name != "bundle.md"
        )

        if not source_files:
            logger.error(f"geen bronbestanden voor bewijs-extractie: project={self.project_id}")
            self._set_status("failed")
            self._add_flag(
                "evidence_extraction_failed",
                "high",
                "geen ingested bronbestanden aanwezig voor bewijs-extractie",
            )
            return

        prompt_template = load_prompt("bewijs_extractor")
        successful_sources = 0
        cap_reached = False
        all_cards: list[dict] = []

        # globale id-teller: start na het hoogste bestaande ev_xxx-id in de db (unique pk)
        # project-teller: huidige kaarten voor dit project (voor cap-check)
        with get_session() as session:
            all_existing = session.query(EvidenceCard).all()
            global_max = 0
            project_card_count = 0
            for c in all_existing:
                if c.id.startswith("ev_"):
                    try:
                        num = int(c.id[3:])
                        global_max = max(global_max, num)
                    except ValueError:
                        pass
                if c.project_id == self.project_id:
                    project_card_count += 1
        ev_id_counter = global_max

        for source_file in source_files:
            if cap_reached:
                break

            source_id = self._extract_source_id(source_file.stem)
            source_content = source_file.read_text(encoding="utf-8")
            first_line = source_content.splitlines()[0] if source_content.strip() else ""
            source_type_hint = self._determine_source_type_hint(first_line)

            user_prompt = render_prompt(
                prompt_template,
                {
                    "primary_category": primary_category,
                    "secondary_category": secondary_category,
                    "relevant_claim_types": claim_types_text,
                    "source_type_hint": source_type_hint,
                    "research_plan": research_plan,
                    "source_id": source_id,
                    "source_content": source_content,
                },
            )

            # eerste llm-poging
            raw = self._call_llm(
                profile="reasoning_model",
                user_prompt=user_prompt,
                role_name=source_id,
                response_format={"type": "json_object"},
            )

            # valideer output
            extraction = None
            try:
                extraction = EvidenceExtractionResult.model_validate_json(raw)
            except Exception as first_exc:
                logger.warning(
                    f"bewijs_extractor parse-fout (eerste poging): "
                    f"project={self.project_id} source={source_id} fout={first_exc}"
                )
                # retry met expliciete instructie
                retry_prompt = (
                    user_prompt
                    + "\n\ngeef alleen valide json terug volgens het opgegeven schema. "
                    "geen markdown fences, geen extra tekst, "
                    "geen kaarten met onbekende claim_types."
                )
                raw2 = self._call_llm(
                    profile="reasoning_model",
                    user_prompt=retry_prompt,
                    role_name=source_id,
                    response_format={"type": "json_object"},
                )
                try:
                    extraction = EvidenceExtractionResult.model_validate_json(raw2)
                except Exception as second_exc:
                    logger.error(
                        f"bewijs_extractor parse-fout (tweede poging, bron overgeslagen): "
                        f"project={self.project_id} source={source_id} fout={second_exc}",
                        exc_info=True,
                    )
                    self._add_flag(
                        "evidence_source_failed",
                        "medium",
                        f"bewijs-extractie mislukt voor {source_id}: {second_exc}",
                    )
                    continue

            # kaarten opslaan met cap-controle
            for llm_card in extraction.cards:
                if project_card_count >= _EVIDENCE_CAP:
                    if not cap_reached:
                        logger.info(
                            f"evidence cap bereikt: project={self.project_id} "
                            f"cap={_EVIDENCE_CAP}"
                        )
                        self._add_flag(
                            "evidence_cap_reached",
                            "medium",
                            f"evidence cap van {_EVIDENCE_CAP} kaarten bereikt",
                        )
                        cap_reached = True
                    break

                ev_id = self._next_ev_id(ev_id_counter)
                card_dict = llm_card.model_dump()
                card_dict["source_id"] = source_id
                self._save_card(card_dict, ev_id)
                all_cards.append({**card_dict, "id": ev_id, "project_id": self.project_id})
                ev_id_counter += 1
                project_card_count += 1

            logger.info(
                f"bewijs_extractor klaar: project={self.project_id} "
                f"source={source_id} kaarten={len(extraction.cards)}"
            )
            successful_sources += 1

        if successful_sources == 0:
            logger.error(f"alle bronnen mislukt bij bewijs-extractie: project={self.project_id}")
            self._set_status("failed")
            self._add_flag(
                "evidence_extraction_failed",
                "high",
                "bewijs-extractie volledig mislukt: geen enkele bron succesvol verwerkt",
            )
            return

        self._write_cards_json(all_cards)
        self._set_status("awaiting_evidence_review")
