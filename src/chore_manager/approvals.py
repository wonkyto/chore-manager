from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AdhocChore, ChoreCompletion, Redemption


class InsufficientPointsError(Exception):
    def __init__(self, person_key: str, cost: int, available: int) -> None:
        super().__init__(
            f"insufficient points for {person_key}: need {cost}, have {available} available"
        )
        self.person_key = person_key
        self.cost = cost
        self.available = available


class InvalidStateError(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(f"redemption already resolved as {status}")
        self.status = status


def _sum_or_zero(session: Session, stmt) -> int:
    val = session.scalar(stmt)
    return int(val or 0)


def points_earned(session: Session, person_key: str) -> int:
    from_scheduled = _sum_or_zero(
        session,
        select(func.coalesce(func.sum(ChoreCompletion.points_awarded), 0)).where(
            ChoreCompletion.person_key == person_key
        ),
    )
    from_adhoc = _sum_or_zero(
        session,
        select(func.coalesce(func.sum(AdhocChore.points), 0)).where(
            AdhocChore.person_key == person_key,
            AdhocChore.completed_at.isnot(None),
        ),
    )
    return from_scheduled + from_adhoc


def points_in_status(session: Session, person_key: str, status: str) -> int:
    return _sum_or_zero(
        session,
        select(func.coalesce(func.sum(Redemption.points_cost), 0)).where(
            Redemption.person_key == person_key,
            Redemption.status == status,
        ),
    )


def available_points(session: Session, person_key: str) -> int:
    earned = points_earned(session, person_key)
    spent = points_in_status(session, person_key, "approved")
    held = points_in_status(session, person_key, "pending")
    return earned - spent - held


def request_redemption(session: Session, person_key: str, reward_key: str, cost: int) -> Redemption:
    available = available_points(session, person_key)
    if available < cost:
        raise InsufficientPointsError(person_key, cost, available)
    r = Redemption(
        person_key=person_key,
        reward_key=reward_key,
        points_cost=cost,
        status="pending",
    )
    session.add(r)
    session.flush()
    return r


def resolve_redemption(
    session: Session, redemption_id: int, *, approve: bool, note: str | None = None
) -> Redemption:
    r = session.get(Redemption, redemption_id)
    if r is None:
        raise LookupError(f"redemption {redemption_id} not found")
    if r.status != "pending":
        raise InvalidStateError(r.status)
    r.status = "approved" if approve else "denied"
    r.resolved_at = datetime.now(UTC).replace(tzinfo=None)
    r.resolved_note = note
    return r
