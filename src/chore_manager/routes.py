from __future__ import annotations

import json
import secrets
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import (
    Blueprint,
    abort,
    current_app,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import func, or_, select

from .achievements import evaluate as evaluate_achievements
from .approvals import (
    InsufficientPointsError,
    available_points,
    points_earned,
    points_in_status,
    request_redemption,
    resolve_redemption,
)
from .audit import audit_log, build_timeline
from .config import AppConfig, FamilyConfig, load_app_config, load_config
from .db import db
from .history import streak
from .models import (
    AdhocChore,
    Adjustment,
    ChoreCompletion,
    ChorePenalty,
    ChoreReassignment,
    ChoreSkip,
    Holiday,
    PersonSetting,
    Redemption,
)
from .schedule import is_scheduled_on
from .stats import (
    best_day_of_week,
    completion_rate_30d,
    daily_points,
    overall_streak,
    per_chore_stats,
    weekly_points,
)

bp = Blueprint("main", __name__)


def _load_app_cfg() -> AppConfig:
    return load_app_config(current_app.config["APP_CONFIG_PATH"])


def _pin_unlocked_for(app_cfg: AppConfig) -> bool:
    if not app_cfg.pin_required:
        return True
    unlocked_at = session.get("pin_unlocked_at")
    if not unlocked_at:
        return False
    return (datetime.now().timestamp() - unlocked_at) < app_cfg.pin_timeout_seconds


def _pin_remaining(app_cfg: AppConfig) -> int:
    if not app_cfg.pin_required:
        return 0
    unlocked_at = session.get("pin_unlocked_at")
    if not unlocked_at:
        return 0
    return max(0, int(app_cfg.pin_timeout_seconds - (datetime.now().timestamp() - unlocked_at)))


@bp.context_processor
def inject_app_config() -> dict:
    app_cfg = _load_app_cfg()
    return {
        "app_config": app_cfg,
        "pin_required": app_cfg.pin_required,
        "pin_unlocked": _pin_unlocked_for(app_cfg),
        "pin_remaining": _pin_remaining(app_cfg),
    }


def _config() -> FamilyConfig:
    return load_config(current_app.config["FAMILY_PATH"])


def _person(person_key: str):
    return next((p for p in _config().people if p.key == person_key), None)


def _chore(chore_key: str):
    return next((c for c in _config().chores if c.key == chore_key), None)


_DICEBEAR_STYLE = "avataaars"
_DICEBEAR_BG = "b6e3f4,c0aede,d1d4f9,ffd5dc,ffdfbf"


def _avatar_url(seed: str) -> str:
    return (
        f"https://api.dicebear.com/9.x/{_DICEBEAR_STYLE}/svg"
        f"?seed={seed}&backgroundColor={_DICEBEAR_BG}"
    )


def _avatar_seed(person_key: str) -> str:
    row = db.session.get(PersonSetting, person_key)
    return row.avatar_seed if row and row.avatar_seed else person_key


def _today() -> date:
    tz = ZoneInfo(current_app.config["TIMEZONE"])
    rollover = _load_app_cfg().day_rollover_hour
    return (datetime.now(tz) - timedelta(hours=rollover)).date()


def _parse_view_date(param: str | None, today: date) -> date:
    if not param:
        return today
    try:
        return date.fromisoformat(param)
    except ValueError:
        return today


def _day_label(view_date: date, today: date) -> str | None:
    delta = (view_date - today).days
    if delta == 0:
        return "Today"
    if delta == -1:
        return "Yesterday"
    if delta == 1:
        return "Tomorrow"
    return None


def _apply_pending_penalties(config: FamilyConfig, yesterday: date) -> None:
    """Apply penalties for incomplete penalty-bearing chores from yesterday."""
    app_cfg = _load_app_cfg()
    if app_cfg.penalty_start_date and yesterday < app_cfg.penalty_start_date:
        return
    for chore in config.chores:
        if not chore.penalty or chore.claim_first:
            continue
        if not is_scheduled_on(chore, yesterday):
            continue
        for person_key in chore.assigned_to:
            existing = db.session.scalar(
                select(ChorePenalty).where(
                    ChorePenalty.chore_key == chore.key,
                    ChorePenalty.person_key == person_key,
                    ChorePenalty.penalty_date == yesterday,
                )
            )
            if existing:
                continue
            completed = db.session.scalar(
                select(ChoreCompletion).where(
                    ChoreCompletion.chore_key == chore.key,
                    ChoreCompletion.person_key == person_key,
                    ChoreCompletion.completed_on == yesterday,
                )
            )
            if completed:
                continue
            skipped = db.session.scalar(
                select(ChoreSkip).where(
                    ChoreSkip.chore_key == chore.key,
                    ChoreSkip.person_key == person_key,
                    ChoreSkip.skip_date == yesterday,
                )
            )
            if skipped:
                continue
            db.session.add(
                ChorePenalty(
                    chore_key=chore.key,
                    person_key=person_key,
                    penalty_date=yesterday,
                    points_deducted=chore.penalty,
                )
            )
            audit_log(f"{person_key} penalised {chore.key} on {yesterday.isoformat()} (-{chore.penalty})")


def _build_item(person_key: str, chore_key: str, view_date: date, today: date) -> dict:
    chore = _chore(chore_key)
    done = (
        db.session.scalar(
            select(ChoreCompletion).where(
                ChoreCompletion.chore_key == chore_key,
                ChoreCompletion.person_key == person_key,
                ChoreCompletion.completed_on == view_date,
            )
        )
        is not None
    )
    skipped = (
        db.session.scalar(
            select(ChoreSkip).where(
                ChoreSkip.chore_key == chore_key,
                ChoreSkip.person_key == person_key,
                ChoreSkip.skip_date == view_date,
            )
        )
        is not None
    )
    reassignment = db.session.scalar(
        select(ChoreReassignment).where(
            ChoreReassignment.chore_key == chore_key,
            ChoreReassignment.new_person_key == person_key,
            ChoreReassignment.on_date == view_date,
        )
    )
    is_reassigned = reassignment is not None
    original_person_key = reassignment.original_person_key if is_reassigned else person_key
    penalised = (
        db.session.scalar(
            select(ChorePenalty).where(
                ChorePenalty.chore_key == chore_key,
                ChorePenalty.person_key == person_key,
                ChorePenalty.penalty_date == view_date,
            )
        )
        is not None
    )
    return {
        "chore_key": chore_key,
        "name": chore.name,
        "points": chore.points,
        "penalty": chore.penalty,
        "penalised": penalised,
        "done": done,
        "skipped": skipped,
        "is_reassigned": is_reassigned,
        "original_person_key": original_person_key,
        "streak": streak(db.session, _config(), chore_key, person_key, today)
        if view_date == today and not is_reassigned
        else 0,
    }


def _holiday_for(person_key: str, on: date) -> Holiday | None:
    """Returns the holiday active on `on` for `person_key`, or None.
    Family-wide holidays (person_key IS NULL) cover everyone."""
    return db.session.scalar(
        select(Holiday)
        .where(
            Holiday.start_date <= on,
            Holiday.end_date >= on,
            (Holiday.person_key == person_key) | (Holiday.person_key.is_(None)),
        )
        .order_by(Holiday.id)
        .limit(1)
    )


def _holidays_active_on(d: date) -> list[Holiday]:
    return list(
        db.session.scalars(
            select(Holiday).where(Holiday.start_date <= d, Holiday.end_date >= d)
        ).all()
    )


_AwayMap = dict[tuple[str, str], str]
_ToMap = dict[str, list[tuple[str, str]]]


def _load_reassignments(d: date) -> tuple[_AwayMap, _ToMap]:
    """Returns (away_map, to_map) for the date.

    away_map: (chore_key, original_person_key) -> new_person_key (chores moved away)
    to_map: new_person_key -> list of (chore_key, original_person_key) (chores received)
    """
    rows = db.session.scalars(select(ChoreReassignment).where(ChoreReassignment.on_date == d)).all()
    away: dict[tuple[str, str], str] = {}
    to: dict[str, list[tuple[str, str]]] = {}
    for r in rows:
        away[(r.chore_key, r.original_person_key)] = r.new_person_key
        to.setdefault(r.new_person_key, []).append((r.chore_key, r.original_person_key))
    return away, to


@bp.get("/")
def index():
    config = _config()
    today = _today()
    viewer = request.cookies.get("viewer")

    view_date = _parse_view_date(request.args.get("date"), today)
    is_today = view_date == today
    prev_date = view_date - timedelta(days=1)
    next_date = view_date + timedelta(days=1)

    yesterday = today - timedelta(days=1)
    _apply_pending_penalties(config, yesterday)
    db.session.commit()

    completion_rows = list(
        db.session.scalars(
            select(ChoreCompletion).where(ChoreCompletion.completed_on == view_date)
        ).all()
    )
    completed_keys = {(row.chore_key, row.person_key) for row in completion_rows}
    claim_winner = {row.chore_key: row.person_key for row in completion_rows}
    skipped_keys = {
        (row.chore_key, row.person_key)
        for row in db.session.scalars(
            select(ChoreSkip).where(ChoreSkip.skip_date == view_date)
        ).all()
    }
    penalised_keys = {
        (row.chore_key, row.person_key)
        for row in db.session.scalars(
            select(ChorePenalty).where(ChorePenalty.penalty_date == view_date)
        ).all()
    }

    visible_people = config.people
    if viewer:
        visible_people = [p for p in config.people if p.key == viewer]

    away_map, to_map = _load_reassignments(view_date)
    chores_by_key = {c.key: c for c in config.chores}

    columns = []
    for person in visible_people:
        holiday = _holiday_for(person.key, view_date)
        chore_items: list[dict] = []
        if holiday is None:
            seen: set[str] = set()

            for chore in config.chores:
                if person.key not in chore.assigned_to:
                    continue
                if not is_scheduled_on(chore, view_date):
                    continue
                if (chore.key, person.key) in away_map:
                    continue
                if chore.claim_first:
                    winner = claim_winner.get(chore.key)
                    if winner is not None and winner != person.key:
                        continue
                seen.add(chore.key)
                chore_items.append(
                    {
                        "chore_key": chore.key,
                        "name": chore.name,
                        "points": chore.points,
                        "penalty": chore.penalty,
                        "penalised": (chore.key, person.key) in penalised_keys,
                        "done": (chore.key, person.key) in completed_keys,
                        "skipped": (chore.key, person.key) in skipped_keys,
                        "is_reassigned": False,
                        "original_person_key": person.key,
                        "claim_first": chore.claim_first,
                        "streak": streak(db.session, config, chore.key, person.key, today)
                        if is_today and not chore.claim_first
                        else 0,
                    }
                )

            for chore_key, original_pk in to_map.get(person.key, []):
                chore = chores_by_key.get(chore_key)
                if chore is None or chore.key in seen:
                    continue
                if not is_scheduled_on(chore, view_date):
                    continue
                seen.add(chore.key)
                chore_items.append(
                    {
                        "chore_key": chore.key,
                        "name": chore.name,
                        "points": chore.points,
                        "penalty": chore.penalty,
                        "penalised": (chore.key, person.key) in penalised_keys,
                        "done": (chore.key, person.key) in completed_keys,
                        "skipped": (chore.key, person.key) in skipped_keys,
                        "is_reassigned": True,
                        "original_person_key": original_pk,
                        "claim_first": False,
                        "streak": 0,
                    }
                )

        columns.append(
            {
                "person": person,
                "chores": chore_items,
                "holiday": holiday,
                "available": available_points(db.session, person.key),
                "earned": points_earned(db.session, person.key),
                "pending": points_in_status(db.session, person.key, "pending"),
            }
        )

    pending = db.session.scalars(
        select(Redemption).where(Redemption.status == "pending").order_by(Redemption.created_at)
    ).all()

    history_by_person: dict[str, list[Redemption]] = {}
    adhoc_by_person: dict[str, list[AdhocChore]] = {}
    for col in columns:
        person_key = col["person"].key
        history_by_person[person_key] = list(
            db.session.scalars(
                select(Redemption)
                .where(Redemption.person_key == person_key)
                .order_by(Redemption.created_at.desc())
                .limit(20)
            ).all()
        )
        adhoc_by_person[person_key] = list(
            db.session.scalars(
                select(AdhocChore)
                .where(
                    AdhocChore.person_key == person_key,
                    func.coalesce(AdhocChore.start_date, AdhocChore.due_date) <= view_date,
                    or_(
                        AdhocChore.completed_at.is_(None),
                        AdhocChore.completed_date == view_date,
                    ),
                )
                .order_by(AdhocChore.due_date, AdhocChore.id)
            ).all()
        )

    avatar_seeds = {
        row.person_key: row.avatar_seed
        for row in db.session.scalars(select(PersonSetting)).all()
        if row.avatar_seed
    }

    template_map = {t.name: t.points for t in config.task_templates}
    adhoc_names = db.session.scalars(
        select(AdhocChore.name).distinct().order_by(AdhocChore.name)
    ).all()
    suggestions_map = dict(template_map)
    for name in adhoc_names:
        if name not in suggestions_map:
            suggestions_map[name] = None
    task_suggestions = [
        {"name": n, "points": p}
        for n, p in sorted(suggestions_map.items(), key=lambda x: x[0].lower())
    ]

    return render_template(
        "today.html",
        today=today,
        view_date=view_date,
        is_today=is_today,
        prev_date=prev_date,
        next_date=next_date,
        day_label=_day_label(view_date, today),
        columns=columns,
        people=config.people,
        viewer=viewer,
        rewards=config.rewards,
        pending=pending if is_today else [],
        history_by_person=history_by_person,
        adhoc_by_person=adhoc_by_person,
        rewards_by_key={r.key: r for r in config.rewards},
        people_by_key={p.key: p for p in config.people},
        avatar_seeds=avatar_seeds,
        avatar_url=_avatar_url,
        task_suggestions=task_suggestions,
    )


def _has_responsibility(chore_key: str, person_key: str, on_date: date, *, chore=None) -> bool:
    """Person is responsible for chore on date if YAML assigns them and not reassigned away,
    or if a reassignment to them exists for that date.

    For `claim_first` chores, any eligible person can claim while no one has yet, and the
    claimer can untick their own claim."""
    if chore is None:
        chore = _chore(chore_key)
    if chore is None:
        return False
    if chore.claim_first and person_key in chore.assigned_to:
        existing = db.session.scalar(
            select(ChoreCompletion).where(
                ChoreCompletion.chore_key == chore_key,
                ChoreCompletion.completed_on == on_date,
            )
        )
        return existing is None or existing.person_key == person_key
    if person_key in chore.assigned_to:
        moved_away = (
            db.session.scalar(
                select(ChoreReassignment).where(
                    ChoreReassignment.chore_key == chore_key,
                    ChoreReassignment.original_person_key == person_key,
                    ChoreReassignment.on_date == on_date,
                )
            )
            is not None
        )
        if not moved_away:
            return True
    return (
        db.session.scalar(
            select(ChoreReassignment).where(
                ChoreReassignment.chore_key == chore_key,
                ChoreReassignment.new_person_key == person_key,
                ChoreReassignment.on_date == on_date,
            )
        )
        is not None
    )


@bp.post("/toggle/<chore_key>/<person_key>")
def toggle(chore_key: str, person_key: str):
    chore = _chore(chore_key)
    person = _person(person_key)
    if chore is None or person is None:
        abort(404)

    today = _today()
    date_str = request.form.get("date")
    toggle_date = date.fromisoformat(date_str) if date_str else today

    if not _has_responsibility(chore_key, person_key, toggle_date, chore=chore):
        abort(404)

    if toggle_date != today:
        app_cfg = _load_app_cfg()
        if not _pin_unlocked_for(app_cfg):
            # PIN expired between page load and tap - re-render cell as locked
            item = _build_item(person_key, chore_key, toggle_date, today)
            return render_template(
                "partials/chore_cell.html",
                item=item,
                person=person,
                is_today=False,
                pin_unlocked=False,
                view_date=toggle_date,
            )

    existing = db.session.scalar(
        select(ChoreCompletion).where(
            ChoreCompletion.chore_key == chore_key,
            ChoreCompletion.person_key == person_key,
            ChoreCompletion.completed_on == toggle_date,
        )
    )
    if existing:
        db.session.delete(existing)
        just_done = False
        audit_log(f"{person_key} unticked {chore_key} on {toggle_date.isoformat()}")
    else:
        db.session.add(
            ChoreCompletion(
                chore_key=chore_key,
                person_key=person_key,
                completed_on=toggle_date,
                points_awarded=chore.points,
            )
        )
        just_done = True
        audit_log(
            f"{person_key} completed {chore_key} (+{chore.points}) on {toggle_date.isoformat()}"
        )
    db.session.commit()

    item = _build_item(person_key, chore_key, toggle_date, today)
    new_available = available_points(db.session, person_key)
    cfg = _config()
    cell = render_template(
        "partials/chore_cell.html",
        item=item,
        person=person,
        is_today=toggle_date == today,
        pin_unlocked=_pin_unlocked_for(_load_app_cfg()),
        view_date=toggle_date,
        people=cfg.people,
        people_by_key={p.key: p for p in cfg.people},
    )
    balance = render_template(
        "partials/points_balance.html",
        person_key=person_key,
        available=new_available,
        pending_pts=points_in_status(db.session, person_key, "pending"),
    )
    rewards = render_template(
        "partials/rewards_panel.html",
        person_key=person_key,
        available=new_available,
        rewards=_config().rewards,
        oob=True,
    )
    response = make_response(cell + balance + rewards)
    if just_done:
        trigger = json.dumps({"chore-completed": {"personKey": person_key}})
        response.headers["HX-Trigger-After-Swap"] = trigger
    if chore.claim_first and len(cfg.people) > 1:
        response.headers["HX-Refresh"] = "true"
    return response


@bp.post("/redeem/<reward_key>/<person_key>")
def redeem(reward_key: str, person_key: str):
    config = _config()
    reward = next((r for r in config.rewards if r.key == reward_key), None)
    person = _person(person_key)
    if reward is None or person is None:
        abort(404)
    try:
        request_redemption(db.session, person_key, reward_key, reward.cost)
        db.session.commit()
    except InsufficientPointsError:
        db.session.rollback()
        return ("Not enough Chorecoins available", 400)
    audit_log(f"{person_key} requested {reward_key} ({reward.cost})")
    return redirect(url_for("main.index"))


@bp.post("/redemption/<int:redemption_id>/approve")
def approve(redemption_id: int):
    if not _pin_unlocked_for(_load_app_cfg()):
        abort(403)
    resolve_redemption(db.session, redemption_id, approve=True)
    db.session.commit()
    audit_log(f"approved redemption {redemption_id}")
    return redirect(url_for("main.index"))


@bp.post("/redemption/<int:redemption_id>/deny")
def deny(redemption_id: int):
    if not _pin_unlocked_for(_load_app_cfg()):
        abort(403)
    resolve_redemption(db.session, redemption_id, approve=False)
    db.session.commit()
    audit_log(f"denied redemption {redemption_id}")
    return redirect(url_for("main.index"))


@bp.post("/skip/<chore_key>/<person_key>")
def skip(chore_key: str, person_key: str):
    if not _pin_unlocked_for(_load_app_cfg()):
        abort(403)
    chore = _chore(chore_key)
    person = _person(person_key)
    if chore is None or person is None:
        abort(404)
    today = _today()
    date_str = request.form.get("date")
    skip_date = date.fromisoformat(date_str) if date_str else today
    if not _has_responsibility(chore_key, person_key, skip_date, chore=chore):
        abort(404)
    people_to_skip = chore.assigned_to if chore.claim_first else [person_key]
    for pk in people_to_skip:
        existing = db.session.scalar(
            select(ChoreSkip).where(
                ChoreSkip.chore_key == chore_key,
                ChoreSkip.person_key == pk,
                ChoreSkip.skip_date == skip_date,
            )
        )
        if not existing:
            db.session.add(ChoreSkip(chore_key=chore_key, person_key=pk, skip_date=skip_date))
    db.session.commit()
    audit_log(f"{person_key} skipped {chore_key} on {skip_date.isoformat()}")
    item = _build_item(person_key, chore_key, skip_date, today)
    cfg = _config()
    response = make_response(
        render_template(
            "partials/chore_cell.html",
            item=item,
            person=person,
            is_today=skip_date == today,
            pin_unlocked=_pin_unlocked_for(_load_app_cfg()),
            view_date=skip_date,
            people=cfg.people,
            people_by_key={p.key: p for p in cfg.people},
        )
    )
    if chore.claim_first:
        response.headers["HX-Refresh"] = "true"
    return response


@bp.post("/unskip/<chore_key>/<person_key>")
def unskip(chore_key: str, person_key: str):
    if not _pin_unlocked_for(_load_app_cfg()):
        abort(403)
    chore = _chore(chore_key)
    person = _person(person_key)
    if chore is None or person is None:
        abort(404)
    today = _today()
    date_str = request.form.get("date")
    skip_date = date.fromisoformat(date_str) if date_str else today
    if not _has_responsibility(chore_key, person_key, skip_date, chore=chore):
        abort(404)
    people_to_unskip = chore.assigned_to if chore.claim_first else [person_key]
    for pk in people_to_unskip:
        existing = db.session.scalar(
            select(ChoreSkip).where(
                ChoreSkip.chore_key == chore_key,
                ChoreSkip.person_key == pk,
                ChoreSkip.skip_date == skip_date,
            )
        )
        if existing:
            db.session.delete(existing)
    db.session.commit()
    audit_log(f"{person_key} unskipped {chore_key} on {skip_date.isoformat()}")
    item = _build_item(person_key, chore_key, skip_date, today)
    cfg = _config()
    response = make_response(
        render_template(
            "partials/chore_cell.html",
            item=item,
            person=person,
            is_today=skip_date == today,
            pin_unlocked=_pin_unlocked_for(_load_app_cfg()),
            view_date=skip_date,
            people=cfg.people,
            people_by_key={p.key: p for p in cfg.people},
        )
    )
    if chore.claim_first:
        response.headers["HX-Refresh"] = "true"
    return response


_ADHOC_NAME_MAX = 200
_ADHOC_POINTS_MAX = 999


@bp.post("/adhoc/add")
def adhoc_add():
    if not _pin_unlocked_for(_load_app_cfg()):
        abort(403)
    person_key = request.form.get("person_key", "")
    name = request.form.get("name", "").strip()[:_ADHOC_NAME_MAX]
    date_str = request.form.get("date")
    try:
        points = min(_ADHOC_POINTS_MAX, max(0, int(request.form.get("points", 5))))
    except ValueError:
        points = 5
    if not name or not person_key or _person(person_key) is None:
        abort(400)
    today = _today()
    try:
        due = date.fromisoformat(date_str) if date_str else today
    except ValueError:
        due = today
    db.session.add(
        AdhocChore(name=name, person_key=person_key, start_date=today, due_date=due, points=points)
    )
    db.session.commit()
    audit_log(f"{person_key} added ad-hoc '{name}' (+{points}) due {due.isoformat()}")
    return redirect(url_for("main.index"))


@bp.post("/adhoc/<int:adhoc_id>/toggle")
def adhoc_toggle(adhoc_id: int):
    task = db.session.get(AdhocChore, adhoc_id)
    if task is None:
        abort(404)
    today = _today()
    date_str = request.form.get("date")
    view_date = date.fromisoformat(date_str) if date_str else today
    if view_date != today and not _pin_unlocked_for(_load_app_cfg()):
        abort(403)
    if task.completed_at:
        task.completed_at = None
        task.completed_date = None
        audit_log(f"{task.person_key} unticked ad-hoc '{task.name}'")
    else:
        task.completed_at = datetime.now(UTC).replace(tzinfo=None)
        task.completed_date = view_date
        audit_log(f"{task.person_key} completed ad-hoc '{task.name}' (+{task.points})")
    db.session.commit()

    just_done = task.completed_at is not None
    new_available = available_points(db.session, task.person_key)
    person = _person(task.person_key)
    cell = render_template(
        "partials/adhoc_cell.html",
        task=task,
        person=person,
        is_today=view_date == today,
        view_date=view_date,
    )
    balance = render_template(
        "partials/points_balance.html",
        person_key=task.person_key,
        available=new_available,
        pending_pts=points_in_status(db.session, task.person_key, "pending"),
    )
    rewards = render_template(
        "partials/rewards_panel.html",
        person_key=task.person_key,
        available=new_available,
        rewards=_config().rewards,
        oob=True,
    )
    response = make_response(cell + balance + rewards)
    if just_done:
        trigger = json.dumps({"chore-completed": {"personKey": task.person_key}})
        response.headers["HX-Trigger-After-Swap"] = trigger
    return response


@bp.post("/adhoc/<int:adhoc_id>/delete")
def adhoc_delete(adhoc_id: int):
    if not _pin_unlocked_for(_load_app_cfg()):
        abort(403)
    task = db.session.get(AdhocChore, adhoc_id)
    if task is None:
        abort(404)
    due = task.due_date
    person_key = task.person_key
    name = task.name
    db.session.delete(task)
    db.session.commit()
    audit_log(f"{person_key} deleted ad-hoc '{name}'")
    today = _today()
    if due == today:
        redirect_url = url_for("main.index")
    else:
        redirect_url = url_for("main.index", date=due.isoformat())
    return redirect(redirect_url)


@bp.post("/reassign/<chore_key>/<original_person>")
def reassign(chore_key: str, original_person: str):
    if not _pin_unlocked_for(_load_app_cfg()):
        abort(403)
    chore = _chore(chore_key)
    if chore is None or original_person not in chore.assigned_to:
        abort(400)
    if chore.claim_first:
        abort(400)
    to_person = request.form.get("to_person", "")
    date_str = request.form.get("date", "")
    try:
        on_date = date.fromisoformat(date_str)
    except ValueError:
        abort(400)
    if _person(to_person) is None:
        abort(400)

    existing = db.session.scalar(
        select(ChoreReassignment).where(
            ChoreReassignment.chore_key == chore_key,
            ChoreReassignment.original_person_key == original_person,
            ChoreReassignment.on_date == on_date,
        )
    )
    if to_person == original_person:
        if existing:
            db.session.delete(existing)
            db.session.commit()
            audit_log(
                f"reassignment of {chore_key} (from {original_person}) cleared on "
                f"{on_date.isoformat()}"
            )
    else:
        if existing:
            existing.new_person_key = to_person
        else:
            db.session.add(
                ChoreReassignment(
                    chore_key=chore_key,
                    original_person_key=original_person,
                    new_person_key=to_person,
                    on_date=on_date,
                )
            )
        db.session.commit()
        audit_log(
            f"reassigned {chore_key} from {original_person} to {to_person} on {on_date.isoformat()}"
        )

    today = _today()
    if on_date == today:
        return redirect(url_for("main.index"))
    return redirect(url_for("main.index", date=on_date.isoformat()))


_ADJUSTMENT_REASON_MAX = 200
_ADJUSTMENT_AMOUNT_MAX = 9999


def _parse_adjustment_amount(form) -> int | None:
    """Returns signed points from either a preset 'points' button or a custom amount + sign."""
    raw = form.get("points")
    if raw is not None:
        try:
            value = int(raw)
        except ValueError:
            return None
        return value if -_ADJUSTMENT_AMOUNT_MAX <= value <= _ADJUSTMENT_AMOUNT_MAX else None

    raw_custom = form.get("custom")
    sign = form.get("custom_sign")
    if raw_custom is None or sign not in {"add", "deduct"}:
        return None
    try:
        magnitude = int(raw_custom)
    except ValueError:
        return None
    if magnitude <= 0 or magnitude > _ADJUSTMENT_AMOUNT_MAX:
        return None
    return magnitude if sign == "add" else -magnitude


@bp.post("/adjustment/add")
def adjustment_add():
    if not _pin_unlocked_for(_load_app_cfg()):
        abort(403)
    person_key = request.form.get("person_key", "")
    if _person(person_key) is None:
        abort(400)
    points = _parse_adjustment_amount(request.form)
    if points is None or points == 0:
        abort(400)
    reason = request.form.get("reason", "").strip()[:_ADJUSTMENT_REASON_MAX] or None
    db.session.add(
        Adjustment(
            person_key=person_key,
            points=points,
            reason=reason,
            created_on=_today(),
        )
    )
    db.session.commit()
    sign = "+" if points >= 0 else ""
    suffix = f": {reason}" if reason else ""
    audit_log(f"adjustment {sign}{points} for {person_key}{suffix}")
    return redirect(url_for("main.index"))


_HOLIDAY_REASON_MAX = 200


@bp.get("/holidays")
def holidays():
    if not _pin_unlocked_for(_load_app_cfg()):
        abort(403)
    cfg = _config()
    rows = list(
        db.session.scalars(
            select(Holiday).order_by(Holiday.start_date.desc(), Holiday.id.desc())
        ).all()
    )
    return render_template(
        "holidays.html",
        holidays=rows,
        people=cfg.people,
        people_by_key={p.key: p for p in cfg.people},
        today=_today(),
    )


@bp.post("/holidays/add")
def holiday_add():
    if not _pin_unlocked_for(_load_app_cfg()):
        abort(403)
    start_str = request.form.get("start_date", "")
    end_str = request.form.get("end_date", "")
    try:
        start = date.fromisoformat(start_str)
        end = date.fromisoformat(end_str)
    except ValueError:
        abort(400)
    if end < start:
        abort(400)
    person_key = request.form.get("person_key", "").strip() or None
    if person_key is not None and _person(person_key) is None:
        abort(400)
    reason = request.form.get("reason", "").strip()[:_HOLIDAY_REASON_MAX] or None
    db.session.add(Holiday(start_date=start, end_date=end, person_key=person_key, reason=reason))
    db.session.commit()
    who = person_key or "everyone"
    audit_log(f"holiday added for {who}: {start.isoformat()} to {end.isoformat()}")
    return redirect(url_for("main.holidays"))


@bp.post("/holidays/<int:holiday_id>/delete")
def holiday_delete(holiday_id: int):
    if not _pin_unlocked_for(_load_app_cfg()):
        abort(403)
    holiday = db.session.get(Holiday, holiday_id)
    if holiday is None:
        abort(404)
    who = holiday.person_key or "everyone"
    start_iso = holiday.start_date.isoformat()
    end_iso = holiday.end_date.isoformat()
    db.session.delete(holiday)
    db.session.commit()
    audit_log(f"holiday deleted for {who}: {start_iso} to {end_iso}")
    return redirect(url_for("main.holidays"))


@bp.get("/avatar/<person_key>")
def avatar_get(person_key: str):
    if _person(person_key) is None:
        abort(404)
    seed = _avatar_seed(person_key)
    return render_template(
        "partials/avatar.html", person_key=person_key, seed=seed, avatar_url=_avatar_url
    )


@bp.get("/avatar/<person_key>/picker")
def avatar_picker(person_key: str):
    if _person(person_key) is None:
        abort(404)
    seeds = [secrets.token_hex(4) for _ in range(20)]
    current = _avatar_seed(person_key)
    return render_template(
        "partials/avatar_picker.html",
        person_key=person_key,
        seeds=seeds,
        current=current,
        avatar_url=_avatar_url,
    )


@bp.post("/avatar/<person_key>")
def avatar_set(person_key: str):
    if _person(person_key) is None:
        abort(404)
    seed = request.form.get("seed", "").strip()
    if not seed:
        abort(400)
    setting = db.session.get(PersonSetting, person_key)
    if setting:
        setting.avatar_seed = seed
    else:
        db.session.add(PersonSetting(person_key=person_key, avatar_seed=seed))
    db.session.commit()
    return render_template(
        "partials/avatar.html", person_key=person_key, seed=seed, avatar_url=_avatar_url
    )


@bp.get("/stats/<person_key>")
def stats(person_key: str):
    person = _person(person_key)
    if person is None:
        abort(404)
    config = _config()
    today = _today()

    chart_days = daily_points(db.session, person_key, today, days=28)
    chart_max = max(max((d["pts"] for d in chart_days), default=1), 1)

    done_30, sched_30 = completion_rate_30d(db.session, config, person_key, today)
    completion_pct = round(done_30 / sched_30 * 100) if sched_30 else 0

    this_week, last_week = weekly_points(db.session, person_key, today)
    streak = overall_streak(db.session, person_key, today)
    total_pts_alltime = points_earned(db.session, person_key)

    chore_rows = per_chore_stats(db.session, config, person_key, today)
    best_day = best_day_of_week(db.session, person_key)
    achievements = evaluate_achievements(db.session, config, person_key)

    avatar_seed = _avatar_seed(person_key)

    return render_template(
        "stats.html",
        person=person,
        today=today,
        chart_days=chart_days,
        chart_max=chart_max,
        completion_pct=completion_pct,
        done_30=done_30,
        sched_30=sched_30,
        this_week=this_week,
        last_week=last_week,
        streak=streak,
        total_pts_alltime=total_pts_alltime,
        chore_rows=chore_rows,
        best_day=best_day,
        achievements=achievements,
        avatar_seed=avatar_seed,
        avatar_url=_avatar_url,
    )


@bp.get("/audit/<person_key>")
def audit(person_key: str):
    person = _person(person_key)
    if person is None:
        abort(404)
    config = _config()
    events = build_timeline(db.session, config, person_key)
    return render_template(
        "audit.html",
        person=person,
        events=events,
        avatar_seed=_avatar_seed(person_key),
        avatar_url=_avatar_url,
    )


@bp.post("/pin/unlock")
def pin_unlock():
    app_cfg = _load_app_cfg()
    entered = request.form.get("pin", "").strip()
    if entered and app_cfg.verify_pin(entered):
        session["pin_unlocked_at"] = datetime.now().timestamp()
    return redirect(request.referrer or url_for("main.index"))


@bp.post("/pin/lock")
def pin_lock():
    session.pop("pin_unlocked_at", None)
    return redirect(request.referrer or url_for("main.index"))


@bp.post("/view-as")
def view_as():
    viewer = request.form.get("viewer", "all")
    response = make_response(redirect(url_for("main.index")))
    if viewer == "all" or _person(viewer) is None:
        response.delete_cookie("viewer")
    else:
        response.set_cookie("viewer", viewer, max_age=60 * 60 * 24 * 365)
    return response
