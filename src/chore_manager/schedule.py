from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .config import DailyChore, FamilyConfig, Weekday, WeeklyChore

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


@dataclass(frozen=True, slots=True)
class ScheduledChore:
    chore_key: str
    name: str
    points: int
    person_key: str


def is_scheduled_on(chore: DailyChore | WeeklyChore, on: date) -> bool:
    if isinstance(chore, DailyChore):
        return True
    if isinstance(chore, WeeklyChore):
        return weekday_for(on) in chore.days
    return False


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
