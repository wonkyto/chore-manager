from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from chore_manager.app import create_app
from chore_manager.approvals import available_points, points_earned
from chore_manager.db import db
from chore_manager.models import Adjustment, ChoreCompletion
from chore_manager.stats import daily_points, weekly_points


def test_points_earned_includes_positive_adjustment(app):
    with app.app_context():
        db.session.add(Adjustment(person_key="bob", points=15, created_on=date(2026, 4, 30)))
        db.session.commit()
        assert points_earned(db.session, "bob") == 15
        assert available_points(db.session, "bob") == 15


def test_points_earned_includes_negative_adjustment(app):
    with app.app_context():
        db.session.add(
            ChoreCompletion(
                chore_key="dishes",
                person_key="bob",
                completed_on=date(2026, 4, 30),
                points_awarded=20,
            )
        )
        db.session.add(Adjustment(person_key="bob", points=-5, created_on=date(2026, 4, 30)))
        db.session.commit()
        assert points_earned(db.session, "bob") == 15
        assert available_points(db.session, "bob") == 15


def test_adjustment_route_adds_preset(client, app):
    resp = client.post(
        "/adjustment/add",
        data={"person_key": "bob", "points": "10"},
    )
    assert resp.status_code == 302

    with app.app_context():
        rows = db.session.query(Adjustment).all()
        assert len(rows) == 1
        assert rows[0].points == 10
        assert rows[0].person_key == "bob"
        assert rows[0].reason is None


def test_adjustment_route_deducts_preset(client, app):
    resp = client.post(
        "/adjustment/add",
        data={"person_key": "bob", "points": "-20", "reason": "Skipped homework"},
    )
    assert resp.status_code == 302

    with app.app_context():
        rows = db.session.query(Adjustment).all()
        assert len(rows) == 1
        assert rows[0].points == -20
        assert rows[0].reason == "Skipped homework"


def test_adjustment_route_custom_add(client, app):
    resp = client.post(
        "/adjustment/add",
        data={"person_key": "bob", "custom": "37", "custom_sign": "add"},
    )
    assert resp.status_code == 302

    with app.app_context():
        rows = db.session.query(Adjustment).all()
        assert rows[0].points == 37


def test_adjustment_route_custom_deduct(client, app):
    resp = client.post(
        "/adjustment/add",
        data={"person_key": "bob", "custom": "12", "custom_sign": "deduct"},
    )
    assert resp.status_code == 302

    with app.app_context():
        rows = db.session.query(Adjustment).all()
        assert rows[0].points == -12


def test_adjustment_route_rejects_unknown_person(client):
    resp = client.post("/adjustment/add", data={"person_key": "ghost", "points": "10"})
    assert resp.status_code == 400


def test_adjustment_route_rejects_zero(client):
    resp = client.post("/adjustment/add", data={"person_key": "bob", "points": "0"})
    assert resp.status_code == 400


def test_adjustment_route_rejects_missing_amount(client):
    resp = client.post("/adjustment/add", data={"person_key": "bob"})
    assert resp.status_code == 400


def test_adjustment_route_rejects_negative_custom(client):
    # custom should always be positive; sign carries direction
    resp = client.post(
        "/adjustment/add",
        data={"person_key": "bob", "custom": "-10", "custom_sign": "add"},
    )
    assert resp.status_code == 400


_PIN_FAMILY = """
people:
  - key: bob
    name: Bob
    role: child
    colour: "#10b981"
chores: []
rewards: []
"""

_PIN_APP_CFG = """
parent_pin: "1234"
pin_timeout_seconds: 60
"""


@pytest.fixture
def pin_client(tmp_path: Path):
    cfg = tmp_path / "family.yaml"
    cfg.write_text(_PIN_FAMILY)
    (tmp_path / "app.yaml").write_text(_PIN_APP_CFG)
    db_path = tmp_path / "test.db"
    app = create_app(config_path=cfg, db_url=f"sqlite:///{db_path}")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client(), app


def test_adjustment_blocked_when_pin_locked(pin_client):
    client, app = pin_client
    resp = client.post("/adjustment/add", data={"person_key": "bob", "points": "10"})
    assert resp.status_code == 403

    with app.app_context():
        assert db.session.query(Adjustment).count() == 0


def test_adjustment_allowed_after_pin_unlock(pin_client):
    client, app = pin_client
    client.post("/pin/unlock", data={"pin": "1234"})
    resp = client.post("/adjustment/add", data={"person_key": "bob", "points": "10"})
    assert resp.status_code == 302

    with app.app_context():
        assert db.session.query(Adjustment).count() == 1


def test_daily_points_includes_adjustments(app):
    with app.app_context():
        today = date(2026, 4, 30)
        db.session.add(
            ChoreCompletion(
                chore_key="dishes",
                person_key="bob",
                completed_on=today,
                points_awarded=10,
            )
        )
        db.session.add(Adjustment(person_key="bob", points=5, created_on=today))
        db.session.add(Adjustment(person_key="bob", points=-3, created_on=today))
        db.session.commit()

        days = daily_points(db.session, "bob", today, days=7)
        today_row = next(d for d in days if d["is_today"])
        assert today_row["pts"] == 12  # 10 + 5 - 3


def test_weekly_points_includes_adjustments(app):
    with app.app_context():
        # 30 Apr 2026 is a Thursday; week starts Mon 27 Apr.
        today = date(2026, 4, 30)
        db.session.add(Adjustment(person_key="bob", points=15, created_on=today))
        # Last week: Mon 20 Apr - Sun 26 Apr.
        db.session.add(Adjustment(person_key="bob", points=8, created_on=date(2026, 4, 22)))
        db.session.commit()

        this_week, last_week = weekly_points(db.session, "bob", today)
        assert this_week == 15
        assert last_week == 8
