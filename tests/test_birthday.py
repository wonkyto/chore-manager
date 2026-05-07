from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from chore_manager.achievements import _birthday_dates, _completion_dates
from chore_manager.approvals import available_points, gross_points_earned
from chore_manager.config import Person, Role, is_birthday
from chore_manager.db import db
from chore_manager.models import Adjustment, ChoreCompletion, ChoreSkip


# --- config validation ---

def test_is_birthday_matches_month_and_day():
    p = Person(key="bob", name="Bob", role=Role.child, birthday="05-15")
    assert is_birthday(p, date(2026, 5, 15))
    assert is_birthday(p, date(2027, 5, 15))
    assert not is_birthday(p, date(2026, 5, 14))
    assert not is_birthday(p, date(2026, 6, 15))


def test_is_birthday_none_never_matches():
    p = Person(key="bob", name="Bob", role=Role.child)
    assert not is_birthday(p, date(2026, 5, 15))


def test_birthday_invalid_format_rejected():
    with pytest.raises(ValueError):
        Person(key="bob", name="Bob", role=Role.child, birthday="15-05")  # wrong order
    with pytest.raises(ValueError):
        Person(key="bob", name="Bob", role=Role.child, birthday="2026-05-15")  # full date
    with pytest.raises(ValueError):
        Person(key="bob", name="Bob", role=Role.child, birthday="02-30")  # impossible date


# --- birthday exemption route (via HTTP) ---

BIRTHDAY_CONFIG = """
people:
  - key: alice
    name: Alice
    role: parent
    colour: "#4f46e5"
  - key: bob
    name: Bob
    role: child
    colour: "#10b981"
    birthday: "04-29"
chores:
  - key: dishes
    name: Dishes
    points: 5
    frequency: daily
    assigned_to: [bob]
  - key: piano
    name: Piano
    points: 10
    frequency: weekly
    days: [wed]
    assigned_to: [bob]
rewards:
  - key: screen
    name: Screen time
    cost: 20
"""


@pytest.fixture
def birthday_app(tmp_path: Path):
    from chore_manager.app import create_app
    cfg = tmp_path / "family.yaml"
    cfg.write_text(BIRTHDAY_CONFIG)
    db_path = tmp_path / "test.db"
    app = create_app(config_path=cfg, db_url=f"sqlite:///{db_path}")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


def test_birthday_exemption_skips_chores_and_awards_points(birthday_app):
    """Birthday exemption auto-skips chores and awards points for the birthday date."""
    from chore_manager.config import load_config
    from chore_manager.routes import _apply_birthday_exemptions

    with birthday_app.app_context():
        # 2026-04-29 is a Wednesday - both dishes (daily) and piano (wed) are scheduled
        birthday = date(2026, 4, 29)
        cfg = load_config(Path(birthday_app.config["FAMILY_PATH"]))
        _apply_birthday_exemptions(cfg, birthday)
        db.session.commit()

        skips = db.session.scalars(
            db.select(ChoreSkip).where(ChoreSkip.person_key == "bob", ChoreSkip.skip_date == birthday)
        ).all()
        skipped_keys = {s.chore_key for s in skips}
        assert "dishes" in skipped_keys
        assert "piano" in skipped_keys

        # 5 (dishes) + 10 (piano) = 15 points awarded
        adj = db.session.scalar(
            db.select(Adjustment).where(
                Adjustment.person_key == "bob",
                Adjustment.reason == "Birthday",
                Adjustment.created_on == birthday,
            )
        )
        assert adj is not None
        assert adj.points == 15
        assert gross_points_earned(db.session, "bob") == 15


def test_birthday_exemption_not_double_applied(birthday_app):
    """Calling the exemption twice for the same birthday doesn't duplicate adjustments."""
    from chore_manager.config import load_config
    from chore_manager.routes import _apply_birthday_exemptions

    with birthday_app.app_context():
        birthday = date(2026, 4, 29)
        cfg = load_config(Path(birthday_app.config["FAMILY_PATH"]))
        _apply_birthday_exemptions(cfg, birthday)
        db.session.commit()
        _apply_birthday_exemptions(cfg, birthday)
        db.session.commit()

        count = db.session.scalar(
            db.select(db.func.count()).select_from(Adjustment).where(
                Adjustment.person_key == "bob",
                Adjustment.reason == "Birthday",
            )
        )
        assert count == 1


def test_birthday_exemption_excludes_already_completed_chores(birthday_app):
    """Points aren't awarded for chores already completed on the birthday."""
    from chore_manager.config import load_config
    from chore_manager.routes import _apply_birthday_exemptions

    with birthday_app.app_context():
        birthday = date(2026, 4, 29)
        db.session.add(
            ChoreCompletion(
                chore_key="dishes",
                person_key="bob",
                completed_on=birthday,
                points_awarded=5,
                completed_at=datetime(2026, 4, 29, 18, 0),
            )
        )
        db.session.commit()

        cfg = load_config(Path(birthday_app.config["FAMILY_PATH"]))
        _apply_birthday_exemptions(cfg, birthday)
        db.session.commit()

        adj = db.session.scalar(
            db.select(Adjustment).where(
                Adjustment.person_key == "bob",
                Adjustment.reason == "Birthday",
            )
        )
        # Only piano (10pts) awarded - dishes already done
        assert adj.points == 10


# --- streak preservation ---

def test_birthday_date_counts_toward_streak(app):
    """A birthday exemption day preserves the streak even with no completions."""
    with app.app_context():
        # Seed completions on consecutive days, with a birthday gap in the middle
        for d in [date(2026, 4, 27), date(2026, 4, 28)]:
            db.session.add(
                ChoreCompletion(
                    chore_key="dishes", person_key="bob",
                    completed_on=d, points_awarded=5,
                    completed_at=datetime.combine(d, datetime.min.time()),
                )
            )
        # Birthday exemption on 2026-04-29 (no actual completion)
        db.session.add(
            Adjustment(person_key="bob", points=5, reason="Birthday", created_on=date(2026, 4, 29))
        )
        db.session.add(
            ChoreCompletion(
                chore_key="dishes", person_key="bob",
                completed_on=date(2026, 4, 30), points_awarded=5,
                completed_at=datetime(2026, 4, 30, 9, 0),
            )
        )
        db.session.commit()

        dates = _completion_dates(db.session, "bob")
        assert date(2026, 4, 29) in dates

        birthday_days = _birthday_dates(db.session, "bob")
        assert date(2026, 4, 29) in birthday_days
