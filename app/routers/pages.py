"""Server-rendered pages and the HTMX partials they swap in."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from app import schemas
from app.config import settings
from app.deps import AUTH_COOKIE, DbSession, OptionalUser, PageUser
from app.errors import ConflictError
from app.models import User
from app.security import create_access_token
from app.seed import DEMO_EMAIL, DEMO_PASSWORD
from app.services import analytics, exercises, users, workouts
from app.templating import kg, render, short_date

PAGE_SIZE = 10

router = APIRouter(include_in_schema=False)


def _logged_in_redirect(user_id: int) -> RedirectResponse:
    response = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        AUTH_COOKIE,
        create_access_token(user_id),
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return response


def _demo_login(db: DbSession) -> dict | None:
    if users.get_by_email(db, DEMO_EMAIL) is None:
        return None
    return {"email": DEMO_EMAIL, "password": DEMO_PASSWORD}


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    field = str(error["loc"][0]).replace("_", " ").capitalize()
    return f"{field}: {error['msg'].removeprefix('Value error, ')}"


# --- Auth ---


@router.get("/login")
@router.get("/register")
def auth_page(request: Request, user: OptionalUser, db: DbSession):
    if user is not None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    mode = request.url.path.lstrip("/")  # "login" or "register": one template serves both
    return render(request, "auth.html", mode=mode, demo=_demo_login(db))


@router.post("/login")
def login(
    request: Request,
    db: DbSession,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    user = users.authenticate(db, email, password)
    if user is None:
        return render(
            request,
            "auth.html",
            mode="login",
            email=email,
            error="Incorrect email or password.",
            demo=_demo_login(db),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    return _logged_in_redirect(user.id)


@router.post("/register")
def register(
    request: Request,
    db: DbSession,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    display_name: Annotated[str, Form()] = "",
):
    try:
        data = schemas.UserCreate(email=email, password=password, display_name=display_name)
        user = users.register(db, data)
    except ValidationError as exc:
        error = _first_error(exc)
    except ConflictError as exc:
        error = exc.message
    else:
        return _logged_in_redirect(user.id)
    return render(
        request,
        "auth.html",
        mode="register",
        email=email,
        display_name=display_name,
        error=error,
        status_code=status.HTTP_400_BAD_REQUEST,
    )


@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(AUTH_COOKIE)
    return response


# --- Pages ---


@router.get("/")
def dashboard(request: Request, user: PageUser, db: DbSession):
    return render(
        request,
        "dashboard.html",
        user,
        active="dashboard",
        exercises=exercises.logged_exercises(db, user.id),
        today=datetime.now(UTC).date(),
    )


@router.get("/workouts")
def history(request: Request, user: PageUser, db: DbSession):
    items, total = workouts.list_workouts(db, user.id, 0, PAGE_SIZE)
    return render(
        request,
        "workouts.html",
        user,
        active="history",
        workouts=items,
        total=total,
        next_skip=PAGE_SIZE if total > PAGE_SIZE else None,
    )


def _workout_form(request: Request, user: User, db: DbSession, **context) -> HTMLResponse:
    """The log/edit form; both need the exercise picker and the muscle groups."""
    choices = exercises.list_exercises(db, user.id)
    return render(
        request,
        "workout_form.html",
        user,
        exercises=choices,
        muscle_groups=schemas.MUSCLE_GROUPS,
        **context,
    )


@router.get("/workouts/new")
def new_workout(request: Request, user: PageUser, db: DbSession):
    # Start the first set on the user's main lift rather than the alphabetically first one.
    main_lift = next((e.id for e in exercises.logged_exercises(db, user.id)), None)
    return _workout_form(
        request, user, db, active="log", workout=None, default_exercise_id=main_lift
    )


@router.get("/workouts/{workout_id}/edit")
def edit_workout(workout_id: int, request: Request, user: PageUser, db: DbSession):
    workout = workouts.get_workout(db, user.id, workout_id)
    return _workout_form(request, user, db, active="history", workout=workout)


# --- HTMX partials ---


@router.get("/htmx/metrics")
def metrics_partial(
    request: Request, user: PageUser, db: DbSession, exercise_id: int, days: int = 90
):
    progression = analytics.progression(db, user.id, exercise_id, days)
    history = progression.history
    latest = history[-1] if history else None
    return render(
        request,
        "partials/metrics_cards.html",
        user,
        progression=progression,
        latest=latest,
        peak_1rm=max((h.estimated_1rm for h in history), default=None),
        pr_count=sum(h.is_pr for h in history),
        # Only circle the peak if it was set in the latest session.
        fresh_record=bool(
            latest
            and latest.is_pr
            and latest.session_date == workouts.latest_workout_at(db, user.id)
        ),
    )


@router.get("/htmx/plateaus")
def plateaus_partial(request: Request, user: PageUser, db: DbSession):
    return render(request, "partials/plateaus.html", user, plateaus=analytics.plateaus(db, user.id))


@router.get("/htmx/personal-records")
def personal_records_partial(request: Request, user: PageUser, db: DbSession):
    return render(
        request,
        "partials/personal_records.html",
        user,
        records=analytics.personal_records(db, user.id),
        # Records set in the latest session are circled.
        latest_session_at=workouts.latest_workout_at(db, user.id),
    )


# Heatmap cell classes: rest day, then volume quartiles 1-4.
HEATMAP_LEVELS = (
    "border border-rule-soft",
    "bg-[#E2E5E9]",
    "bg-[#C2C7CE]",
    "bg-[#959CA5]",
    "bg-[#5F666F]",
)


def _heatmap_columns(frequency: schemas.TrainingFrequency) -> list[dict]:
    """One column per week (Monday first) of cells shaded by that day's training volume."""
    by_day = {d.day: d for d in frequency.days}
    training_volumes = sorted(d.volume for d in frequency.days if d.sessions)
    # Quartiles instead of a max-based scale, so one big day doesn't wash out the rest.
    cuts = [training_volumes[len(training_volumes) * q // 4] for q in (1, 2, 3) if training_volumes]

    columns = []
    for week in range(frequency.weeks):
        monday = frequency.start + timedelta(weeks=week)
        cells = []
        for offset in range(7):
            day = by_day.get(monday + timedelta(days=offset))
            if day is None:  # in the future
                cells.append(None)
                continue
            # Level 0 is a rest day; 1-4 is the quartile the day's volume falls in.
            level = 0 if not day.sessions else 1 + sum(day.volume >= cut for cut in cuts)
            label = short_date(day.day)
            title = (
                f"{label}: {day.sessions} session{'s' if day.sessions > 1 else ''}, "
                f"{kg(day.volume)} kg"
                if day.sessions
                else f"{label}: rest"
            )
            cells.append({"level": level, "title": title})
        new_month = week == 0 or monday.month != (monday - timedelta(weeks=1)).month
        columns.append({"label": monday.strftime("%b") if new_month else "", "cells": cells})
    return columns


@router.get("/htmx/heatmap")
def heatmap_partial(request: Request, user: PageUser, db: DbSession):
    frequency = analytics.training_frequency(db, user.id, weeks=26)
    return render(
        request,
        "partials/heatmap.html",
        user,
        frequency=frequency,
        columns=_heatmap_columns(frequency),
        levels=HEATMAP_LEVELS,
    )


def _parse_number(raw: str | None, kind: type) -> int | float | None:
    try:
        return kind(raw) if raw not in (None, "") else None
    except ValueError:
        return None


@router.get("/htmx/set-row")
def set_row_partial(
    request: Request,
    user: PageUser,
    db: DbSession,
    exercise_id: str | None = None,
    reps: str | None = None,
    weight: str | None = None,
):
    """A new set row, pre-filled from the previous row so repeated sets are one click."""
    return render(
        request,
        "partials/set_row.html",
        user,
        exercises=exercises.list_exercises(db, user.id),
        s={
            "exercise_id": _parse_number(exercise_id, int),
            "reps": _parse_number(reps, int),
            "weight": _parse_number(weight, float),
        },
    )


@router.get("/htmx/workouts")
def workouts_partial(request: Request, user: PageUser, db: DbSession, skip: int = 0):
    items, total = workouts.list_workouts(db, user.id, skip, PAGE_SIZE)
    next_skip = skip + PAGE_SIZE
    return render(
        request,
        "partials/workout_list.html",
        user,
        workouts=items,
        next_skip=next_skip if total > next_skip else None,
    )


@router.delete("/htmx/workouts/{workout_id}")
def delete_workout_partial(workout_id: int, user: PageUser, db: DbSession):
    workouts.delete_workout(db, user.id, workout_id)
    # 200 with an empty body: htmx swaps the card out (it ignores 204 responses).
    return HTMLResponse("")
