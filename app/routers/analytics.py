from typing import Annotated

from fastapi import APIRouter, Query

from app import schemas
from app.deps import CurrentUser, DbSession
from app.services import analytics

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/progression/{exercise_id}", response_model=schemas.Progression)
def progression(
    exercise_id: int,
    user: CurrentUser,
    db: DbSession,
    days: Annotated[int, Query(ge=0, le=3650, description="Look-back window; 0 = all time")] = 90,
):
    """Per-session best estimated 1RM with change since last session and PR flags."""
    return analytics.progression(db, user.id, exercise_id, days)


@router.get("/personal-records", response_model=list[schemas.PersonalRecord])
def personal_records(user: CurrentUser, db: DbSession):
    """Best estimated-1RM set for every exercise the user has logged."""
    return analytics.personal_records(db, user.id)


@router.get("/weekly-volume", response_model=schemas.WeeklyVolume)
def weekly_volume(
    user: CurrentUser, db: DbSession, weeks: Annotated[int, Query(ge=1, le=104)] = 12
):
    """Total volume (reps x kg) per muscle group per week, zero-filled."""
    return analytics.weekly_volume(db, user.id, weeks)


@router.get("/frequency", response_model=schemas.TrainingFrequency)
def training_frequency(
    user: CurrentUser, db: DbSession, weeks: Annotated[int, Query(ge=1, le=104)] = 26
):
    """Sessions per calendar day, including rest days, for a heatmap."""
    return analytics.training_frequency(db, user.id, weeks)


@router.get("/plateaus", response_model=list[schemas.Plateau])
def plateaus(user: CurrentUser, db: DbSession, window: Annotated[int, Query(ge=2, le=12)] = 4):
    """Recently trained lifts whose last `window` sessions didn't beat their earlier best."""
    return analytics.plateaus(db, user.id, window)
