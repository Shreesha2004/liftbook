from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app import schemas
from app.deps import CurrentUser, DbSession
from app.services import workouts

router = APIRouter(prefix="/workouts", tags=["workouts"])


@router.post("", response_model=schemas.WorkoutCreated, status_code=status.HTTP_201_CREATED)
def create_workout(data: schemas.WorkoutIn, user: CurrentUser, db: DbSession):
    """Log a session. The response lists any new estimated-1RM personal records it set."""
    workout, records = workouts.create_workout(db, user.id, data)
    created = schemas.WorkoutCreated.model_validate(workout)
    created.new_personal_records = records
    return created


@router.get("", response_model=schemas.WorkoutPage)
def list_workouts(
    user: CurrentUser,
    db: DbSession,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """Newest first."""
    items, total = workouts.list_workouts(db, user.id, skip, limit)
    return schemas.WorkoutPage(items=items, total=total, skip=skip, limit=limit)


@router.get("/{workout_id}", response_model=schemas.WorkoutOut)
def get_workout(workout_id: int, user: CurrentUser, db: DbSession):
    return workouts.get_workout(db, user.id, workout_id)


@router.get("/{workout_id}/summary", response_model=schemas.WorkoutSummary)
def get_workout_summary(workout_id: int, user: CurrentUser, db: DbSession):
    """Totals and best estimated 1RM per exercise for one session."""
    return workouts.summarize(workouts.get_workout(db, user.id, workout_id))


@router.put("/{workout_id}", response_model=schemas.WorkoutOut)
def update_workout(workout_id: int, data: schemas.WorkoutIn, user: CurrentUser, db: DbSession):
    """Replace the session's details and all of its sets."""
    return workouts.update_workout(db, user.id, workout_id, data)


@router.delete("/{workout_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workout(workout_id: int, user: CurrentUser, db: DbSession):
    workouts.delete_workout(db, user.id, workout_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
