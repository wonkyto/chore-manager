from __future__ import annotations

from pathlib import Path

import pytest

from chore_manager.app import create_app

CONFIG_YAML = """
people:
  - key: alice
    name: Alice
    role: parent
    colour: "#4f46e5"
  - key: bob
    name: Bob
    role: child
    colour: "#10b981"
chores:
  - key: dishes
    name: Dishes
    points: 5
    frequency: daily
    assigned_to: [bob]
  - key: piano
    name: Piano
    points: 10
    frequency: weekly
    days: [mon, wed, fri]
    assigned_to: [bob]
rewards:
  - key: screen
    name: 30 minutes screen time
    cost: 20
"""


@pytest.fixture
def app(tmp_path: Path):
    cfg = tmp_path / "family.yaml"
    cfg.write_text(CONFIG_YAML)
    db_path = tmp_path / "test.db"
    app = create_app(config_path=cfg, db_url=f"sqlite:///{db_path}")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    return app


@pytest.fixture
def client(app):
    return app.test_client()
