from __future__ import annotations

from datetime import date

from chore_manager.config import FamilyConfig, Weekday
from chore_manager.schedule import chores_for, weekday_for


def _config(chores: list[dict]) -> FamilyConfig:
    return FamilyConfig.model_validate(
        {
            "people": [
                {"key": "alice", "name": "Alice", "role": "parent"},
                {"key": "bob", "name": "Bob", "role": "child"},
            ],
            "chores": chores,
        }
    )


def test_daily_chore_appears_every_day():
    cfg = _config(
        [
            {
                "key": "dishes",
                "name": "Dishes",
                "points": 5,
                "frequency": "daily",
                "assigned_to": ["alice"],
            }
        ]
    )
    items = chores_for(cfg, date(2026, 4, 30))
    assert len(items) == 1
    assert items[0].chore_key == "dishes"


def test_weekly_chore_only_on_scheduled_days():
    cfg = _config(
        [
            {
                "key": "piano",
                "name": "Piano",
                "points": 10,
                "frequency": "weekly",
                "days": ["mon", "wed"],
                "assigned_to": ["bob"],
            }
        ]
    )
    monday = date(2026, 5, 4)
    tuesday = date(2026, 5, 5)
    wednesday = date(2026, 5, 6)
    assert len(chores_for(cfg, monday)) == 1
    assert len(chores_for(cfg, tuesday)) == 0
    assert len(chores_for(cfg, wednesday)) == 1


def test_chore_assigned_to_multiple_people():
    cfg = _config(
        [
            {
                "key": "tidy",
                "name": "Tidy",
                "points": 3,
                "frequency": "daily",
                "assigned_to": ["alice", "bob"],
            }
        ]
    )
    items = chores_for(cfg, date(2026, 4, 30))
    assert {i.person_key for i in items} == {"alice", "bob"}


def test_weekday_mapping():
    assert weekday_for(date(2026, 5, 4)) == Weekday.mon
    assert weekday_for(date(2026, 5, 10)) == Weekday.sun


def test_assignment_to_unknown_person_rejected():
    import pytest

    with pytest.raises(ValueError, match="unknown people"):
        FamilyConfig.model_validate(
            {
                "people": [{"key": "alice", "name": "Alice", "role": "parent"}],
                "chores": [
                    {
                        "key": "x",
                        "name": "X",
                        "points": 1,
                        "frequency": "daily",
                        "assigned_to": ["ghost"],
                    }
                ],
            }
        )
