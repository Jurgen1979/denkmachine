"""evidence-routes: bewijs-review, acties per kaart en bulk-operaties."""

import json
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required

from src.models import EvidenceCard, Project
from src.schemas.evidence import ALLOWED_CLAIM_TYPES
from src.state import get_session

_BASE_DIR = Path(__file__).parent.parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"

_ALLOWED_STATUSES = {"awaiting_evidence_review", "evidence_approved"}

evidence_bp = Blueprint("evidence", __name__)


def _get_project_or_abort(project_id: str) -> Project:
    """Haal project op uit db of geef 404 terug."""
    with get_session() as session:
        project = session.get(Project, project_id)
    if project is None:
        abort(404)
    return project


def _load_cards(project_id: str, filters: dict) -> list[EvidenceCard]:
    """Laad EvidenceCard-rijen voor dit project, gefilterd op query-params."""
    with get_session() as session:
        q = session.query(EvidenceCard).filter(EvidenceCard.project_id == project_id)
        if filters.get("source"):
            q = q.filter(EvidenceCard.source_id == filters["source"])
        if filters.get("claim_type"):
            q = q.filter(EvidenceCard.claim_type == filters["claim_type"])
        cards = q.order_by(EvidenceCard.id).all()

    # tag-filters in python (tags opgeslagen als json-string)
    tag_filter = filters.get("tag")
    weak_only = filters.get("weak") == "1"

    result = []
    for card in cards:
        card_tags = json.loads(card.tags) if card.tags else []
        if tag_filter and tag_filter not in card_tags:
            continue
        if weak_only and "weak" not in card_tags:
            continue
        result.append(card)
    return result


def _get_filter_options(project_id: str) -> dict:
    """Haal unieke source_ids, claim_types en tags op voor de filter-balk."""
    with get_session() as session:
        cards = (
            session.query(EvidenceCard)
            .filter(EvidenceCard.project_id == project_id)
            .order_by(EvidenceCard.id)
            .all()
        )
    source_ids: list[str] = sorted({c.source_id for c in cards})
    claim_types: list[str] = sorted({c.claim_type for c in cards})
    all_tags: set[str] = set()
    for card in cards:
        if card.tags:
            all_tags.update(json.loads(card.tags))
    return {
        "source_ids": source_ids,
        "claim_types": claim_types,
        "tags": sorted(all_tags),
    }


def _write_cards_json(project_id: str) -> None:
    """Herschrijf cards.json vanuit de huidige db-staat."""
    with get_session() as session:
        cards = (
            session.query(EvidenceCard)
            .filter(EvidenceCard.project_id == project_id)
            .order_by(EvidenceCard.id)
            .all()
        )
        card_dicts = []
        for card in cards:
            card_dicts.append({
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
            })

    evidence_dir = _PROJECTS_DIR / project_id / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "cards.json").write_text(
        json.dumps(card_dicts, ensure_ascii=False, indent=2), encoding="utf-8"
    )


@evidence_bp.route("/project/<project_id>/evidence", methods=["GET"])
@login_required
def evidence_view(project_id: str):
    """Toon de evidence-review pagina met alle bewijskaarten en filters."""
    project = _get_project_or_abort(project_id)
    if project.status not in _ALLOWED_STATUSES:
        abort(409)

    filters = {
        "source": request.args.get("source", ""),
        "claim_type": request.args.get("claim_type", ""),
        "tag": request.args.get("tag", ""),
        "weak": request.args.get("weak", ""),
    }
    cards = _load_cards(project_id, filters)
    options = _get_filter_options(project_id)

    return render_template(
        "evidence.html",
        project=project,
        cards=cards,
        filters=filters,
        source_ids=options["source_ids"],
        claim_types=options["claim_types"],
        tags=options["tags"],
    )


@evidence_bp.route("/project/<project_id>/evidence/fragment", methods=["GET"])
@login_required
def evidence_fragment(project_id: str):
    """Geef enkel het tabel-fragment terug (htmx live refresh)."""
    project = _get_project_or_abort(project_id)
    if project.status not in _ALLOWED_STATUSES:
        abort(409)

    filters = {
        "source": request.args.get("source", ""),
        "claim_type": request.args.get("claim_type", ""),
        "tag": request.args.get("tag", ""),
        "weak": request.args.get("weak", ""),
    }
    cards = _load_cards(project_id, filters)
    options = _get_filter_options(project_id)

    return render_template(
        "evidence_fragment.html",
        project=project,
        cards=cards,
        filters=filters,
        source_ids=options["source_ids"],
        claim_types=options["claim_types"],
        tags=options["tags"],
    )


@evidence_bp.route("/project/<project_id>/evidence/<ev_id>/approve", methods=["POST"])
@login_required
def evidence_approve(project_id: str, ev_id: str):
    """Zet een kaart op approved."""
    project = _get_project_or_abort(project_id)
    if project.status != "awaiting_evidence_review":
        abort(409)

    with get_session() as session:
        card = session.get(EvidenceCard, ev_id)
        if card is None or card.project_id != project_id:
            abort(404)
        card.human_status = "approved"
        card.human_reviewed = True
        session.commit()

    return redirect(request.referrer or url_for("evidence.evidence_view", project_id=project_id))


@evidence_bp.route("/project/<project_id>/evidence/<ev_id>/reject", methods=["POST"])
@login_required
def evidence_reject(project_id: str, ev_id: str):
    """Zet een kaart op rejected."""
    with get_session() as session:
        card = session.get(EvidenceCard, ev_id)
        if card is None or card.project_id != project_id:
            abort(404)
        card.human_status = "rejected"
        card.human_reviewed = True
        session.commit()

    return redirect(request.referrer or url_for("evidence.evidence_view", project_id=project_id))


@evidence_bp.route("/project/<project_id>/evidence/<ev_id>/edit", methods=["POST"])
@login_required
def evidence_edit(project_id: str, ev_id: str):
    """Bewerk claim, claim_type, confidence en optionele note van een kaart."""
    claim = request.form.get("claim", "").strip()
    claim_type = request.form.get("claim_type", "").strip()
    confidence = request.form.get("confidence", "").strip()
    note = request.form.get("note", "").strip() or None

    if claim_type not in ALLOWED_CLAIM_TYPES:
        return f"ongeldig claim_type: {claim_type}", 400
    if confidence not in {"high", "medium", "low"}:
        return f"ongeldig confidence: {confidence}", 400
    if not claim:
        return "claim mag niet leeg zijn", 400

    with get_session() as session:
        card = session.get(EvidenceCard, ev_id)
        if card is None or card.project_id != project_id:
            abort(404)
        card.claim = claim
        card.claim_type = claim_type
        card.confidence = confidence
        card.human_status = "edited"
        card.human_reviewed = True
        if note:
            card.human_note = note
        session.commit()

    return redirect(request.referrer or url_for("evidence.evidence_view", project_id=project_id))


@evidence_bp.route("/project/<project_id>/evidence/<ev_id>/note", methods=["POST"])
@login_required
def evidence_note(project_id: str, ev_id: str):
    """Sla alleen de human_note op bij een kaart."""
    note = request.form.get("note", "").strip() or None

    with get_session() as session:
        card = session.get(EvidenceCard, ev_id)
        if card is None or card.project_id != project_id:
            abort(404)
        card.human_note = note
        session.commit()

    return redirect(request.referrer or url_for("evidence.evidence_view", project_id=project_id))


@evidence_bp.route("/project/<project_id>/evidence/bulk", methods=["POST"])
@login_required
def evidence_bulk(project_id: str):
    """Voer een bulk-actie uit op kaarten (approve_all, reject_all, approve_source)."""
    action = request.form.get("action", "")
    source = request.form.get("source", "")

    with get_session() as session:
        q = session.query(EvidenceCard).filter(EvidenceCard.project_id == project_id)
        if action == "approve_source" and source:
            q = q.filter(EvidenceCard.source_id == source)

        cards = q.all()
        for card in cards:
            if action in ("approve_all", "approve_source"):
                card.human_status = "approved"
                card.human_reviewed = True
            elif action == "reject_all":
                card.human_status = "rejected"
                card.human_reviewed = True
        session.commit()

    return redirect(url_for("evidence.evidence_view", project_id=project_id))


@evidence_bp.route("/project/<project_id>/evidence/add", methods=["POST"])
@login_required
def evidence_add(project_id: str):
    """Voeg een handmatige bewijskaart toe."""
    claim = request.form.get("claim", "").strip()
    claim_type = request.form.get("claim_type", "").strip()
    source_id = request.form.get("source_id", "manual").strip() or "manual"
    source_type = request.form.get("source_type", "user_input").strip() or "user_input"
    confidence = request.form.get("confidence", "medium").strip() or "medium"
    quote = request.form.get("quote", "").strip() or None
    context = request.form.get("context", "").strip() or None
    tags_raw = request.form.get("tags", "").strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    if claim_type not in ALLOWED_CLAIM_TYPES:
        return f"ongeldig claim_type: {claim_type}", 400
    if confidence not in {"high", "medium", "low"}:
        return f"ongeldig confidence: {confidence}", 400
    if not claim:
        return "claim mag niet leeg zijn", 400

    # volgnummer bepalen: hoger dan het hoogste bestaande ev_xxx-id (globaal)
    with get_session() as session:
        existing = session.query(EvidenceCard).all()
        max_num = 0
        for card in existing:
            if card.id.startswith("ev_"):
                try:
                    num = int(card.id[3:])
                    max_num = max(max_num, num)
                except ValueError:
                    pass

        new_id = f"ev_{max_num + 1:03d}"
        now = datetime.now(timezone.utc).isoformat()
        new_card = EvidenceCard(
            id=new_id,
            project_id=project_id,
            source_id=source_id,
            source_type=source_type,
            claim=claim,
            claim_type=claim_type,
            quote=quote,
            context=context,
            confidence=confidence,
            tags=json.dumps(tags, ensure_ascii=False),
            category_relevance=json.dumps([], ensure_ascii=False),
            human_reviewed=True,
            human_status="approved",
            human_note=None,
            created_by="human",
            created_at=now,
        )
        session.add(new_card)
        session.commit()

    return redirect(url_for("evidence.evidence_view", project_id=project_id))


@evidence_bp.route("/project/<project_id>/evidence/approve-all-and-continue", methods=["POST"])
@login_required
def evidence_approve_all_and_continue(project_id: str):
    """Keur alle nog niet-gereviewde kaarten goed en zet status op evidence_approved."""
    project = _get_project_or_abort(project_id)
    if project.status != "awaiting_evidence_review":
        abort(409)

    with get_session() as session:
        cards = (
            session.query(EvidenceCard)
            .filter(
                EvidenceCard.project_id == project_id,
                EvidenceCard.human_status == "pending",
            )
            .all()
        )
        for card in cards:
            card.human_status = "approved"
            card.human_reviewed = True
        session.commit()

    _write_cards_json(project_id)

    now = datetime.now(timezone.utc).isoformat()
    with get_session() as session:
        project = session.get(Project, project_id)
        if project is not None:
            project.status = "evidence_approved"
            project.updated_at = now
            session.commit()

    return redirect(url_for("evidence.evidence_view", project_id=project_id))
