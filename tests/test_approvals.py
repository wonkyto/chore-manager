from __future__ import annotations

from datetime import date

import pytest

from chore_manager.approvals import (
    InsufficientPointsError,
    InvalidStateError,
    available_points,
    gross_points_earned,
    request_redemption,
    resolve_redemption,
)
from chore_manager.db import db
from chore_manager.models import ChoreCompletion, ChorePenalty


def _earn(person_key: str, points: int, on: date | None = None) -> None:
    db.session.add(
        ChoreCompletion(
            chore_key="x",
            person_key=person_key,
            completed_on=on or date(2026, 4, 30),
            points_awarded=points,
        )
    )


def test_balance_starts_at_zero(app):
    with app.app_context():
        assert available_points(db.session, "bob") == 0


def test_completions_increase_available(app):
    with app.app_context():
        _earn("bob", 30)
        db.session.commit()
        assert available_points(db.session, "bob") == 30


def test_pending_redemption_holds_points(app):
    with app.app_context():
        _earn("bob", 30)
        db.session.commit()
        request_redemption(db.session, "bob", "screen", 20)
        db.session.commit()
        assert available_points(db.session, "bob") == 10


def test_redemption_rejected_when_short(app):
    with app.app_context():
        _earn("bob", 5)
        db.session.commit()
        with pytest.raises(InsufficientPointsError):
            request_redemption(db.session, "bob", "screen", 20)


def test_approve_finalises_redemption(app):
    with app.app_context():
        _earn("bob", 30)
        db.session.commit()
        r = request_redemption(db.session, "bob", "screen", 20)
        db.session.commit()
        resolve_redemption(db.session, r.id, approve=True)
        db.session.commit()
        assert available_points(db.session, "bob") == 10


def test_deny_releases_held_points(app):
    with app.app_context():
        _earn("bob", 30)
        db.session.commit()
        r = request_redemption(db.session, "bob", "screen", 20)
        db.session.commit()
        resolve_redemption(db.session, r.id, approve=False)
        db.session.commit()
        assert available_points(db.session, "bob") == 30


def test_penalty_reduces_available_but_not_gross(app):
    with app.app_context():
        _earn("bob", 100)
        db.session.add(
            ChorePenalty(
                chore_key="hw",
                person_key="bob",
                penalty_date=date(2026, 5, 6),
                points_deducted=50,
            )
        )
        db.session.commit()
        assert gross_points_earned(db.session, "bob") == 100
        assert available_points(db.session, "bob") == 50


def test_resolving_twice_raises(app):
    with app.app_context():
        _earn("bob", 30)
        db.session.commit()
        r = request_redemption(db.session, "bob", "screen", 20)
        db.session.commit()
        resolve_redemption(db.session, r.id, approve=True)
        db.session.commit()
        with pytest.raises(InvalidStateError):
            resolve_redemption(db.session, r.id, approve=False)
