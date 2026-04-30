from __future__ import annotations

from datetime import date, timedelta

from chore_manager.config import FamilyConfig
from chore_manager.db import db
from chore_manager.history import missed_count, streak
from chore_manager.models import ChoreCompletion


def _add(chore_key: str, when: date, points: int = 5) -> None:
    db.session.add(
        ChoreCompletion(
            chore_key=chore_key,
            person_key="bob",
            completed_on=when,
            points_awarded=points,
        )
    )


def test_daily_streak_counts_consecutive_days(app):
    today = date(2026, 4, 30)
    with app.app_context():
        for i in range(5):
            _add("dishes", today - timedelta(days=i))
        db.session.commit()
        cfg = app.config["FAMILY"]
        assert streak(db.session, cfg, "dishes", "bob", today) == 5


def test_daily_streak_breaks_on_missed_day(app):
    today = date(2026, 4, 30)
    with app.app_context():
        _add("dishes", today)
        _add("dishes", today - timedelta(days=1))
        _add("dishes", today - timedelta(days=3))
        db.session.commit()
        cfg = app.config["FAMILY"]
        assert streak(db.session, cfg, "dishes", "bob", today) == 2


def test_today_not_done_yet_keeps_streak(app):
    today = date(2026, 4, 30)
    with app.app_context():
        for i in range(1, 4):
            _add("dishes", today - timedelta(days=i))
        db.session.commit()
        cfg = app.config["FAMILY"]
        assert streak(db.session, cfg, "dishes", "bob", today) == 3


def test_weekly_streak_across_scheduled_days(app):
    today = date(2026, 5, 8)
    with app.app_context():
        for d in [date(2026, 5, 4), date(2026, 5, 6), date(2026, 5, 8)]:
            _add("piano", d, points=10)
        db.session.commit()
        cfg = app.config["FAMILY"]
        assert streak(db.session, cfg, "piano", "bob", today) == 3


def test_weekly_streak_skips_missing_scheduled_day(app):
    today = date(2026, 5, 8)
    with app.app_context():
        _add("piano", date(2026, 5, 8), points=10)
        _add("piano", date(2026, 5, 4), points=10)
        db.session.commit()
        cfg = app.config["FAMILY"]
        assert streak(db.session, cfg, "piano", "bob", today) == 1


def _config_with(chore_spec: dict) -> FamilyConfig:
    return FamilyConfig.model_validate(
        {
            "people": [{"key": "bob", "name": "Bob", "role": "child"}],
            "chores": [{**chore_spec, "assigned_to": ["bob"]}],
        }
    )


def test_monthly_streak_walks_back_across_months(app):
    today = date(2026, 5, 15)
    cfg = _config_with(
        {
            "key": "rent",
            "name": "Rent",
            "points": 5,
            "frequency": "monthly",
            "day_of_month": 15,
        }
    )
    with app.app_context():
        for d in [date(2026, 5, 15), date(2026, 4, 15), date(2026, 3, 15), date(2026, 2, 15)]:
            _add("rent", d)
        db.session.commit()
        assert streak(db.session, cfg, "rent", "bob", today) == 4


def test_annual_streak_walks_back_across_years(app):
    today = date(2026, 4, 1)
    cfg = _config_with(
        {
            "key": "smoke",
            "name": "Smoke alarms",
            "points": 5,
            "frequency": "annual",
            "month": 4,
            "day_of_month": 1,
        }
    )
    with app.app_context():
        for d in [date(2026, 4, 1), date(2025, 4, 1), date(2024, 4, 1)]:
            _add("smoke", d)
        db.session.commit()
        assert streak(db.session, cfg, "smoke", "bob", today) == 3


def test_monthly_streak_breaks_on_missing_month(app):
    today = date(2026, 5, 15)
    cfg = _config_with(
        {
            "key": "rent",
            "name": "Rent",
            "points": 5,
            "frequency": "monthly",
            "day_of_month": 15,
        }
    )
    with app.app_context():
        # Skip April; March and May completed.
        for d in [date(2026, 5, 15), date(2026, 3, 15)]:
            _add("rent", d)
        db.session.commit()
        assert streak(db.session, cfg, "rent", "bob", today) == 1


def test_missed_count(app):
    today = date(2026, 4, 30)
    with app.app_context():
        for i in range(0, 5):
            if i != 2:
                _add("dishes", today - timedelta(days=i))
        db.session.commit()
        cfg = app.config["FAMILY"]
        assert missed_count(db.session, cfg, "dishes", "bob", today, window_days=4) == 1
