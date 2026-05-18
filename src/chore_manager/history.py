from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import FamilyConfig
from .models import ChoreCompletion, ChoreSkip, Holiday
from .schedule import is_scheduled_on, previous_occurrence


def _completions_for(session: Session, chore_key: str, person_key: str) -> set[date]:
    rows = session.scalars(
        select(ChoreCompletion.completed_on).where(
            ChoreCompletion.chore_key == chore_key,
            ChoreCompletion.person_key == person_key,
        )
    ).all()
    return set(rows)


def _skips_for(session: Session, chore_key: str, person_key: str) -> set[date]:
    rows = session.scalars(
        select(ChoreSkip.skip_date).where(
            ChoreSkip.chore_key == chore_key,
            ChoreSkip.person_key == person_key,
        )
    ).all()
    return set(rows)


def _on_holiday(holidays: list[Holiday], d: date) -> bool:
    return any(h.start_date <= d <= h.end_date for h in holidays)


def _holidays_for(session: Session, person_key: str) -> list[Holiday]:
    return list(
        session.scalars(
            select(Holiday).where(
                or_(Holiday.person_key == person_key, Holiday.person_key.is_(None))
            )
        ).all()
    )


def streak(
    session: Session,
    config: FamilyConfig,
    chore_key: str,
    person_key: str,
    today: date,
) -> int:
    chore = next((c for c in config.chores if c.key == chore_key), None)
    if chore is None:
        return 0

    completed = _completions_for(session, chore_key, person_key)
    skipped = _skips_for(session, chore_key, person_key)
    holidays = _holidays_for(session, person_key)

    def _exempt(d: date) -> bool:
        return _on_holiday(holidays, d) or d in skipped

    def prev_active(from_date: date) -> date | None:
        cursor = previous_occurrence(chore, from_date)
        while cursor is not None and _exempt(cursor):
            cursor = previous_occurrence(chore, cursor - timedelta(days=1))
        return cursor

    # If today is a scheduled occurrence that hasn't been ticked off yet,
    # don't count it against the streak - start from the previous occurrence.
    # Holiday and skipped days are exempt (the chore wasn't expected).
    if (
        is_scheduled_on(chore, today)
        and today not in completed
        and not _exempt(today)
    ):
        cursor = prev_active(today - timedelta(days=1))
    else:
        cursor = prev_active(today)

    count = 0
    while cursor is not None and cursor in completed:
        count += 1
        cursor = prev_active(cursor - timedelta(days=1))
    return count


def missed_count(
    session: Session,
    config: FamilyConfig,
    chore_key: str,
    person_key: str,
    today: date,
    window_days: int = 30,
) -> int:
    chore = next((c for c in config.chores if c.key == chore_key), None)
    if chore is None:
        return 0

    completed = _completions_for(session, chore_key, person_key)
    skipped = _skips_for(session, chore_key, person_key)
    missed = 0
    for offset in range(1, window_days + 1):
        d = today - timedelta(days=offset)
        if is_scheduled_on(chore, d) and d not in completed and d not in skipped:
            missed += 1
    return missed
