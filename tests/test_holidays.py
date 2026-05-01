from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from chore_manager.app import create_app
from chore_manager.config import load_config
from chore_manager.db import db
from chore_manager.history import streak
from chore_manager.models import ChoreCompletion, Holiday


def _today_for(app) -> date:
    return datetime.now(ZoneInfo(app.config["TIMEZONE"])).date()


def test_holiday_for_person_hides_chores(client, app):
    today = _today_for(app)
    with app.app_context():
        db.session.add(Holiday(start_date=today, end_date=today, person_key="bob", reason="Skiing"))
        db.session.commit()

    resp = client.get("/")
    body = resp.get_data(as_text=True)
    bob_idx = body.index('data-person-key="bob"')
    bob_section = body[bob_idx:]
    assert "On holiday" in bob_section
    assert "Skiing" in bob_section


def test_family_wide_holiday_covers_all(client, app):
    today = _today_for(app)
    with app.app_context():
        db.session.add(Holiday(start_date=today, end_date=today, reason="Public holiday"))
        db.session.commit()

    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert body.count("On holiday") == 2  # both alice and bob


def test_holiday_outside_range_does_not_hide(client, app):
    today = _today_for(app)
    yesterday = today - timedelta(days=1)
    with app.app_context():
        db.session.add(Holiday(start_date=yesterday, end_date=yesterday, person_key="bob"))
        db.session.commit()

    resp = client.get("/")
    body = resp.get_data(as_text=True)
    bob_idx = body.index('data-person-key="bob"')
    bob_section = body[bob_idx:]
    assert "On holiday" not in bob_section


def test_streak_skips_holiday_days(app):
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        today = date(2026, 5, 1)  # Friday
        # Bob has dishes (daily). Add a holiday in the middle of a streak.
        # Completed: Apr 28 (Tue), Apr 29 (Wed). Holiday Apr 30 (Thu).
        # Today (May 1, Fri) hasn't been ticked. Streak should be 2 (Wed, Tue).
        db.session.add_all(
            [
                ChoreCompletion(
                    chore_key="dishes",
                    person_key="bob",
                    completed_on=date(2026, 4, 28),
                    points_awarded=5,
                ),
                ChoreCompletion(
                    chore_key="dishes",
                    person_key="bob",
                    completed_on=date(2026, 4, 29),
                    points_awarded=5,
                ),
                Holiday(start_date=date(2026, 4, 30), end_date=date(2026, 4, 30), person_key="bob"),
            ]
        )
        db.session.commit()

        result = streak(db.session, cfg, "dishes", "bob", today)
        assert result == 2


def test_streak_no_holiday_breaks_normally(app):
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        today = date(2026, 5, 1)
        # Bob completed Tue and Wed; missed Thu (no holiday). Streak today should be 0.
        db.session.add_all(
            [
                ChoreCompletion(
                    chore_key="dishes",
                    person_key="bob",
                    completed_on=date(2026, 4, 28),
                    points_awarded=5,
                ),
                ChoreCompletion(
                    chore_key="dishes",
                    person_key="bob",
                    completed_on=date(2026, 4, 29),
                    points_awarded=5,
                ),
            ]
        )
        db.session.commit()

        result = streak(db.session, cfg, "dishes", "bob", today)
        assert result == 0


def test_streak_family_holiday_also_skips(app):
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        today = date(2026, 5, 1)
        db.session.add_all(
            [
                ChoreCompletion(
                    chore_key="dishes",
                    person_key="bob",
                    completed_on=date(2026, 4, 29),
                    points_awarded=5,
                ),
                Holiday(start_date=date(2026, 4, 30), end_date=date(2026, 4, 30)),
            ]
        )
        db.session.commit()

        result = streak(db.session, cfg, "dishes", "bob", today)
        assert result == 1


_HOLIDAY_FAMILY = """
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
    cfg.write_text(_HOLIDAY_FAMILY)
    (tmp_path / "app.yaml").write_text(_PIN_APP_CFG)
    db_path = tmp_path / "test.db"
    app = create_app(config_path=cfg, db_url=f"sqlite:///{db_path}")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


def test_holidays_page_blocked_when_pin_locked(pin_app):
    client = pin_app.test_client()
    assert client.get("/holidays").status_code == 403
    resp = client.post("/holidays/add", data={"start_date": "2026-05-01", "end_date": "2026-05-03"})
    assert resp.status_code == 403


def test_holiday_add_after_pin_unlock(pin_app):
    client = pin_app.test_client()
    client.post("/pin/unlock", data={"pin": "1234"})
    resp = client.post(
        "/holidays/add",
        data={
            "start_date": "2026-05-01",
            "end_date": "2026-05-05",
            "person_key": "bob",
            "reason": "School trip",
        },
    )
    assert resp.status_code == 302
    with pin_app.app_context():
        rows = db.session.query(Holiday).all()
        assert len(rows) == 1
        assert rows[0].person_key == "bob"
        assert rows[0].reason == "School trip"
        assert rows[0].start_date == date(2026, 5, 1)
        assert rows[0].end_date == date(2026, 5, 5)


def test_holiday_add_family_wide(pin_app):
    client = pin_app.test_client()
    client.post("/pin/unlock", data={"pin": "1234"})
    client.post(
        "/holidays/add",
        data={"start_date": "2026-05-01", "end_date": "2026-05-01", "person_key": ""},
    )
    with pin_app.app_context():
        rows = db.session.query(Holiday).all()
        assert len(rows) == 1
        assert rows[0].person_key is None


def test_holiday_add_invalid_date_400(pin_app):
    client = pin_app.test_client()
    client.post("/pin/unlock", data={"pin": "1234"})
    resp = client.post("/holidays/add", data={"start_date": "not-a-date", "end_date": "2026-05-01"})
    assert resp.status_code == 400


def test_holiday_add_end_before_start_400(pin_app):
    client = pin_app.test_client()
    client.post("/pin/unlock", data={"pin": "1234"})
    resp = client.post("/holidays/add", data={"start_date": "2026-05-05", "end_date": "2026-05-01"})
    assert resp.status_code == 400


def test_holiday_add_unknown_person_400(pin_app):
    client = pin_app.test_client()
    client.post("/pin/unlock", data={"pin": "1234"})
    resp = client.post(
        "/holidays/add",
        data={"start_date": "2026-05-01", "end_date": "2026-05-01", "person_key": "ghost"},
    )
    assert resp.status_code == 400


def test_holiday_delete(pin_app):
    client = pin_app.test_client()
    client.post("/pin/unlock", data={"pin": "1234"})
    client.post("/holidays/add", data={"start_date": "2026-05-01", "end_date": "2026-05-01"})
    with pin_app.app_context():
        holiday_id = db.session.query(Holiday).one().id

    resp = client.post(f"/holidays/{holiday_id}/delete")
    assert resp.status_code == 302
    with pin_app.app_context():
        assert db.session.query(Holiday).count() == 0


def test_holiday_delete_unknown_404(pin_app):
    client = pin_app.test_client()
    client.post("/pin/unlock", data={"pin": "1234"})
    resp = client.post("/holidays/9999/delete")
    assert resp.status_code == 404
