from __future__ import annotations

from datetime import date

import pytest

from chore_manager.approvals import (
    InsufficientPointsError,
    InvalidStateError,
    available_points,
    request_redemption,
    resolve_redemption,
)
from chore_manager.db import db
from chore_manager.models import ChoreCompletion


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
