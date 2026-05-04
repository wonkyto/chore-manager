from __future__ import annotations

import secrets
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from werkzeug.security import check_password_hash


class Role(StrEnum):
    parent = "parent"
    child = "child"


class Weekday(StrEnum):
    mon = "mon"
    tue = "tue"
    wed = "wed"
    thu = "thu"
    fri = "fri"
    sat = "sat"
    sun = "sun"


class Person(BaseModel):
    key: str
    name: str
    role: Role
    colour: str = "#6b7280"
    avatar: str | None = None


class _ChoreBase(BaseModel):
    key: str
    name: str
    points: int = Field(ge=0)
    penalty: int = Field(default=0, ge=0)
    assigned_to: list[str]
    claim_first: bool = False


class DailyChore(_ChoreBase):
    frequency: Literal["daily"]


class WeeklyChore(_ChoreBase):
    frequency: Literal["weekly"]
    days: list[Weekday]

    @field_validator("days")
    @classmethod
    def days_not_empty(cls, v: list[Weekday]) -> list[Weekday]:
        if not v:
            raise ValueError("weekly chore needs at least one day")
        return v


class FortnightlyChore(_ChoreBase):
    frequency: Literal["fortnightly"]
    days: list[Weekday]
    anchor_date: date

    @field_validator("days")
    @classmethod
    def days_not_empty(cls, v: list[Weekday]) -> list[Weekday]:
        if not v:
            raise ValueError("fortnightly chore needs at least one day")
        return v


class MonthlyChore(_ChoreBase):
    frequency: Literal["monthly"]
    day_of_month: int = Field(ge=1, le=31)


class AnnualChore(_ChoreBase):
    frequency: Literal["annual"]
    month: int = Field(ge=1, le=12)
    day_of_month: int = Field(ge=1, le=31)


class EveryNDaysChore(_ChoreBase):
    frequency: Literal["every_n_days"]
    every_days: int = Field(ge=2)
    anchor_date: date


Chore = Annotated[
    DailyChore | WeeklyChore | FortnightlyChore | MonthlyChore | AnnualChore | EveryNDaysChore,
    Field(discriminator="frequency"),
]


class Reward(BaseModel):
    key: str
    name: str
    cost: int = Field(ge=0)


class TaskTemplate(BaseModel):
    name: str
    points: int = Field(ge=0)


class FamilyConfig(BaseModel):
    people: list[Person]
    chores: list[Chore] = Field(default_factory=list)
    rewards: list[Reward] = Field(default_factory=list)
    task_templates: list[TaskTemplate] = Field(default_factory=list)

    @field_validator("people")
    @classmethod
    def unique_person_keys(cls, v: list[Person]) -> list[Person]:
        keys = [p.key for p in v]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate person keys")
        return v

    @model_validator(mode="after")
    def assignments_reference_known_people(self) -> FamilyConfig:
        keys = {p.key for p in self.people}
        for c in self.chores:
            unknown = set(c.assigned_to) - keys
            if unknown:
                raise ValueError(f"chore {c.key!r} assigned to unknown people: {sorted(unknown)}")
        return self


class AppConfig(BaseModel):
    app_name: str = "Chore Manager"
    timezone: str = "Australia/Sydney"
    parent_pin: str | None = None
    parent_pin_hash: str | None = None
    pin_timeout_seconds: int = 60
    day_rollover_hour: int = Field(default=0, ge=0, le=23)
    penalty_start_date: date | None = None

    def verify_pin(self, candidate: str) -> bool:
        if self.parent_pin_hash:
            try:
                return check_password_hash(self.parent_pin_hash, candidate)
            except ValueError:
                return False
        if self.parent_pin:
            return secrets.compare_digest(self.parent_pin, candidate)
        return False

    @property
    def pin_required(self) -> bool:
        return bool(self.parent_pin or self.parent_pin_hash)


def load_config(path: Path) -> FamilyConfig:
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return FamilyConfig.model_validate(data)


def load_app_config(path: Path) -> AppConfig:
    if not path.exists():
        return AppConfig()
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return AppConfig.model_validate(data)
