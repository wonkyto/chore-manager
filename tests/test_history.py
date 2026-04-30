from __future__ import annotations

from datetime import date, timedelta

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


def test_missed_count(app):
    today = date(2026, 4, 30)
    with app.app_context():
        for i in range(0, 5):
            if i != 2:
                _add("dishes", today - timedelta(days=i))
        db.session.commit()
        cfg = app.config["FAMILY"]
        assert missed_count(db.session, cfg, "dishes", "bob", today, window_days=4) == 1
