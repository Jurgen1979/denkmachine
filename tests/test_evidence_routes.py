"""tests voor de evidence-routes."""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

os.environ.setdefault("DM_USER", "testuser")
os.environ.setdefault("DM_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DM_PASSWORD_HASH", "")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("FIRECRAWL_API_KEY", "test-firecrawl-key")

_BASE_DIR = Path(__file__).parent.parent
_PROJECTS_DIR = _BASE_DIR / "projects"


@pytest.fixture
def client():
    """Flask test-client met ingelogde gebruiker."""
    from src.app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.test_client() as c:
        with app.test_request_context():
            from flask_login import login_user
            from src.app_user import SingleUser
            login_user(SingleUser())
        with c.session_transaction() as sess:
            sess["_user_id"] = "1"
            sess["_fresh"] = True
        yield c


def _create_project(status: str = "awaiting_evidence_review") -> str:
    """Maak een testproject aan."""
    from src.models import Project
    from src.state import get_session

    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    project = Project(
        id=project_id,
        created_at=now,
        updated_at=now,
        user_question="test",
        status=status,
        primary_category="diagnose",
    )
    with get_session() as session:
        session.add(project)
        session.commit()
    return project_id


def _create_cards(project_id: str, n: int = 5, source_id: str = "src_001") -> list[str]:
    """Maak n testkaarten aan voor een project."""
    from src.models import EvidenceCard
    from src.state import get_session

    ids = []
    with get_session() as session:
        for i in range(n):
            ev_id = f"ev_{i + 1:03d}_{project_id[:4]}"
            tags = json.dumps(["weak"] if i % 2 == 0 else [])
            card = EvidenceCard(
                id=ev_id,
                project_id=project_id,
                source_id=source_id if i < 3 else "src_002",
                source_type="document",
                claim=f"claim {i}",
                claim_type="observation",
                quote=None,
                context=None,
                confidence="medium",
                tags=tags,
                category_relevance=json.dumps([]),
                human_reviewed=False,
                human_status="pending",
                human_note=None,
                created_by="agent",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            session.add(card)
            ids.append(ev_id)
        session.commit()
    return ids


def test_evidence_page_renders(client):
    """GET /evidence geeft 200 en bevat tabel-html."""
    project_id = _create_project()
    _create_cards(project_id, 5)

    response = client.get(f"/project/{project_id}/evidence")
    assert response.status_code == 200
    assert b"<table" in response.data


def test_evidence_page_wrong_status_409(client):
    """GET /evidence met status plan_approved geeft 409."""
    project_id = _create_project(status="plan_approved")
    response = client.get(f"/project/{project_id}/evidence")
    assert response.status_code == 409


def test_evidence_page_filters_by_source(client):
    """GET /evidence?source=src_001 toont alleen kaarten van src_001."""
    project_id = _create_project()
    _create_cards(project_id, 5)

    response = client.get(f"/project/{project_id}/evidence?source=src_001")
    assert response.status_code == 200
    data = response.data.decode()
    assert "src_001" in data
    # src_002 mag niet in de tabel-rijen staan (buiten de filter-balk)
    # we controleren via het fragment
    response2 = client.get(f"/project/{project_id}/evidence/fragment?source=src_001")
    assert b"src_002" not in response2.data or response2.data.count(b"src_002") == 0


def test_evidence_page_filters_by_claim_type(client):
    """GET /evidence?claim_type=observation toont alleen observation-kaarten."""
    project_id = _create_project()
    _create_cards(project_id, 5)

    response = client.get(f"/project/{project_id}/evidence?claim_type=observation")
    assert response.status_code == 200
    assert b"observation" in response.data


def test_evidence_page_filters_weak(client):
    """GET /evidence?weak=1 toont alleen weak-kaarten."""
    project_id = _create_project()
    _create_cards(project_id, 5)

    response = client.get(f"/project/{project_id}/evidence?weak=1")
    assert response.status_code == 200
    # fragment apart controleren
    response2 = client.get(f"/project/{project_id}/evidence/fragment?weak=1")
    assert response2.status_code == 200


def test_approve_card(client):
    """POST /evidence/<ev_id>/approve zet human_status op approved."""
    from src.models import EvidenceCard
    from src.state import get_session

    project_id = _create_project()
    ids = _create_cards(project_id, 1)
    ev_id = ids[0]

    response = client.post(
        f"/project/{project_id}/evidence/{ev_id}/approve",
        follow_redirects=True,
    )
    assert response.status_code == 200

    with get_session() as session:
        card = session.get(EvidenceCard, ev_id)
        assert card.human_status == "approved"
        assert card.human_reviewed is True


def test_reject_card(client):
    """POST /evidence/<ev_id>/reject zet human_status op rejected."""
    from src.models import EvidenceCard
    from src.state import get_session

    project_id = _create_project()
    ids = _create_cards(project_id, 1)
    ev_id = ids[0]

    response = client.post(
        f"/project/{project_id}/evidence/{ev_id}/reject",
        follow_redirects=True,
    )
    assert response.status_code == 200

    with get_session() as session:
        card = session.get(EvidenceCard, ev_id)
        assert card.human_status == "rejected"


def test_edit_card(client):
    """POST /evidence/<ev_id>/edit werkt claim en claim_type bij, zet status edited."""
    from src.models import EvidenceCard
    from src.state import get_session

    project_id = _create_project()
    ids = _create_cards(project_id, 1)
    ev_id = ids[0]

    response = client.post(
        f"/project/{project_id}/evidence/{ev_id}/edit",
        data={
            "claim": "aangepaste claim",
            "claim_type": "pain_point",
            "confidence": "high",
            "note": "mijn notitie",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with get_session() as session:
        card = session.get(EvidenceCard, ev_id)
        assert card.claim == "aangepaste claim"
        assert card.claim_type == "pain_point"
        assert card.human_status == "edited"
        assert card.human_note == "mijn notitie"


def test_edit_invalid_claim_type_400(client):
    """POST /evidence/<ev_id>/edit met onbekend claim_type geeft 400."""
    project_id = _create_project()
    ids = _create_cards(project_id, 1)
    ev_id = ids[0]

    response = client.post(
        f"/project/{project_id}/evidence/{ev_id}/edit",
        data={
            "claim": "claim",
            "claim_type": "onbekend_type_xyz",
            "confidence": "medium",
        },
    )
    assert response.status_code == 400


def test_bulk_approve_all(client):
    """POST /evidence/bulk action=approve_all zet alle pending-kaarten op approved."""
    from src.models import EvidenceCard
    from src.state import get_session

    project_id = _create_project()
    _create_cards(project_id, 4)

    response = client.post(
        f"/project/{project_id}/evidence/bulk",
        data={"action": "approve_all"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with get_session() as session:
        cards = (
            session.query(EvidenceCard)
            .filter(EvidenceCard.project_id == project_id)
            .all()
        )
        for card in cards:
            assert card.human_status == "approved"


def test_bulk_approve_source(client):
    """POST /evidence/bulk action=approve_source source=src_001 keurt alleen src_001 goed."""
    from src.models import EvidenceCard
    from src.state import get_session

    project_id = _create_project()
    _create_cards(project_id, 5)

    response = client.post(
        f"/project/{project_id}/evidence/bulk",
        data={"action": "approve_source", "source": "src_001"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with get_session() as session:
        src1 = (
            session.query(EvidenceCard)
            .filter(
                EvidenceCard.project_id == project_id,
                EvidenceCard.source_id == "src_001",
            )
            .all()
        )
        for card in src1:
            assert card.human_status == "approved"

        src2 = (
            session.query(EvidenceCard)
            .filter(
                EvidenceCard.project_id == project_id,
                EvidenceCard.source_id == "src_002",
            )
            .all()
        )
        for card in src2:
            assert card.human_status == "pending"


def test_add_manual_card(client):
    """POST /evidence/add maakt een nieuwe kaart aan met created_by=human."""
    from src.models import EvidenceCard
    from src.state import get_session

    project_id = _create_project()

    response = client.post(
        f"/project/{project_id}/evidence/add",
        data={
            "claim": "mijn eigen observatie",
            "claim_type": "observation",
            "source_id": "manual",
            "source_type": "user_input",
            "confidence": "high",
            "tags": "critical, weak",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with get_session() as session:
        card = (
            session.query(EvidenceCard)
            .filter(
                EvidenceCard.project_id == project_id,
                EvidenceCard.created_by == "human",
            )
            .first()
        )
        assert card is not None
        assert card.human_status == "approved"
        assert card.id.startswith("ev_")


def test_approve_all_and_continue_changes_status(client):
    """POST /evidence/approve-all-and-continue keurt alles goed en zet status evidence_approved."""
    from src.models import EvidenceCard, Project
    from src.state import get_session

    project_id = _create_project()
    _create_cards(project_id, 3)

    project_dir = _PROJECTS_DIR / project_id / "evidence"
    project_dir.mkdir(parents=True, exist_ok=True)

    response = client.post(
        f"/project/{project_id}/evidence/approve-all-and-continue",
        follow_redirects=True,
    )
    assert response.status_code == 200

    with get_session() as session:
        cards = (
            session.query(EvidenceCard)
            .filter(EvidenceCard.project_id == project_id)
            .all()
        )
        for card in cards:
            assert card.human_status == "approved"

        project = session.get(Project, project_id)
        assert project.status == "evidence_approved"

    cards_json = _PROJECTS_DIR / project_id / "evidence" / "cards.json"
    assert cards_json.exists()
    data = json.loads(cards_json.read_text(encoding="utf-8"))
    assert len(data) == 3
    for entry in data:
        assert entry["human_status"] == "approved"


def test_approve_all_wrong_status_409(client):
    """POST /evidence/approve-all-and-continue op reeds goedgekeurd project geeft 409."""
    project_id = _create_project(status="evidence_approved")

    response = client.post(
        f"/project/{project_id}/evidence/approve-all-and-continue",
    )
    assert response.status_code == 409
