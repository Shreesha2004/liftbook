from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.errors import ConflictError, NotFoundError
from app.models import Exercise, Workout, WorkoutSet


def visible_to(user_id: int):
    """Filter for exercises a user may use: the shared catalog and their own custom ones."""
    return or_(Exercise.user_id.is_(None), Exercise.user_id == user_id)


def list_exercises(db: Session, user_id: int) -> Sequence[Exercise]:
    return db.scalars(
        select(Exercise).where(visible_to(user_id)).order_by(Exercise.muscle_group, Exercise.name)
    ).all()


def logged_exercises(db: Session, user_id: int) -> Sequence[Exercise]:
    """Exercises the user has logged, heaviest first, so the main lifts lead the picker."""
    return db.scalars(
        select(Exercise)
        .join(WorkoutSet, WorkoutSet.exercise_id == Exercise.id)
        .join(Workout, Workout.id == WorkoutSet.workout_id)
        .where(Workout.user_id == user_id)
        .group_by(Exercise.id)
        .order_by(func.max(WorkoutSet.weight).desc(), Exercise.name)
    ).all()


def get_visible_exercise(db: Session, user_id: int, exercise_id: int) -> Exercise:
    exercise = db.scalar(select(Exercise).where(Exercise.id == exercise_id, visible_to(user_id)))
    if exercise is None:
        raise NotFoundError(f"Exercise {exercise_id} not found")
    return exercise


def create_exercise(db: Session, user_id: int, data: schemas.ExerciseCreate) -> Exercise:
    clash = db.scalar(
        select(Exercise.id).where(
            visible_to(user_id), func.lower(Exercise.name) == data.name.lower()
        )
    )
    if clash is not None:
        raise ConflictError(f"An exercise named '{data.name}' already exists")
    exercise = Exercise(name=data.name, muscle_group=data.muscle_group, user_id=user_id)
    db.add(exercise)
    try:
        db.commit()
    except IntegrityError:  # lost a race with a concurrent request for the same name
        db.rollback()
        raise ConflictError(f"An exercise named '{data.name}' already exists") from None
    db.refresh(exercise)
    return exercise
