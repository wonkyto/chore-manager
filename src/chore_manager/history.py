from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import FamilyConfig
from .models import ChoreCompletion
from .schedule import is_scheduled_on, previous_occurrence


def _completions_for(session: Session, chore_key: str, person_key: str) -> set[date]:
    rows = session.scalars(
        select(ChoreCompletion.completed_on).where(
            ChoreCompletion.chore_key == chore_key,
            ChoreCompletion.person_key == person_key,
        )
    ).all()
    return set(rows)


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

    # If today is a scheduled occurrence that hasn't been ticked off yet,
    # don't count it against the streak - start from the previous occurrence.
    if is_scheduled_on(chore, today) and today not in completed:
        cursor = previous_occurrence(chore, today - timedelta(days=1))
    else:
        cursor = previous_occurrence(chore, today)

    count = 0
    while cursor is not None and cursor in completed:
        count += 1
        cursor = previous_occurrence(chore, cursor - timedelta(days=1))
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
    missed = 0
    for offset in range(1, window_days + 1):
        d = today - timedelta(days=offset)
        if is_scheduled_on(chore, d) and d not in completed:
            missed += 1
    return missed
