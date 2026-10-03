from fastapi import APIRouter, status

from app import schemas
from app.deps import CurrentUser, DbSession
from app.services import exercises

router = APIRouter(prefix="/exercises", tags=["exercises"])


@router.get("", response_model=list[schemas.ExerciseOut])
def list_exercises(user: CurrentUser, db: DbSession):
    """The shared catalog plus the user's own custom exercises."""
    return exercises.list_exercises(db, user.id)


@router.post("", response_model=schemas.ExerciseOut, status_code=status.HTTP_201_CREATED)
def create_exercise(data: schemas.ExerciseCreate, user: CurrentUser, db: DbSession):
    return exercises.create_exercise(db, user.id, data)
