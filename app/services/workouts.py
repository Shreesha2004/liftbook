from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.orm import Session, selectinload

from app import schemas
from app.errors import InvalidReferenceError, NotFoundError
from app.models import Exercise, Workout, WorkoutSet
from app.one_rep_max import E1RM_SQL, brzycki
from app.services.exercises import visible_to


def get_workout(db: Session, user_id: int, workout_id: int) -> Workout:
    # Other users' workouts are reported as missing rather than forbidden,
    # so ids can't be probed to learn what exists.
    workout = db.scalar(
        select(Workout)
        .where(Workout.id == workout_id, Workout.user_id == user_id)
        .options(selectinload(Workout.sets))
    )
    if workout is None:
        raise NotFoundError(f"Workout {workout_id} not found")
    return workout


def list_workouts(
    db: Session, user_id: int, skip: int = 0, limit: int = 20
) -> tuple[Sequence[Workout], int]:
    total = db.scalar(select(func.count()).where(Workout.user_id == user_id))
    items = db.scalars(
        select(Workout)
        .where(Workout.user_id == user_id)
        .order_by(Workout.performed_at.desc(), Workout.id.desc())
        .offset(skip)
        .limit(limit)
        .options(selectinload(Workout.sets))
    ).all()
    return items, total or 0


def latest_workout_at(db: Session, user_id: int) -> datetime | None:
    return db.scalar(select(func.max(Workout.performed_at)).where(Workout.user_id == user_id))


def _check_exercises(db: Session, user_id: int, sets: list[schemas.SetIn]) -> dict[int, str]:
    wanted = {s.exercise_id for s in sets}
    found = dict(
        db.execute(
            select(Exercise.id, Exercise.name).where(Exercise.id.in_(wanted), visible_to(user_id))
        ).all()
    )
    missing = sorted(wanted - found.keys())
    if missing:
        raise InvalidReferenceError(f"Unknown exercise id(s): {', '.join(map(str, missing))}")
    return found


_BEST_E1RM_SQL = text(
    f"""
    SELECT s.exercise_id, MAX({E1RM_SQL}) AS best
    FROM workout_sets s
    JOIN workouts w ON w.id = s.workout_id
    WHERE w.user_id = :user_id AND s.exercise_id IN :exercise_ids
    GROUP BY s.exercise_id
    """
).bindparams(bindparam("exercise_ids", expanding=True))


def _best_e1rm_by_exercise(db: Session, user_id: int, exercise_ids: set[int]) -> dict[int, float]:
    rows = db.execute(_BEST_E1RM_SQL, {"user_id": user_id, "exercise_ids": list(exercise_ids)})
    return {exercise_id: float(best) for exercise_id, best in rows}


def create_workout(
    db: Session, user_id: int, data: schemas.WorkoutIn
) -> tuple[Workout, list[schemas.PersonalRecordHit]]:
    names = _check_exercises(db, user_id, data.sets)
    previous_best = _best_e1rm_by_exercise(db, user_id, set(names))

    workout = Workout(
        user_id=user_id,
        title=data.title,
        notes=data.notes,
        performed_at=data.performed_at or datetime.now(UTC),
        sets=[WorkoutSet(**s.model_dump()) for s in data.sets],
    )
    db.add(workout)
    db.commit()
    db.refresh(workout)

    new_best: dict[int, float] = defaultdict(float)
    for s in data.sets:
        new_best[s.exercise_id] = max(new_best[s.exercise_id], brzycki(s.weight, s.reps))
    # First-ever sessions of an exercise aren't announced as records; there is nothing to beat.
    records = [
        schemas.PersonalRecordHit(
            exercise_id=exercise_id,
            exercise_name=names[exercise_id],
            estimated_1rm=round(best, 2),
            previous_best=round(previous_best[exercise_id], 2),
        )
        for exercise_id, best in new_best.items()
        if exercise_id in previous_best and best > previous_best[exercise_id] + 1e-9
    ]
    return workout, records


def update_workout(db: Session, user_id: int, workout_id: int, data: schemas.WorkoutIn) -> Workout:
    workout = get_workout(db, user_id, workout_id)
    _check_exercises(db, user_id, data.sets)
    workout.title = data.title
    workout.notes = data.notes
    if data.performed_at is not None:
        workout.performed_at = data.performed_at
    workout.sets = [WorkoutSet(**s.model_dump()) for s in data.sets]
    db.commit()
    db.refresh(workout)
    return workout


def delete_workout(db: Session, user_id: int, workout_id: int) -> None:
    db.delete(get_workout(db, user_id, workout_id))
    db.commit()


def summarize(workout: Workout) -> schemas.WorkoutSummary:
    by_exercise: dict[int, list[WorkoutSet]] = defaultdict(list)
    for s in workout.sets:
        by_exercise[s.exercise_id].append(s)

    exercises = [
        schemas.ExerciseSummary(
            exercise_id=exercise_id,
            exercise_name=sets[0].exercise_name,
            total_sets=len(sets),
            total_reps=sum(s.reps for s in sets),
            total_volume=round(sum(s.reps * s.weight for s in sets), 2),
            best_estimated_1rm=max(s.estimated_1rm for s in sets),
        )
        for exercise_id, sets in by_exercise.items()
    ]
    return schemas.WorkoutSummary(
        workout_id=workout.id,
        workout_title=workout.title,
        total_sets=len(workout.sets),
        total_reps=sum(s.reps for s in workout.sets),
        total_volume=workout.total_volume,
        exercises=exercises,
    )
