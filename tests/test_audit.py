from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from pathlib import Path

from chore_manager.audit import (
    audit_log,
    build_timeline,
    configure_audit_logger,
    get_audit_logger,
)
from chore_manager.config import load_config
from chore_manager.db import db
from chore_manager.models import (
    AdhocChore,
    Adjustment,
    ChoreCompletion,
    ChoreReassignment,
    ChoreSkip,
    Redemption,
)


def test_audit_page_renders(client, app):
    resp = client.get("/audit/bob")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Activity" in body


def test_audit_page_404_for_unknown_person(client):
    assert client.get("/audit/ghost").status_code == 404


def test_audit_page_lists_completion(client, app):
    client.post("/toggle/dishes/bob")
    body = client.get("/audit/bob").get_data(as_text=True)
    assert "Completed Dishes" in body


def test_timeline_orders_events_desc(app):
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        db.session.add_all(
            [
                ChoreCompletion(
                    chore_key="dishes",
                    person_key="bob",
                    completed_on=date(2026, 4, 28),
                    points_awarded=5,
                    completed_at=datetime(2026, 4, 28, 9, 0),
                ),
                ChoreCompletion(
                    chore_key="dishes",
                    person_key="bob",
                    completed_on=date(2026, 4, 30),
                    points_awarded=5,
                    completed_at=datetime(2026, 4, 30, 9, 0),
                ),
                Adjustment(
                    person_key="bob",
                    points=10,
                    reason="bonus",
                    created_on=date(2026, 4, 29),
                    created_at=datetime(2026, 4, 29, 14, 0),
                ),
            ]
        )
        db.session.commit()

        events = build_timeline(db.session, cfg, "bob")
        assert [e.kind for e in events] == ["completion", "adjustment", "completion"]
        assert events[0].when > events[1].when > events[2].when


def test_timeline_includes_all_kinds(app):
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        now = datetime(2026, 4, 30, 10, 0)
        db.session.add_all(
            [
                ChoreCompletion(
                    chore_key="dishes",
                    person_key="bob",
                    completed_on=date(2026, 4, 30),
                    points_awarded=5,
                    completed_at=now,
                ),
                AdhocChore(
                    name="Walk dog",
                    person_key="bob",
                    points=3,
                    completed_at=datetime(2026, 4, 30, 10, 5),
                    completed_date=date(2026, 4, 30),
                ),
                Adjustment(
                    person_key="bob",
                    points=-2,
                    reason="missed bin",
                    created_on=date(2026, 4, 30),
                    created_at=datetime(2026, 4, 30, 10, 10),
                ),
                Redemption(
                    person_key="bob",
                    reward_key="screen",
                    points_cost=20,
                    status="approved",
                    created_at=datetime(2026, 4, 30, 10, 15),
                    resolved_at=datetime(2026, 4, 30, 10, 20),
                ),
                ChoreReassignment(
                    chore_key="dishes",
                    original_person_key="bob",
                    new_person_key="alice",
                    on_date=date(2026, 4, 30),
                    created_at=datetime(2026, 4, 30, 10, 25),
                ),
                ChoreSkip(
                    chore_key="dishes",
                    person_key="bob",
                    skip_date=date(2026, 4, 30),
                    created_at=datetime(2026, 4, 30, 10, 30),
                ),
            ]
        )
        db.session.commit()

        events = build_timeline(db.session, cfg, "bob")
        kinds = {e.kind for e in events}
        assert kinds == {"completion", "adhoc", "adjustment", "redemption", "reassignment", "skip"}


def test_timeline_only_shows_target_person(app):
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        db.session.add(
            ChoreCompletion(
                chore_key="dishes",
                person_key="alice",
                completed_on=date(2026, 4, 30),
                points_awarded=5,
                completed_at=datetime(2026, 4, 30, 9, 0),
            )
        )
        db.session.commit()
        events = build_timeline(db.session, cfg, "bob")
        assert events == []


def test_audit_logger_writes_to_file(tmp_path: Path):
    log_path = tmp_path / "audit.log"
    configure_audit_logger(log_path)
    audit_log("test event")
    for h in get_audit_logger().handlers:
        h.flush()
    assert log_path.exists()
    content = log_path.read_text()
    assert "test event" in content
    # Tear down so this doesn't bleed into other tests
    configure_audit_logger(None)


def test_audit_logger_no_file_path_means_stdout_only(caplog):
    configure_audit_logger(None)
    logger = get_audit_logger()
    # Stream handler exists, no file handler.
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0], logging.StreamHandler)


def test_toggle_writes_audit_log(client, app, tmp_path):
    log_path = tmp_path / "audit.log"
    configure_audit_logger(log_path)
    try:
        client.post("/toggle/dishes/bob")
        for h in get_audit_logger().handlers:
            h.flush()
        content = log_path.read_text()
        assert "bob completed dishes" in content
    finally:
        configure_audit_logger(None)


# Reset module-level logger state at import to avoid polluting other tests.
configure_audit_logger(None)


def test_utc_completed_at_handled(app):
    """A timezone-aware completed_at shouldn't crash sorting."""
    with app.app_context():
        cfg = load_config(Path(app.config["FAMILY_PATH"]))
        db.session.add(
            ChoreCompletion(
                chore_key="dishes",
                person_key="bob",
                completed_on=date(2026, 4, 30),
                points_awarded=5,
                completed_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
        db.session.commit()
        events = build_timeline(db.session, cfg, "bob")
        assert len(events) == 1
