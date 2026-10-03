from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.one_rep_max import MAX_REPS, brzycki


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    muscle_group: Mapped[str] = mapped_column(String(30))
    # NULL means a shared catalog exercise; otherwise a custom exercise owned by one user.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    @property
    def is_custom(self) -> bool:
        return self.user_id is not None


# Names are unique case-insensitively: once across the catalog, and once per user's own list.
Index(
    "uq_exercises_catalog_name",
    func.lower(Exercise.name),
    unique=True,
    postgresql_where=Exercise.user_id.is_(None),
)
Index(
    "uq_exercises_user_name",
    Exercise.user_id,
    func.lower(Exercise.name),
    unique=True,
    postgresql_where=Exercise.user_id.is_not(None),
)


class Workout(Base):
    __tablename__ = "workouts"
    __table_args__ = (Index("ix_workouts_user_id_performed_at", "user_id", "performed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    sets: Mapped[list["WorkoutSet"]] = relationship(
        back_populates="workout", cascade="all, delete-orphan", order_by="WorkoutSet.id"
    )

    @property
    def total_volume(self) -> float:
        return round(sum(s.reps * s.weight for s in self.sets), 2)


class WorkoutSet(Base):
    __tablename__ = "workout_sets"
    __table_args__ = (
        CheckConstraint(f"reps BETWEEN 1 AND {MAX_REPS}", name="ck_workout_sets_reps_range"),
        CheckConstraint("weight >= 0", name="ck_workout_sets_weight_non_negative"),
        # Covers the analytics access path: filter by exercise, then join to workouts.
        Index("ix_workout_sets_exercise_id_workout_id", "exercise_id", "workout_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workout_id: Mapped[int] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), index=True
    )
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="RESTRICT"))
    reps: Mapped[int]
    weight: Mapped[float] = mapped_column(Float)

    workout: Mapped[Workout] = relationship(back_populates="sets")
    exercise: Mapped[Exercise] = relationship(lazy="joined")

    @property
    def exercise_name(self) -> str:
        return self.exercise.name

    @property
    def estimated_1rm(self) -> float:
        return round(brzycki(self.weight, self.reps), 2)
