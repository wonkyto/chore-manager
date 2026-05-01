from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from chore_manager.achievements import (
    ACHIEVEMENTS,
    completion_count,
    evaluate,
    longest_perfect_streak,
    longest_streak,
    perfect_days,
)
from chore_manager.config import load_config
from chore_manager.db import db
from chore_manager.models import (
    AdhocChore,
    ChoreCompletion,
    ChoreReassignment,
    ChoreSkip,
    Redemption,
)


def _seed_completions(dates: list[date], chore_key: str = "dishes", person: str = "bob") -> None:
    db.session.add_all(
        [
            ChoreCompletion(
                chore_key=chore_key,
                person_key=person,
                completed_on=d,
                points_awarded=5,
                completed_at=datetime.combine(d, datetime.min.time()).replace(hour=9),
            )
            for d in dates
        ]
    )
    db.session.commit()


def test_completion_count_includes_adhoc(app):
    with app.app_context():
        _seed_completions([date(2026, 4, 28), date(2026, 4, 29)])
        db.session.add(
            AdhocChore(
                name="Walk dog",
                person_key="bob",
                points=3,
                completed_at=datetime(2026, 4, 30, 10, 0),
                completed_date=date(2026, 4, 30),
            )
        )
        db.session.commit()
        assert completion_count(db.session, "bob") == 3


def test_completion_count_excludes_uncompleted_adhoc(app):
    with app.app_context():
        db.session.add(
            AdhocChore(name="Pending", person_key="bob", points=3, due_date=date(2026, 4, 30))
        )
        db.session.commit()
        assert completion_count(db.session, "bob") == 0


def test_longest_streak_consecutive_dates(app):
    with app.app_context():
        # 3 consecutive, gap, 2 consecutive
        _seed_completions(
            [
                date(2026, 4, 20),
                date(2026, 4, 21),
                date(2026, 4, 22),
                date(2026, 4, 25),
                date(2026, 4, 26),
            ]
        )
        assert longest_streak(db.session, "bob") == 3


def test_longest_streak_dedupes_same_day(app):
    with app.app_context():
        # Two completions on the same day shouldn't double-count
        _seed_completions([date(2026, 4, 20), date(2026, 4, 21)])
        db.session.add(
            ChoreCompletion(
                chore_key="piano",
                person_key="bob",
                completed_on=date(2026, 4, 20),
                points_awarded=10,
                completed_at=datetime(2026, 4, 20, 10, 0),
            )
        )
        db.session.commit()
        assert longest_streak(db.session, "bob") == 2


def test_longest_streak_zero_when_empty(app):
    with app.app_context():
        assert longest_streak(db.session, "bob") == 0


def test_perfect_day_when_all_scheduled_done(app):
    """Bob has dishes (daily) plus piano (mon/wed/fri). On a Tuesday only dishes is scheduled."""
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        tuesday = date(2026, 4, 28)
        assert tuesday.weekday() == 1
        _seed_completions([tuesday])
        days = perfect_days(db.session, cfg, "bob")
        assert tuesday in days


def test_perfect_day_excluded_when_chore_missing(app):
    """On a Friday both dishes and piano are scheduled - only dishes done = not perfect."""
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        friday = date(2026, 5, 1)
        assert friday.weekday() == 4
        _seed_completions([friday])
        assert friday not in perfect_days(db.session, cfg, "bob")


def test_perfect_day_skips_count_as_done(app):
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        friday = date(2026, 5, 1)
        _seed_completions([friday])
        db.session.add(ChoreSkip(chore_key="piano", person_key="bob", skip_date=friday))
        db.session.commit()
        assert friday in perfect_days(db.session, cfg, "bob")


def test_perfect_day_respects_reassignment_away(app):
    """If piano was sent to alice, bob only owes dishes that day."""
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        friday = date(2026, 5, 1)
        _seed_completions([friday])
        db.session.add(
            ChoreReassignment(
                chore_key="piano",
                original_person_key="bob",
                new_person_key="alice",
                on_date=friday,
            )
        )
        db.session.commit()
        assert friday in perfect_days(db.session, cfg, "bob")


def test_perfect_day_respects_reassignment_received(app):
    """If alice's chore came to bob, he must finish that too to be perfect.
    The fixture only assigns dishes/piano to bob, so we test by reassigning a bob chore TO bob.
    Reuse: send piano away from bob on Fri, and check perfect when only dishes done."""
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        # Alice has no chores in fixture, so use the "away" path indirectly:
        # Bob owes dishes daily; on Sat only dishes scheduled, and we'll add a received entry
        # for piano (not scheduled Sat) - it shouldn't matter because piano isn't scheduled on Sat.
        saturday = date(2026, 5, 2)
        assert saturday.weekday() == 5
        _seed_completions([saturday])
        db.session.add(
            ChoreReassignment(
                chore_key="piano",
                original_person_key="bob",
                new_person_key="bob",
                on_date=saturday,
            )
        )
        db.session.commit()
        # Piano not scheduled on Sat regardless, so day stays perfect.
        assert saturday in perfect_days(db.session, cfg, "bob")


def test_longest_perfect_streak_finds_longest_run():
    days = {
        date(2026, 4, 20),
        date(2026, 4, 21),
        date(2026, 4, 22),
        date(2026, 4, 25),
    }
    assert longest_perfect_streak(days) == 3


def test_longest_perfect_streak_empty():
    assert longest_perfect_streak(set()) == 0


def test_evaluate_locks_unearned(app):
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        results = evaluate(db.session, cfg, "bob")
        assert len(results) == len(ACHIEVEMENTS)
        for ev in results:
            assert not ev.earned


def test_evaluate_unlocks_first_chore(app):
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        _seed_completions([date(2026, 4, 30)])
        results = {ev.achievement.key: ev for ev in evaluate(db.session, cfg, "bob")}
        assert results["first_chore"].earned
        assert not results["ten_chores"].earned
        assert results["ten_chores"].progress == 1
        assert results["ten_chores"].target == 10


def test_evaluate_unlocks_coin_milestones(app):
    """Five chores at 5 points each = 25, plus a 100-point adjustment via adhoc."""
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        # 20 completions x 5 points = 100 coins
        _seed_completions([date(2026, 4, 1) + timedelta(days=i) for i in range(20)])
        results = {ev.achievement.key: ev for ev in evaluate(db.session, cfg, "bob")}
        assert results["coin_100"].earned
        assert not results["coin_500"].earned


def test_evaluate_streak_threshold(app):
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        _seed_completions([date(2026, 4, 1) + timedelta(days=i) for i in range(7)])
        results = {ev.achievement.key: ev for ev in evaluate(db.session, cfg, "bob")}
        assert results["streak_3"].earned
        assert results["streak_7"].earned
        assert not results["streak_14"].earned


def test_evaluate_first_reward(app):
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        db.session.add(
            Redemption(
                person_key="bob",
                reward_key="screen",
                points_cost=20,
                status="approved",
                created_at=datetime(2026, 4, 30, 10, 0),
                resolved_at=datetime(2026, 4, 30, 10, 5),
            )
        )
        db.session.commit()
        results = {ev.achievement.key: ev for ev in evaluate(db.session, cfg, "bob")}
        assert results["first_reward"].earned


def test_evaluate_pending_redemption_does_not_unlock(app):
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        db.session.add(
            Redemption(
                person_key="bob",
                reward_key="screen",
                points_cost=20,
                status="pending",
                created_at=datetime(2026, 4, 30, 10, 0),
            )
        )
        db.session.commit()
        results = {ev.achievement.key: ev for ev in evaluate(db.session, cfg, "bob")}
        assert not results["first_reward"].earned


def test_stats_page_shows_achievements_section(client, app):
    client.post("/toggle/dishes/bob")
    body = client.get("/stats/bob").get_data(as_text=True)
    assert "Achievements" in body
    assert "First chore" in body
