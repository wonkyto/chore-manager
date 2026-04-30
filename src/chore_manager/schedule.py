from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from .config import (
    AnnualChore,
    Chore,
    DailyChore,
    EveryNDaysChore,
    FamilyConfig,
    FortnightlyChore,
    MonthlyChore,
    Weekday,
    WeeklyChore,
)

_WEEKDAYS = [
    Weekday.mon,
    Weekday.tue,
    Weekday.wed,
    Weekday.thu,
    Weekday.fri,
    Weekday.sat,
    Weekday.sun,
]


def weekday_for(d: date) -> Weekday:
    return _WEEKDAYS[d.weekday()]


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _clamp_dom(day: int, year: int, month: int) -> int:
    """Clamp day-of-month to the actual length of the month.

    day_of_month=31 always lands on the last day of the month;
    day_of_month=29 in February of a non-leap year lands on the 28th.
    """
    return min(day, calendar.monthrange(year, month)[1])


@dataclass(frozen=True, slots=True)
class ScheduledChore:
    chore_key: str
    name: str
    points: int
    person_key: str


def is_scheduled_on(chore: Chore, on: date) -> bool:
    match chore:
        case DailyChore():
            return True
        case WeeklyChore():
            return weekday_for(on) in chore.days
        case FortnightlyChore():
            if weekday_for(on) not in chore.days:
                return False
            weeks = (_week_start(on) - _week_start(chore.anchor_date)).days // 7
            return weeks % 2 == 0
        case MonthlyChore():
            return on.day == _clamp_dom(chore.day_of_month, on.year, on.month)
        case AnnualChore():
            if on.month != chore.month:
                return False
            return on.day == _clamp_dom(chore.day_of_month, on.year, chore.month)
        case EveryNDaysChore():
            delta = (on - chore.anchor_date).days
            return delta >= 0 and delta % chore.every_days == 0
    return False


def previous_occurrence(chore: Chore, on: date) -> date | None:
    """Most recent scheduled date <= on, or None if there isn't one yet."""
    match chore:
        case DailyChore():
            return on
        case WeeklyChore():
            for offset in range(7):
                d = on - timedelta(days=offset)
                if weekday_for(d) in chore.days:
                    return d
            return None
        case FortnightlyChore():
            for offset in range(14):
                d = on - timedelta(days=offset)
                if is_scheduled_on(chore, d):
                    return d
            return None
        case MonthlyChore():
            target = _clamp_dom(chore.day_of_month, on.year, on.month)
            if on.day >= target:
                return on.replace(day=target)
            y, m = (on.year - 1, 12) if on.month == 1 else (on.year, on.month - 1)
            return date(y, m, _clamp_dom(chore.day_of_month, y, m))
        case AnnualChore():
            target_this = _clamp_dom(chore.day_of_month, on.year, chore.month)
            this_year = date(on.year, chore.month, target_this)
            if this_year <= on:
                return this_year
            target_prev = _clamp_dom(chore.day_of_month, on.year - 1, chore.month)
            return date(on.year - 1, chore.month, target_prev)
        case EveryNDaysChore():
            delta = (on - chore.anchor_date).days
            if delta < 0:
                return None
            return on - timedelta(days=delta % chore.every_days)
    return None


def chores_for(config: FamilyConfig, on: date) -> list[ScheduledChore]:
    out: list[ScheduledChore] = []
    for chore in config.chores:
        if not is_scheduled_on(chore, on):
            continue
        for person_key in chore.assigned_to:
            out.append(
                ScheduledChore(
                    chore_key=chore.key,
                    name=chore.name,
                    points=chore.points,
                    person_key=person_key,
                )
            )
    return out
