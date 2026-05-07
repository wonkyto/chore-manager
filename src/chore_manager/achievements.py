from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .approvals import gross_points_earned
from .config import FamilyConfig
from .models import (
    AdhocChore,
    Adjustment,
    ChoreCompletion,
    ChoreReassignment,
    ChoreSkip,
    Redemption,
)
from .schedule import is_scheduled_on

Tier = Literal["bronze", "silver", "gold"]


@dataclass(frozen=True, slots=True)
class Achievement:
    key: str
    name: str
    description: str
    tier: Tier


@dataclass(frozen=True, slots=True)
class EvaluatedAchievement:
    achievement: Achievement
    earned: bool
    progress: int | None
    target: int | None


ACHIEVEMENTS: list[Achievement] = [
    Achievement("first_chore", "First chore", "Complete one chore", "bronze"),
    Achievement("ten_chores", "Ten chores", "Complete 10 chores", "bronze"),
    Achievement("fifty_chores", "Fifty chores", "Complete 50 chores", "silver"),
    Achievement("century", "Centurion", "Complete 100 chores", "gold"),
    Achievement("coin_100", "100 Chorecoins", "Earn 100 Chorecoins", "bronze"),
    Achievement("coin_500", "500 Chorecoins", "Earn 500 Chorecoins", "silver"),
    Achievement("coin_1000", "1000 Chorecoins", "Earn 1000 Chorecoins", "gold"),
    Achievement("streak_3", "Three-day streak", "Complete chores 3 days in a row", "bronze"),
    Achievement("streak_7", "Week-long streak", "Complete chores 7 days in a row", "silver"),
    Achievement("streak_14", "Fortnight streak", "Complete chores 14 days in a row", "gold"),
    Achievement("perfect_day", "Perfect day", "Complete every scheduled chore in a day", "bronze"),
    Achievement(
        "perfect_monday",
        "Marvellous Monday",
        "Complete every scheduled chore on a Monday",
        "silver",
    ),
    Achievement("perfect_week", "Perfect week", "Seven perfect days in a row", "gold"),
    Achievement("first_reward", "First reward", "Have a redemption approved", "bronze"),
]


def completion_count(session: Session, person_key: str) -> int:
    """Total chores completed (scheduled + completed ad-hoc)."""
    sched = session.scalar(
        select(func.count())
        .select_from(ChoreCompletion)
        .where(ChoreCompletion.person_key == person_key)
    )
    adhoc = session.scalar(
        select(func.count())
        .select_from(AdhocChore)
        .where(
            AdhocChore.person_key == person_key,
            AdhocChore.completed_at.is_not(None),
        )
    )
    return int(sched or 0) + int(adhoc or 0)


def _birthday_dates(session: Session, person_key: str) -> set[date]:
    return set(
        session.scalars(
            select(Adjustment.created_on).where(
                Adjustment.person_key == person_key,
                Adjustment.reason == "Birthday",
            )
        ).all()
    )


def _completion_dates(session: Session, person_key: str) -> set[date]:
    sched = set(
        session.scalars(
            select(ChoreCompletion.completed_on).where(ChoreCompletion.person_key == person_key)
        ).all()
    )
    adhoc = {
        d
        for d in session.scalars(
            select(AdhocChore.completed_date).where(
                AdhocChore.person_key == person_key,
                AdhocChore.completed_at.is_not(None),
            )
        ).all()
        if d is not None
    }
    return sched | adhoc | _birthday_dates(session, person_key)


def longest_streak(session: Session, person_key: str) -> int:
    """Longest run of consecutive days with at least one completion (any kind)."""
    dates = sorted(_completion_dates(session, person_key))
    if not dates:
        return 0
    longest = 1
    current = 1
    for i in range(1, len(dates)):
        if dates[i] - dates[i - 1] == timedelta(days=1):
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


def perfect_days(session: Session, config: FamilyConfig, person_key: str) -> set[date]:
    """Dates where the person finished every chore expected of them.

    Skipped chores count as resolved. Reassignments shift expected work between people."""
    completed_by_chore: dict[str, set[date]] = defaultdict(set)
    completion_dates: set[date] = set()
    for chore_key, completed_on in session.execute(
        select(ChoreCompletion.chore_key, ChoreCompletion.completed_on).where(
            ChoreCompletion.person_key == person_key
        )
    ).all():
        completed_by_chore[chore_key].add(completed_on)
        completion_dates.add(completed_on)

    skipped_by_chore: dict[str, set[date]] = defaultdict(set)
    for chore_key, skip_date in session.execute(
        select(ChoreSkip.chore_key, ChoreSkip.skip_date).where(ChoreSkip.person_key == person_key)
    ).all():
        skipped_by_chore[chore_key].add(skip_date)

    away: set[tuple[str, date]] = set()
    for chore_key, on_date in session.execute(
        select(ChoreReassignment.chore_key, ChoreReassignment.on_date).where(
            ChoreReassignment.original_person_key == person_key
        )
    ).all():
        away.add((chore_key, on_date))

    received: dict[date, list[str]] = defaultdict(list)
    for chore_key, on_date in session.execute(
        select(ChoreReassignment.chore_key, ChoreReassignment.on_date).where(
            ChoreReassignment.new_person_key == person_key
        )
    ).all():
        received[on_date].append(chore_key)

    candidate_dates = completion_dates | set(received.keys())
    chore_by_key = {c.key: c for c in config.chores}
    perfect: set[date] = set()
    for d in candidate_dates:
        expected: list[str] = []
        for chore in config.chores:
            if person_key not in chore.assigned_to:
                continue
            if not is_scheduled_on(chore, d):
                continue
            if (chore.key, d) in away:
                continue
            expected.append(chore.key)
        for chore_key in received.get(d, []):
            chore = chore_by_key.get(chore_key)
            if chore is not None and is_scheduled_on(chore, d):
                expected.append(chore_key)
        if not expected:
            continue
        if all(d in completed_by_chore[ck] or d in skipped_by_chore[ck] for ck in expected):
            perfect.add(d)
    return perfect


def longest_perfect_streak(perfect: set[date]) -> int:
    if not perfect:
        return 0
    dates = sorted(perfect)
    longest = 1
    current = 1
    for i in range(1, len(dates)):
        if dates[i] - dates[i - 1] == timedelta(days=1):
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


def _has_approved_redemption(session: Session, person_key: str) -> bool:
    return (
        session.scalar(
            select(Redemption.id)
            .where(
                Redemption.person_key == person_key,
                Redemption.status == "approved",
            )
            .limit(1)
        )
        is not None
    )


def evaluate(session: Session, config: FamilyConfig, person_key: str) -> list[EvaluatedAchievement]:
    completions = completion_count(session, person_key)
    coins = gross_points_earned(session, person_key)
    streak = longest_streak(session, person_key)
    perfect = perfect_days(session, config, person_key)
    perfect_streak = longest_perfect_streak(perfect)
    has_perfect_monday = any(d.weekday() == 0 for d in perfect)
    has_first_reward = _has_approved_redemption(session, person_key)

    counter_targets: dict[str, tuple[int, int]] = {
        "first_chore": (completions, 1),
        "ten_chores": (completions, 10),
        "fifty_chores": (completions, 50),
        "century": (completions, 100),
        "coin_100": (coins, 100),
        "coin_500": (coins, 500),
        "coin_1000": (coins, 1000),
        "streak_3": (streak, 3),
        "streak_7": (streak, 7),
        "streak_14": (streak, 14),
        "perfect_week": (perfect_streak, 7),
    }
    flags: dict[str, bool] = {
        "perfect_day": bool(perfect),
        "perfect_monday": has_perfect_monday,
        "first_reward": has_first_reward,
    }

    out: list[EvaluatedAchievement] = []
    for ach in ACHIEVEMENTS:
        if ach.key in counter_targets:
            current, target = counter_targets[ach.key]
            out.append(
                EvaluatedAchievement(
                    achievement=ach,
                    earned=current >= target,
                    progress=min(current, target),
                    target=target,
                )
            )
        else:
            out.append(
                EvaluatedAchievement(
                    achievement=ach,
                    earned=flags[ach.key],
                    progress=None,
                    target=None,
                )
            )
    return out
