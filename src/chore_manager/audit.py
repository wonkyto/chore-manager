from __future__ import annotations

import logging
import logging.handlers
import os
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import FamilyConfig
from .models import (
    AdhocChore,
    Adjustment,
    ChoreCompletion,
    ChoreReassignment,
    ChoreSkip,
    Redemption,
)


@dataclass
class TimelineEvent:
    when: datetime
    kind: str  # "completion", "adhoc", "adjustment", "redemption", "reassignment", "skip"
    summary: str
    points: int | None = None  # signed; positive earns, negative spends


def _at_noon(d: date) -> datetime:
    return datetime.combine(d, time(12, 0))


def build_timeline(
    session: Session, config: FamilyConfig, person_key: str, limit: int = 200
) -> list[TimelineEvent]:
    chores_by_key = {c.key: c for c in config.chores}
    people_by_key = {p.key: p for p in config.people}
    events: list[TimelineEvent] = []

    for row in session.scalars(
        select(ChoreCompletion).where(ChoreCompletion.person_key == person_key)
    ):
        chore = chores_by_key.get(row.chore_key)
        name = chore.name if chore else row.chore_key
        events.append(
            TimelineEvent(
                when=row.completed_at or _at_noon(row.completed_on),
                kind="completion",
                summary=f"Completed {name}",
                points=row.points_awarded,
            )
        )

    for row in session.scalars(
        select(AdhocChore).where(
            AdhocChore.person_key == person_key, AdhocChore.completed_at.is_not(None)
        )
    ):
        events.append(
            TimelineEvent(
                when=row.completed_at,
                kind="adhoc",
                summary=f"Completed ad-hoc '{row.name}'",
                points=row.points,
            )
        )

    for row in session.scalars(select(Adjustment).where(Adjustment.person_key == person_key)):
        reason = f": {row.reason}" if row.reason else ""
        sign = "+" if row.points >= 0 else ""
        events.append(
            TimelineEvent(
                when=row.created_at or _at_noon(row.created_on),
                kind="adjustment",
                summary=f"Adjustment {sign}{row.points}{reason}",
                points=row.points,
            )
        )

    for row in session.scalars(select(Redemption).where(Redemption.person_key == person_key)):
        status = row.status
        events.append(
            TimelineEvent(
                when=row.created_at,
                kind="redemption",
                summary=f"Requested {row.reward_key} ({status})",
                points=-row.points_cost if status != "denied" else 0,
            )
        )
        if row.resolved_at:
            verb = "Approved" if row.status == "approved" else "Denied"
            events.append(
                TimelineEvent(
                    when=row.resolved_at,
                    kind="redemption",
                    summary=f"{verb} {row.reward_key}",
                )
            )

    for row in session.scalars(
        select(ChoreReassignment).where(
            (ChoreReassignment.original_person_key == person_key)
            | (ChoreReassignment.new_person_key == person_key)
        )
    ):
        chore = chores_by_key.get(row.chore_key)
        chore_name = chore.name if chore else row.chore_key
        original = people_by_key.get(row.original_person_key)
        new = people_by_key.get(row.new_person_key)
        original_name = original.name if original else row.original_person_key
        new_name = new.name if new else row.new_person_key
        if row.original_person_key == person_key:
            summary = f"Sent {chore_name} to {new_name} ({row.on_date.isoformat()})"
        else:
            summary = f"Took {chore_name} from {original_name} ({row.on_date.isoformat()})"
        events.append(
            TimelineEvent(
                when=row.created_at or _at_noon(row.on_date),
                kind="reassignment",
                summary=summary,
            )
        )

    for row in session.scalars(select(ChoreSkip).where(ChoreSkip.person_key == person_key)):
        chore = chores_by_key.get(row.chore_key)
        name = chore.name if chore else row.chore_key
        events.append(
            TimelineEvent(
                when=row.created_at or _at_noon(row.skip_date),
                kind="skip",
                summary=f"Skipped {name} ({row.skip_date.isoformat()})",
            )
        )

    events.sort(key=lambda e: e.when, reverse=True)
    return events[:limit]


_AUDIT_LOGGER_NAME = "chore_manager.audit"


def get_audit_logger() -> logging.Logger:
    return logging.getLogger(_AUDIT_LOGGER_NAME)


def configure_audit_logger(log_path: Path | None) -> None:
    """Configure stdout + optional file logging for audit events.

    Idempotent: clears existing handlers before reattaching."""
    logger = get_audit_logger()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=2_000_000, backupCount=3
        )
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)


def audit_log(message: str) -> None:
    get_audit_logger().info(message)


def resolve_audit_log_path() -> Path | None:
    """Resolve the audit log path from CHORE_AUDIT_LOG env, or None to disable file logging."""
    raw = os.environ.get("CHORE_AUDIT_LOG")
    if not raw:
        return None
    return Path(raw)
