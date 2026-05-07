from __future__ import annotations

from datetime import date

from chore_manager.config import FamilyConfig, Weekday
from chore_manager.schedule import chores_for, is_scheduled_on, previous_occurrence, weekday_for


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


def _single_chore(spec: dict):
    cfg = _config([{**spec, "assigned_to": ["alice"]}])
    return cfg.chores[0]


def test_fortnightly_fires_on_anchor_week_only():
    chore = _single_chore(
        {
            "key": "bins",
            "name": "Bins",
            "points": 5,
            "frequency": "fortnightly",
            "days": ["tue"],
            "anchor_date": "2026-05-05",  # Tuesday
        }
    )
    assert is_scheduled_on(chore, date(2026, 5, 5))  # anchor week
    assert not is_scheduled_on(chore, date(2026, 5, 12))  # off week
    assert is_scheduled_on(chore, date(2026, 5, 19))  # on week
    assert not is_scheduled_on(chore, date(2026, 4, 28))  # off week before anchor
    assert is_scheduled_on(chore, date(2026, 4, 21))  # on week before anchor


def test_fortnightly_only_on_listed_days_within_on_week():
    chore = _single_chore(
        {
            "key": "bins",
            "name": "Bins",
            "points": 5,
            "frequency": "fortnightly",
            "days": ["tue"],
            "anchor_date": "2026-05-05",
        }
    )
    # Same on-week as anchor, but Wednesday isn't a listed day
    assert not is_scheduled_on(chore, date(2026, 5, 6))


def test_monthly_fires_on_specific_day_of_month():
    chore = _single_chore(
        {
            "key": "rent",
            "name": "Rent",
            "points": 5,
            "frequency": "monthly",
            "day_of_month": 15,
        }
    )
    assert is_scheduled_on(chore, date(2026, 5, 15))
    assert not is_scheduled_on(chore, date(2026, 5, 14))
    assert is_scheduled_on(chore, date(2026, 6, 15))


def test_monthly_day_31_clamps_to_last_day_of_short_months():
    chore = _single_chore(
        {
            "key": "filter",
            "name": "Filter",
            "points": 5,
            "frequency": "monthly",
            "day_of_month": 31,
        }
    )
    # February: clamps to 28 in 2026 (non-leap)
    assert is_scheduled_on(chore, date(2026, 2, 28))
    assert not is_scheduled_on(chore, date(2026, 2, 27))
    # April has 30 days
    assert is_scheduled_on(chore, date(2026, 4, 30))
    # March has 31
    assert is_scheduled_on(chore, date(2026, 3, 31))


def test_monthly_day_29_in_february_leap_vs_non_leap():
    chore = _single_chore(
        {
            "key": "x",
            "name": "X",
            "points": 5,
            "frequency": "monthly",
            "day_of_month": 29,
        }
    )
    # 2024 is a leap year
    assert is_scheduled_on(chore, date(2024, 2, 29))
    # 2026 is not - clamps to 28
    assert is_scheduled_on(chore, date(2026, 2, 28))
    assert not is_scheduled_on(chore, date(2026, 2, 27))


def test_annual_fires_on_specified_month_and_day():
    chore = _single_chore(
        {
            "key": "smoke",
            "name": "Smoke alarms",
            "points": 5,
            "frequency": "annual",
            "month": 4,
            "day_of_month": 1,
        }
    )
    assert is_scheduled_on(chore, date(2026, 4, 1))
    assert not is_scheduled_on(chore, date(2026, 4, 2))
    assert not is_scheduled_on(chore, date(2026, 5, 1))
    assert is_scheduled_on(chore, date(2027, 4, 1))


def test_annual_feb_29_clamps_in_non_leap_years():
    chore = _single_chore(
        {
            "key": "x",
            "name": "X",
            "points": 5,
            "frequency": "annual",
            "month": 2,
            "day_of_month": 29,
        }
    )
    assert is_scheduled_on(chore, date(2024, 2, 29))
    assert is_scheduled_on(chore, date(2026, 2, 28))


def test_every_n_days_from_anchor():
    chore = _single_chore(
        {
            "key": "water",
            "name": "Water plants",
            "points": 5,
            "frequency": "every_n_days",
            "every_days": 3,
            "anchor_date": "2026-04-30",
        }
    )
    assert is_scheduled_on(chore, date(2026, 4, 30))
    assert not is_scheduled_on(chore, date(2026, 5, 1))
    assert not is_scheduled_on(chore, date(2026, 5, 2))
    assert is_scheduled_on(chore, date(2026, 5, 3))
    assert is_scheduled_on(chore, date(2026, 5, 6))
    # Before anchor, never fires
    assert not is_scheduled_on(chore, date(2026, 4, 29))


def test_previous_occurrence_monthly_walks_to_prior_month():
    chore = _single_chore(
        {
            "key": "rent",
            "name": "Rent",
            "points": 5,
            "frequency": "monthly",
            "day_of_month": 15,
        }
    )
    # Before this month's occurrence, returns last month's
    assert previous_occurrence(chore, date(2026, 5, 14)) == date(2026, 4, 15)
    # On the day, returns today
    assert previous_occurrence(chore, date(2026, 5, 15)) == date(2026, 5, 15)
    # Across year boundary
    assert previous_occurrence(chore, date(2026, 1, 14)) == date(2025, 12, 15)


def test_previous_occurrence_annual_walks_to_prior_year():
    chore = _single_chore(
        {
            "key": "smoke",
            "name": "Smoke alarms",
            "points": 5,
            "frequency": "annual",
            "month": 4,
            "day_of_month": 1,
        }
    )
    assert previous_occurrence(chore, date(2026, 3, 31)) == date(2025, 4, 1)
    assert previous_occurrence(chore, date(2026, 4, 1)) == date(2026, 4, 1)
    assert previous_occurrence(chore, date(2026, 12, 31)) == date(2026, 4, 1)


def test_start_date_prevents_chore_appearing_before_it():
    chore = _single_chore(
        {
            "key": "hw",
            "name": "Homework",
            "points": 0,
            "frequency": "weekly",
            "days": ["mon", "tue", "wed", "thu"],
            "start_date": "2026-05-07",
        }
    )
    assert not is_scheduled_on(chore, date(2026, 5, 6))   # Wednesday before start
    assert not is_scheduled_on(chore, date(2026, 5, 4))   # Monday before start
    assert is_scheduled_on(chore, date(2026, 5, 7))        # Thursday on start date
    assert is_scheduled_on(chore, date(2026, 5, 11))       # Monday after start


def test_start_date_does_not_block_chore_on_start_day():
    chore = _single_chore(
        {
            "key": "hw",
            "name": "Homework",
            "points": 0,
            "frequency": "daily",
            "start_date": "2026-05-07",
        }
    )
    assert is_scheduled_on(chore, date(2026, 5, 7))
    assert not is_scheduled_on(chore, date(2026, 5, 6))


def test_previous_occurrence_every_n_days_aligns_to_anchor():
    chore = _single_chore(
        {
            "key": "water",
            "name": "Water",
            "points": 5,
            "frequency": "every_n_days",
            "every_days": 3,
            "anchor_date": "2026-04-30",
        }
    )
    assert previous_occurrence(chore, date(2026, 5, 4)) == date(2026, 5, 3)
    assert previous_occurrence(chore, date(2026, 4, 29)) is None
