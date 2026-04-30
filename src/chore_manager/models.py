from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class ChoreCompletion(Base):
    __tablename__ = "chore_completion"
    __table_args__ = (
        UniqueConstraint("chore_key", "person_key", "completed_on", name="uq_completion"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chore_key: Mapped[str] = mapped_column(String(64), index=True)
    person_key: Mapped[str] = mapped_column(String(64), index=True)
    completed_on: Mapped[date] = mapped_column(Date, index=True)
    points_awarded: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class AdhocChore(Base):
    __tablename__ = "adhoc_chore"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    person_key: Mapped[str] = mapped_column(String(64), index=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    points: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class ChoreSkip(Base):
    __tablename__ = "chore_skip"
    __table_args__ = (UniqueConstraint("chore_key", "person_key", "skip_date", name="uq_skip"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chore_key: Mapped[str] = mapped_column(String(64), index=True)
    person_key: Mapped[str] = mapped_column(String(64), index=True)
    skip_date: Mapped[date] = mapped_column(Date, index=True)


class PersonSetting(Base):
    __tablename__ = "person_setting"

    person_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    avatar_seed: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Redemption(Base):
    __tablename__ = "redemption"

    id: Mapped[int] = mapped_column(primary_key=True)
    person_key: Mapped[str] = mapped_column(String(64), index=True)
    reward_key: Mapped[str] = mapped_column(String(64))
    points_cost: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
