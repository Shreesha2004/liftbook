from datetime import date
from itertools import groupby
from pathlib import Path

from fastapi import Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.models import User, Workout

templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")


def kg(value: float) -> str:
    """85.0 -> "85", 82.5 -> "82.5", 1234.0 -> "1,234"."""
    return f"{value:,.1f}".removesuffix(".0")


def sets_by_exercise(workout: Workout) -> list[tuple[str, str, float]]:
    """(exercise, "4 x 5 @ 85 kg" or "5x85, 5x85, 4x85 kg", best e1RM) in logged order."""
    summary = []
    for name, group in groupby(workout.sets, key=lambda s: s.exercise_name):
        sets = list(group)
        if len({(s.reps, s.weight) for s in sets}) == 1:
            text = f"{len(sets)} × {sets[0].reps} @ {kg(sets[0].weight)} kg"
        else:
            text = ", ".join(f"{s.reps}×{kg(s.weight)}" for s in sets) + " kg"
        summary.append((name, text, max(s.estimated_1rm for s in sets)))
    return summary


def short_date(value: date) -> str:
    """Fri 2 Oct"""
    return f"{value:%a} {value.day} {value:%b}"


def long_date(value: date) -> str:
    """2 Oct 2026"""
    return f"{value.day} {value:%b %Y}"


templates.env.filters["kg"] = kg
templates.env.filters["by_exercise"] = sets_by_exercise
templates.env.filters["shortdate"] = short_date
templates.env.filters["longdate"] = long_date


def render(
    request: Request,
    name: str,
    user: User | None = None,
    status_code: int = status.HTTP_200_OK,
    **context,
) -> HTMLResponse:
    """Render a template with the logged-in user (if any) always in its context."""
    return templates.TemplateResponse(
        request, name, {"user": user, **context}, status_code=status_code
    )
