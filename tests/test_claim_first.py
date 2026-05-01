from __future__ import annotations

from pathlib import Path

import pytest

from chore_manager.app import create_app
from chore_manager.db import db
from chore_manager.models import ChoreCompletion

_FAMILY = """
people:
  - key: alice
    name: Alice
    role: parent
    colour: "#4f46e5"
  - key: bob
    name: Bob
    role: child
    colour: "#10b981"
chores:
  - key: bins
    name: Take out the bins
    points: 8
    frequency: daily
    claim_first: true
    assigned_to: [alice, bob]
  - key: dishes
    name: Dishes
    points: 5
    frequency: daily
    assigned_to: [bob]
rewards: []
"""


@pytest.fixture
def claim_app(tmp_path: Path):
    cfg = tmp_path / "family.yaml"
    cfg.write_text(_FAMILY)
    db_path = tmp_path / "test.db"
    app = create_app(config_path=cfg, db_url=f"sqlite:///{db_path}")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture
def claim_client(claim_app):
    return claim_app.test_client()


def test_claim_first_shows_in_all_eligible_columns(claim_client):
    body = claim_client.get("/").get_data(as_text=True)
    alice_idx = body.index('data-person-key="alice"')
    bob_idx = body.index('data-person-key="bob"')
    if alice_idx < bob_idx:
        alice_section = body[alice_idx:bob_idx]
        bob_section = body[bob_idx:]
    else:
        alice_section = body[alice_idx:]
        bob_section = body[bob_idx:alice_idx]
    assert "Take out the bins" in alice_section
    assert "Take out the bins" in bob_section
    assert body.count("claim it") == 2


def test_claim_first_disappears_from_others_after_claim(claim_client, claim_app):
    claim_client.post("/toggle/bins/alice")
    body = claim_client.get("/").get_data(as_text=True)
    alice_idx = body.index('data-person-key="alice"')
    bob_idx = body.index('data-person-key="bob"')
    if alice_idx < bob_idx:
        alice_section = body[alice_idx:bob_idx]
        bob_section = body[bob_idx:]
    else:
        alice_section = body[alice_idx:]
        bob_section = body[bob_idx:alice_idx]
    assert "Take out the bins" in alice_section
    assert "Take out the bins" not in bob_section


def test_claim_first_either_eligible_can_claim(claim_client, claim_app):
    resp = claim_client.post("/toggle/bins/bob")
    assert resp.status_code == 200
    with claim_app.app_context():
        rows = db.session.query(ChoreCompletion).all()
        assert len(rows) == 1
        assert rows[0].person_key == "bob"
        assert rows[0].chore_key == "bins"


def test_claim_first_others_blocked_after_claim(claim_client):
    claim_client.post("/toggle/bins/alice")
    resp = claim_client.post("/toggle/bins/bob")
    assert resp.status_code == 404


def test_claim_first_claimer_can_unclaim(claim_client, claim_app):
    claim_client.post("/toggle/bins/alice")
    with claim_app.app_context():
        assert db.session.query(ChoreCompletion).count() == 1
    resp = claim_client.post("/toggle/bins/alice")
    assert resp.status_code == 200
    with claim_app.app_context():
        assert db.session.query(ChoreCompletion).count() == 0


def test_claim_first_returns_hx_refresh(claim_client):
    resp = claim_client.post("/toggle/bins/alice")
    assert resp.headers.get("HX-Refresh") == "true"


def test_normal_chore_no_hx_refresh(claim_client):
    resp = claim_client.post("/toggle/dishes/bob")
    assert resp.headers.get("HX-Refresh") is None


def test_reassign_blocked_for_claim_first(claim_client):
    resp = claim_client.post(
        "/reassign/bins/alice", data={"to_person": "bob", "date": "2026-05-01"}
    )
    assert resp.status_code == 400


def test_non_eligible_person_cannot_claim(tmp_path: Path):
    cfg = tmp_path / "family.yaml"
    cfg.write_text(_FAMILY.replace("assigned_to: [alice, bob]", "assigned_to: [bob]", 1))
    db_path = tmp_path / "test.db"
    app = create_app(config_path=cfg, db_url=f"sqlite:///{db_path}")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    resp = client.post("/toggle/bins/alice")
    assert resp.status_code == 404
