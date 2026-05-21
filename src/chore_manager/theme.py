from __future__ import annotations

from datetime import date, timedelta

THEMES: tuple[str, ...] = ("easter", "halloween", "christmas")


def easter_sunday(year: int) -> date:
    """Easter Sunday for a Gregorian year via Meeus/Jones/Butcher."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def active_theme(today: date, enabled: list[str] | tuple[str, ...]) -> str | None:
    """Return the theme key whose window covers `today`, or None.

    Windows:
      christmas: Dec 1 - Dec 26
      halloween: Oct 25 - Oct 31
      easter:    Good Friday (Easter Sunday - 2) through Easter Monday (+1)
    """
    enabled_set = set(enabled)

    if "christmas" in enabled_set and today.month == 12 and 1 <= today.day <= 26:
        return "christmas"

    if "halloween" in enabled_set and today.month == 10 and 25 <= today.day <= 31:
        return "halloween"

    if "easter" in enabled_set:
        es = easter_sunday(today.year)
        if (es - timedelta(days=2)) <= today <= (es + timedelta(days=1)):
            return "easter"

    return None
