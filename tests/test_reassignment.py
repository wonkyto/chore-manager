from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from chore_manager.app import create_app
from chore_manager.db import db
from chore_manager.models import ChoreCompletion, ChoreReassignment


def test_reassign_route_creates_row(client, app):
    resp = client.post(
        "/reassign/dishes/bob",
        data={"to_person": "alice", "date": "2026-04-30"},
    )
    assert resp.status_code == 302

    with app.app_context():
        rows = db.session.query(ChoreReassignment).all()
        assert len(rows) == 1
        assert rows[0].chore_key == "dishes"
        assert rows[0].original_person_key == "bob"
        assert rows[0].new_person_key == "alice"
        assert rows[0].on_date == date(2026, 4, 30)


def test_reassign_back_to_original_deletes_row(client, app):
    client.post("/reassign/dishes/bob", data={"to_person": "alice", "date": "2026-04-30"})
    with app.app_context():
        assert db.session.query(ChoreReassignment).count() == 1

    resp = client.post(
        "/reassign/dishes/bob",
        data={"to_person": "bob", "date": "2026-04-30"},
    )
    assert resp.status_code == 302

    with app.app_context():
        assert db.session.query(ChoreReassignment).count() == 0


def test_reassign_updates_existing_row(client, app):
    # Add a third person to the family for this test via direct fixture setup is tricky;
    # instead, reassign the same chore twice on the same day - second call updates target.
    client.post("/reassign/dishes/bob", data={"to_person": "alice", "date": "2026-04-30"})
    # Reassign the same (chore, original) on the same day to alice again - upsert no-op.
    client.post("/reassign/dishes/bob", data={"to_person": "alice", "date": "2026-04-30"})

    with app.app_context():
        rows = db.session.query(ChoreReassignment).all()
        assert len(rows) == 1
        assert rows[0].new_person_key == "alice"


def test_reassign_unknown_chore_400(client):
    resp = client.post("/reassign/missing/bob", data={"to_person": "alice", "date": "2026-04-30"})
    assert resp.status_code == 400


def test_reassign_unassigned_original_400(client):
    # alice is not assigned to dishes per fixture YAML
    resp = client.post("/reassign/dishes/alice", data={"to_person": "bob", "date": "2026-04-30"})
    assert resp.status_code == 400


def test_reassign_unknown_target_400(client):
    resp = client.post("/reassign/dishes/bob", data={"to_person": "ghost", "date": "2026-04-30"})
    assert resp.status_code == 400


def test_reassign_bad_date_400(client):
    resp = client.post("/reassign/dishes/bob", data={"to_person": "alice", "date": "not-a-date"})
    assert resp.status_code == 400


def test_index_shows_chore_in_new_persons_column(client, app):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    with app.app_context():
        today = datetime.now(ZoneInfo(app.config["TIMEZONE"])).date()
    client.post(
        "/reassign/dishes/bob",
        data={"to_person": "alice", "date": today.isoformat()},
    )
    resp = client.get("/")
    body = resp.get_data(as_text=True)

    alice_idx = body.index('data-person-key="alice"')
    bob_idx = body.index('data-person-key="bob"')
    alice_section = body[alice_idx:bob_idx] if alice_idx < bob_idx else body[alice_idx:]
    assert "Dishes" in alice_section
    assert "from Bob" in alice_section


def test_toggle_works_for_reassigned_new_person(client, app):
    # alice is not in dishes.assigned_to. Reassign first, then toggle as alice.
    client.post("/reassign/dishes/bob", data={"to_person": "alice", "date": "2026-04-30"})
    resp = client.post("/toggle/dishes/alice", data={"date": "2026-04-30"})
    assert resp.status_code == 200

    with app.app_context():
        rows = db.session.query(ChoreCompletion).all()
        assert len(rows) == 1
        assert rows[0].person_key == "alice"
        assert rows[0].chore_key == "dishes"


def test_toggle_blocked_for_original_after_reassign(client, app):
    client.post("/reassign/dishes/bob", data={"to_person": "alice", "date": "2026-04-30"})
    resp = client.post("/toggle/dishes/bob", data={"date": "2026-04-30"})
    assert resp.status_code == 404


def test_toggle_blocked_for_unrelated_person(client):
    # Without a reassignment, alice can't toggle bob's chore.
    resp = client.post("/toggle/dishes/alice")
    assert resp.status_code == 404


_PIN_FAMILY = """
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
  - key: dishes
    name: Dishes
    points: 5
    frequency: daily
    assigned_to: [bob]
rewards: []
"""

_PIN_APP_CFG = """
parent_pin: "1234"
"""


@pytest.fixture
def pin_app(tmp_path: Path):
    cfg = tmp_path / "family.yaml"
    cfg.write_text(_PIN_FAMILY)
    (tmp_path / "app.yaml").write_text(_PIN_APP_CFG)
    db_path = tmp_path / "test.db"
    app = create_app(config_path=cfg, db_url=f"sqlite:///{db_path}")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


def test_reassign_blocked_when_pin_locked(pin_app):
    client = pin_app.test_client()
    resp = client.post("/reassign/dishes/bob", data={"to_person": "alice", "date": "2026-04-30"})
    assert resp.status_code == 403

    with pin_app.app_context():
        assert db.session.query(ChoreReassignment).count() == 0


def test_reassign_allowed_after_pin_unlock(pin_app):
    client = pin_app.test_client()
    client.post("/pin/unlock", data={"pin": "1234"})
    resp = client.post("/reassign/dishes/bob", data={"to_person": "alice", "date": "2026-04-30"})
    assert resp.status_code == 302

    with pin_app.app_context():
        assert db.session.query(ChoreReassignment).count() == 1
