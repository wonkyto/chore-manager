from __future__ import annotations

from datetime import date, timedelta

from chore_manager.config import FamilyConfig
from chore_manager.db import db
from chore_manager.history import missed_count, streak
from chore_manager.models import ChoreCompletion, ChoreSkip


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


def test_streak_treats_skipped_day_as_transparent(app):
    """A ChoreSkip row (e.g. from a birthday exemption) shouldn't break the streak."""
    today = date(2026, 4, 30)
    with app.app_context():
        _add("dishes", today - timedelta(days=1))
        _add("dishes", today - timedelta(days=2))
        # Skip 3 days ago (e.g. birthday exemption)
        db.session.add(
            ChoreSkip(
                chore_key="dishes",
                person_key="bob",
                skip_date=today - timedelta(days=3),
            )
        )
        _add("dishes", today - timedelta(days=4))
        _add("dishes", today - timedelta(days=5))
        db.session.commit()
        cfg = app.config["FAMILY"]
        # 5 completions either side of the skip; the skip is transparent like a holiday.
        assert streak(db.session, cfg, "dishes", "bob", today) == 4


def test_streak_today_skipped_walks_back_normally(app):
    """If today's scheduled chore is skipped, the streak walks back to the prior occurrence."""
    today = date(2026, 4, 30)
    with app.app_context():
        for i in range(1, 4):
            _add("dishes", today - timedelta(days=i))
        db.session.add(
            ChoreSkip(chore_key="dishes", person_key="bob", skip_date=today)
        )
        db.session.commit()
        cfg = app.config["FAMILY"]
        assert streak(db.session, cfg, "dishes", "bob", today) == 3


def test_missed_count_excludes_skipped_days(app):
    """A skipped scheduled day shouldn't count as missed."""
    today = date(2026, 4, 30)
    with app.app_context():
        # 3 missed days + 1 skipped day in the window
        db.session.add(
            ChoreSkip(
                chore_key="dishes",
                person_key="bob",
                skip_date=today - timedelta(days=2),
            )
        )
        db.session.commit()
        cfg = app.config["FAMILY"]
        # Without the skip, all 30 prior days would be missed.
        # With it, 29 missed.
        assert missed_count(db.session, cfg, "dishes", "bob", today) == 29


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
