from __future__ import annotations

from datetime import date

import pytest

from chore_manager.config import AppConfig
from chore_manager.theme import active_theme, easter_sunday


# Reference values from https://en.wikipedia.org/wiki/List_of_dates_for_Easter
KNOWN_EASTER_SUNDAYS = [
    (2020, date(2020, 4, 12)),
    (2021, date(2021, 4, 4)),
    (2022, date(2022, 4, 17)),
    (2023, date(2023, 4, 9)),
    (2024, date(2024, 3, 31)),
    (2025, date(2025, 4, 20)),
    (2026, date(2026, 4, 5)),
    (2027, date(2027, 3, 28)),
    (2030, date(2030, 4, 21)),
]


@pytest.mark.parametrize("year,expected", KNOWN_EASTER_SUNDAYS)
def test_easter_sunday_matches_known_dates(year, expected):
    assert easter_sunday(year) == expected


def test_active_theme_returns_none_when_nothing_enabled():
    assert active_theme(date(2026, 12, 25), []) is None


def test_christmas_window_inclusive_bounds():
    enabled = ["christmas"]
    assert active_theme(date(2026, 11, 30), enabled) is None
    assert active_theme(date(2026, 12, 1), enabled) == "christmas"
    assert active_theme(date(2026, 12, 25), enabled) == "christmas"
    assert active_theme(date(2026, 12, 26), enabled) == "christmas"
    assert active_theme(date(2026, 12, 27), enabled) is None


def test_halloween_window_inclusive_bounds():
    enabled = ["halloween"]
    assert active_theme(date(2026, 10, 24), enabled) is None
    assert active_theme(date(2026, 10, 25), enabled) == "halloween"
    assert active_theme(date(2026, 10, 31), enabled) == "halloween"
    assert active_theme(date(2026, 11, 1), enabled) is None


def test_easter_window_spans_good_friday_to_easter_monday():
    enabled = ["easter"]
    # Easter Sunday 2026 = Apr 5; Good Friday = Apr 3, Easter Monday = Apr 6.
    assert active_theme(date(2026, 4, 2), enabled) is None
    assert active_theme(date(2026, 4, 3), enabled) == "easter"
    assert active_theme(date(2026, 4, 5), enabled) == "easter"
    assert active_theme(date(2026, 4, 6), enabled) == "easter"
    assert active_theme(date(2026, 4, 7), enabled) is None


def test_disabled_theme_returns_none_inside_window():
    assert active_theme(date(2026, 12, 25), ["halloween"]) is None
    assert active_theme(date(2026, 10, 31), ["christmas"]) is None


def test_appconfig_rejects_unknown_theme_key():
    with pytest.raises(Exception):  # pydantic ValidationError
        AppConfig.model_validate({"enabled_themes": ["diwali"]})


def test_appconfig_accepts_known_themes():
    cfg = AppConfig.model_validate({"enabled_themes": ["easter", "christmas"]})
    assert cfg.enabled_themes == ["easter", "christmas"]
