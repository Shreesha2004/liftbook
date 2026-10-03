from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)

from app.one_rep_max import MAX_REPS

# Also the colour order in the volume chart.
MuscleGroup = Literal["Legs", "Back", "Chest", "Shoulders", "Arms", "Core", "Other"]
MUSCLE_GROUPS: tuple[str, ...] = MuscleGroup.__args__

# Rounded floats for analytics responses.
Kg = Annotated[float, AfterValidator(lambda v: round(v, 2))]
Volume = Annotated[float, AfterValidator(lambda v: round(v, 1))]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Auth ---


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(None, max_length=80)

    @field_validator("email")
    @classmethod
    def _lowercase_email(cls, email: str) -> str:
        return email.lower()

    @field_validator("display_name")
    @classmethod
    def _blank_name_is_none(cls, name: str | None) -> str | None:
        return (name or "").strip() or None


class UserOut(ORMModel):
    id: int
    email: str
    display_name: str | None
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Exercises ---


class ExerciseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    muscle_group: MuscleGroup

    @field_validator("name")
    @classmethod
    def _strip_name(cls, name: str) -> str:
        name = " ".join(name.split())
        if not name:
            raise ValueError("name must not be blank")
        return name


class ExerciseOut(ORMModel):
    id: int
    name: str
    muscle_group: str
    is_custom: bool


# --- Workouts ---


class SetIn(BaseModel):
    exercise_id: int
    reps: int = Field(ge=1, le=MAX_REPS, description="1-36; the Brzycki formula breaks at 37")
    weight: float = Field(ge=0, le=1000, description="Kilograms")


class SetOut(ORMModel):
    id: int
    exercise_id: int
    exercise_name: str
    reps: int
    weight: float
    estimated_1rm: float


class WorkoutIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    notes: str | None = Field(None, max_length=500)
    performed_at: datetime | None = Field(
        None, description="Defaults to now. Times without a timezone are treated as UTC."
    )
    sets: list[SetIn] = Field(min_length=1, max_length=100)

    @field_validator("performed_at")
    @classmethod
    def _aware_and_not_future(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        if value > datetime.now(UTC) + timedelta(days=1):
            raise ValueError("performed_at cannot be in the future")
        return value


class WorkoutOut(ORMModel):
    id: int
    title: str
    notes: str | None
    performed_at: datetime
    total_volume: float
    sets: list[SetOut]


class WorkoutPage(BaseModel):
    items: list[WorkoutOut]
    total: int
    skip: int
    limit: int


class PersonalRecordHit(BaseModel):
    exercise_id: int
    exercise_name: str
    estimated_1rm: float
    previous_best: float


class WorkoutCreated(WorkoutOut):
    new_personal_records: list[PersonalRecordHit] = []


class ExerciseSummary(BaseModel):
    exercise_id: int
    exercise_name: str
    total_sets: int
    total_reps: int
    total_volume: float
    best_estimated_1rm: float


class WorkoutSummary(BaseModel):
    workout_id: int
    workout_title: str
    total_sets: int
    total_reps: int
    total_volume: float
    exercises: list[ExerciseSummary]


# --- Analytics ---


class ProgressionPoint(BaseModel):
    workout_id: int
    session_date: datetime
    max_weight: float
    estimated_1rm: Kg
    volume: Kg
    previous_1rm: Kg | None
    delta_1rm: Kg | None
    is_pr: bool


class Progression(BaseModel):
    exercise_id: int
    exercise_name: str
    days: int | None
    total_sessions: int
    history: list[ProgressionPoint]


class PersonalRecord(BaseModel):
    exercise_id: int
    exercise_name: str
    muscle_group: str
    best_estimated_1rm: Kg
    weight: float
    reps: int
    achieved_at: datetime
    heaviest_weight: float


class VolumeSeries(BaseModel):
    muscle_group: str
    volumes: list[Volume]


class WeeklyVolume(BaseModel):
    weeks: list[date]
    series: list[VolumeSeries]


class FrequencyDay(BaseModel):
    day: date
    sessions: int
    volume: Volume


class TrainingFrequency(BaseModel):
    start: date
    end: date
    total_sessions: int
    active_weeks: int
    weeks: int
    days: list[FrequencyDay]


class Plateau(BaseModel):
    exercise_id: int
    exercise_name: str
    sessions_checked: int
    recent_best: Kg
    all_time_best: Kg
    best_achieved_at: datetime
