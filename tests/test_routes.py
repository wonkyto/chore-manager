from __future__ import annotations

from pathlib import Path

import pytest

_PENALTY_CONFIG = """
people:
  - key: bob
    name: Bob
    role: child
    colour: "#10b981"
chores:
  - key: homework
    name: Homework
    points: 5
    penalty: 3
    frequency: daily
    assigned_to: [bob]
rewards: []
"""


@pytest.fixture
def penalty_app(tmp_path: Path):
    from chore_manager.app import create_app

    cfg = tmp_path / "family.yaml"
    cfg.write_text(_PENALTY_CONFIG)
    db_path = tmp_path / "test.db"
    app = create_app(config_path=cfg, db_url=f"sqlite:///{db_path}")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture
def penalty_client(penalty_app):
    return penalty_app.test_client()


def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Bob" in body
    assert "CHORE MANAGER" in body


def test_toggle_marks_done(client, app):
    from chore_manager.db import db
    from chore_manager.models import ChoreCompletion

    resp = client.post("/toggle/dishes/bob")
    assert resp.status_code == 200
    assert resp.headers.get("HX-Trigger-After-Swap") is not None

    with app.app_context():
        rows = db.session.query(ChoreCompletion).all()
        assert len(rows) == 1
        assert rows[0].chore_key == "dishes"
        assert rows[0].person_key == "bob"


def test_toggle_again_undoes(client, app):
    from chore_manager.db import db
    from chore_manager.models import ChoreCompletion

    client.post("/toggle/dishes/bob")
    resp = client.post("/toggle/dishes/bob")
    assert resp.status_code == 200
    assert resp.headers.get("HX-Trigger") is None

    with app.app_context():
        rows = db.session.query(ChoreCompletion).all()
        assert len(rows) == 0


def test_toggle_unknown_chore_returns_404(client):
    resp = client.post("/toggle/missing/bob")
    assert resp.status_code == 404


def test_toggle_unassigned_person_returns_404(client):
    resp = client.post("/toggle/dishes/alice")
    assert resp.status_code == 404


def test_view_as_sets_cookie(client):
    resp = client.post("/view-as", data={"viewer": "bob"})
    assert resp.status_code == 302
    cookies = resp.headers.getlist("Set-Cookie")
    assert any("viewer=bob" in c for c in cookies)


def test_toggle_on_past_date_removes_penalty(client, app):
    """Retroactively ticking a chore should clear any penalty already applied for that date."""
    from datetime import date

    from chore_manager.db import db
    from chore_manager.models import ChoreCompletion, ChorePenalty

    yesterday = date(2026, 5, 20)
    with app.app_context():
        db.session.add(
            ChorePenalty(
                chore_key="dishes",
                person_key="bob",
                penalty_date=yesterday,
                points_deducted=5,
            )
        )
        db.session.commit()

    resp = client.post("/toggle/dishes/bob", data={"date": yesterday.isoformat()})
    assert resp.status_code == 200

    with app.app_context():
        completions = db.session.query(ChoreCompletion).all()
        penalties = db.session.query(ChorePenalty).all()
        assert len(completions) == 1
        assert completions[0].completed_on == yesterday
        assert penalties == []


def test_untoggle_on_past_date_reapplies_penalty(penalty_client, penalty_app):
    """Un-ticking a past completion reinstates the penalty that was originally due.

    Without this, you can clear a penalty by ticking and then un-ticking - the un-tick
    leaves the chore unfinished with no penalty, defeating the rollover rule."""
    from datetime import date, timedelta
    from unittest.mock import patch

    from chore_manager import routes
    from chore_manager.db import db
    from chore_manager.models import ChoreCompletion, ChorePenalty

    fake_today = date(2026, 6, 1)
    yesterday = fake_today - timedelta(days=1)

    with penalty_app.app_context():
        db.session.add(
            ChoreCompletion(
                chore_key="homework",
                person_key="bob",
                completed_on=yesterday,
                points_awarded=5,
            )
        )
        db.session.commit()

    with patch.object(routes, "_today", return_value=fake_today):
        resp = penalty_client.post("/toggle/homework/bob", data={"date": yesterday.isoformat()})
        assert resp.status_code == 200

    with penalty_app.app_context():
        assert db.session.query(ChoreCompletion).all() == []
        penalties = db.session.query(ChorePenalty).all()
        assert len(penalties) == 1
        assert penalties[0].penalty_date == yesterday
        assert penalties[0].points_deducted == 3


def test_unskip_on_past_date_reapplies_penalty(penalty_client, penalty_app):
    """Un-skipping a past skip reinstates the penalty for an unfinished penalty-bearing chore."""
    from datetime import date, timedelta
    from unittest.mock import patch

    from chore_manager import routes
    from chore_manager.db import db
    from chore_manager.models import ChorePenalty, ChoreSkip

    fake_today = date(2026, 6, 1)
    yesterday = fake_today - timedelta(days=1)

    with penalty_app.app_context():
        db.session.add(
            ChoreSkip(chore_key="homework", person_key="bob", skip_date=yesterday)
        )
        db.session.commit()

    with patch.object(routes, "_today", return_value=fake_today):
        resp = penalty_client.post("/unskip/homework/bob", data={"date": yesterday.isoformat()})
        assert resp.status_code == 200

    with penalty_app.app_context():
        assert db.session.query(ChoreSkip).all() == []
        penalties = db.session.query(ChorePenalty).all()
        assert len(penalties) == 1
        assert penalties[0].penalty_date == yesterday


def test_redeem_creates_pending(client, app):
    from datetime import date

    from chore_manager.db import db
    from chore_manager.models import ChoreCompletion, Redemption

    with app.app_context():
        db.session.add(
            ChoreCompletion(
                chore_key="dishes",
                person_key="bob",
                completed_on=date(2026, 4, 30),
                points_awarded=30,
            )
        )
        db.session.commit()

    resp = client.post("/redeem/screen/bob")
    assert resp.status_code == 302

    with app.app_context():
        redemptions = db.session.query(Redemption).all()
        assert len(redemptions) == 1
        assert redemptions[0].status == "pending"
