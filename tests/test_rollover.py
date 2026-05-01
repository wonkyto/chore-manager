from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from chore_manager.app import create_app
from chore_manager.config import AppConfig, load_app_config


def test_app_config_default_rollover_is_zero():
    cfg = AppConfig()
    assert cfg.day_rollover_hour == 0


def test_app_config_loads_rollover(tmp_path: Path):
    p = tmp_path / "app.yaml"
    p.write_text("day_rollover_hour: 4\n")
    cfg = load_app_config(p)
    assert cfg.day_rollover_hour == 4


def test_app_config_rejects_out_of_range(tmp_path: Path):
    p = tmp_path / "app.yaml"
    p.write_text("day_rollover_hour: 25\n")
    with pytest.raises(Exception):  # noqa: B017 - pydantic validation error
        load_app_config(p)


_FAMILY = """
people:
  - key: alice
    name: Alice
    role: parent
    colour: "#4f46e5"
chores: []
rewards: []
"""


def _make_app(tmp_path: Path, rollover: int):
    cfg = tmp_path / "family.yaml"
    cfg.write_text(_FAMILY)
    (tmp_path / "app.yaml").write_text(f"day_rollover_hour: {rollover}\n")
    db_path = tmp_path / "test.db"
    app = create_app(config_path=cfg, db_url=f"sqlite:///{db_path}")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


def test_today_before_rollover_returns_yesterday(tmp_path: Path):
    app = _make_app(tmp_path, rollover=4)
    tz = ZoneInfo(app.config["TIMEZONE"])
    fake_now = datetime(2026, 5, 1, 2, 30, tzinfo=tz)  # 2:30am

    from chore_manager import routes

    class _FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now

    with patch.object(routes, "datetime", _FakeDT), app.app_context():
        assert routes._today().isoformat() == "2026-04-30"


def test_today_after_rollover_returns_today(tmp_path: Path):
    app = _make_app(tmp_path, rollover=4)
    tz = ZoneInfo(app.config["TIMEZONE"])
    fake_now = datetime(2026, 5, 1, 5, 0, tzinfo=tz)  # 5am

    from chore_manager import routes

    class _FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now

    with patch.object(routes, "datetime", _FakeDT), app.app_context():
        assert routes._today().isoformat() == "2026-05-01"


def test_today_with_zero_rollover_uses_midnight(tmp_path: Path):
    app = _make_app(tmp_path, rollover=0)
    tz = ZoneInfo(app.config["TIMEZONE"])
    fake_now = datetime(2026, 5, 1, 0, 1, tzinfo=tz)  # 1 minute past midnight

    from chore_manager import routes

    class _FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now

    with patch.object(routes, "datetime", _FakeDT), app.app_context():
        assert routes._today().isoformat() == "2026-05-01"
