from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import FamilyConfig
from .models import AdhocChore, Adjustment, ChoreCompletion
from .schedule import is_scheduled_on

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def daily_points(session: Session, person_key: str, today: date, days: int = 28) -> list[dict]:
    """Points earned per day for the last N days, oldest first."""
    start = today - timedelta(days=days - 1)

    sched_rows = session.execute(
        select(ChoreCompletion.completed_on, func.sum(ChoreCompletion.points_awarded))
        .where(
            ChoreCompletion.person_key == person_key,
            ChoreCompletion.completed_on >= start,
            ChoreCompletion.completed_on <= today,
        )
        .group_by(ChoreCompletion.completed_on)
    ).all()

    adhoc_rows = session.execute(
        select(AdhocChore.completed_date, func.sum(AdhocChore.points))
        .where(
            AdhocChore.person_key == person_key,
            AdhocChore.completed_date >= start,
            AdhocChore.completed_date <= today,
            AdhocChore.completed_at.isnot(None),
        )
        .group_by(AdhocChore.completed_date)
    ).all()

    adj_rows = session.execute(
        select(Adjustment.created_on, func.sum(Adjustment.points))
        .where(
            Adjustment.person_key == person_key,
            Adjustment.created_on >= start,
            Adjustment.created_on <= today,
        )
        .group_by(Adjustment.created_on)
    ).all()

    pts_map: dict[date, int] = defaultdict(int)
    for d, pts in sched_rows:
        pts_map[d] += int(pts or 0)
    for d, pts in adhoc_rows:
        if d is not None:
            pts_map[d] += int(pts or 0)
    for d, pts in adj_rows:
        pts_map[d] += int(pts or 0)

    result = []
    for i in range(days):
        d = start + timedelta(days=i)
        result.append(
            {
                "date": d,
                "pts": pts_map.get(d, 0),
                "is_today": d == today,
                "week_label": _DAY_SHORT[d.weekday()] if d.weekday() == 0 else None,
            }
        )
    return result


def completion_rate_30d(
    session: Session, config: FamilyConfig, person_key: str, today: date
) -> tuple[int, int]:
    """Returns (completed, scheduled) over the last 30 days, not including today."""
    rows = session.execute(
        select(ChoreCompletion.chore_key, ChoreCompletion.completed_on).where(
            ChoreCompletion.person_key == person_key,
            ChoreCompletion.completed_on >= today - timedelta(days=30),
            ChoreCompletion.completed_on < today,
        )
    ).all()
    done_set = {(r.chore_key, r.completed_on) for r in rows}

    scheduled = 0
    done = 0
    for chore in config.chores:
        if person_key not in chore.assigned_to:
            continue
        for offset in range(1, 31):
            d = today - timedelta(days=offset)
            if is_scheduled_on(chore, d):
                scheduled += 1
                if (chore.key, d) in done_set:
                    done += 1

    return done, scheduled


def per_chore_stats(
    session: Session, config: FamilyConfig, person_key: str, today: date, window: int = 30
) -> list[dict]:
    """Per-chore breakdown for the last N days."""
    rows = session.execute(
        select(ChoreCompletion.chore_key, ChoreCompletion.completed_on).where(
            ChoreCompletion.person_key == person_key,
            ChoreCompletion.completed_on >= today - timedelta(days=window),
            ChoreCompletion.completed_on <= today,
        )
    ).all()
    done_by_chore: dict[str, set[date]] = defaultdict(set)
    for r in rows:
        done_by_chore[r.chore_key].add(r.completed_on)

    result = []
    for chore in config.chores:
        if person_key not in chore.assigned_to:
            continue
        scheduled = sum(
            1
            for offset in range(window + 1)
            if is_scheduled_on(chore, today - timedelta(days=offset))
        )
        done = len(done_by_chore.get(chore.key, set()))
        result.append(
            {
                "name": chore.name,
                "points": chore.points,
                "done": done,
                "scheduled": scheduled,
                "rate": round(done / scheduled * 100) if scheduled > 0 else None,
            }
        )

    # Chores with no scheduled occurrences in the window (e.g. annual chores)
    # sort to the bottom.
    return sorted(result, key=lambda x: (x["rate"] is None, -(x["rate"] or 0)))


def best_day_of_week(session: Session, person_key: str) -> str | None:
    """Day of week with the most completions, all-time."""
    dates = session.scalars(
        select(ChoreCompletion.completed_on).where(ChoreCompletion.person_key == person_key)
    ).all()
    if not dates:
        return None
    counts: dict[int, int] = defaultdict(int)
    for d in dates:
        counts[d.weekday()] += 1
    return _DAY_NAMES[max(counts, key=lambda k: counts[k])]


def weekly_points(session: Session, person_key: str, today: date) -> tuple[int, int]:
    """Returns (this_week, last_week) points. Week starts Monday."""
    week_start = today - timedelta(days=today.weekday())
    last_start = week_start - timedelta(days=7)

    def _sum(start: date, end: date) -> int:
        sched = (
            session.scalar(
                select(func.coalesce(func.sum(ChoreCompletion.points_awarded), 0)).where(
                    ChoreCompletion.person_key == person_key,
                    ChoreCompletion.completed_on >= start,
                    ChoreCompletion.completed_on < end,
                )
            )
            or 0
        )
        adhoc = (
            session.scalar(
                select(func.coalesce(func.sum(AdhocChore.points), 0)).where(
                    AdhocChore.person_key == person_key,
                    AdhocChore.completed_date >= start,
                    AdhocChore.completed_date < end,
                    AdhocChore.completed_at.isnot(None),
                )
            )
            or 0
        )
        adj = (
            session.scalar(
                select(func.coalesce(func.sum(Adjustment.points), 0)).where(
                    Adjustment.person_key == person_key,
                    Adjustment.created_on >= start,
                    Adjustment.created_on < end,
                )
            )
            or 0
        )
        return int(sched) + int(adhoc) + int(adj)

    return _sum(week_start, today + timedelta(days=1)), _sum(last_start, week_start)


def overall_streak(session: Session, person_key: str, today: date) -> int:
    """Consecutive days ending today (or yesterday) with at least one completion."""
    sched_dates = set(
        session.scalars(
            select(ChoreCompletion.completed_on).where(ChoreCompletion.person_key == person_key)
        ).all()
    )
    adhoc_dates = {
        d
        for d in session.scalars(
            select(AdhocChore.completed_date).where(
                AdhocChore.person_key == person_key,
                AdhocChore.completed_at.isnot(None),
            )
        ).all()
        if d is not None
    }
    birthday_dates = set(
        session.scalars(
            select(Adjustment.created_on).where(
                Adjustment.person_key == person_key,
                Adjustment.reason == "Birthday",
            )
        ).all()
    )
    all_dates = sched_dates | adhoc_dates | birthday_dates

    cursor = today
    if cursor not in all_dates:
        cursor -= timedelta(days=1)

    count = 0
    while cursor in all_dates:
        count += 1
        cursor -= timedelta(days=1)
    return count
