"""Multi-user accounts and a normalized exercise catalog

- users table; every workout now belongs to a user
- exercises table (shared catalog + per-user custom exercises) replacing free-text names
- workouts.timestamp renamed to performed_at and made NOT NULL
- check constraints on reps/weight, indexes for the analytics queries

Existing rows are preserved: if the database already has workouts, they are
assigned to the demo account, and their exercise names are matched to the catalog
(names not in the catalog become custom exercises of that account).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Kept inline (not imported from app code) so this migration never changes after release.
DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo1234"
DEMO_NAME = "Demo Lifter"

CATALOG = [
    ("Squat", "Legs"),
    ("Front Squat", "Legs"),
    ("Romanian Deadlift", "Legs"),
    ("Leg Press", "Legs"),
    ("Bulgarian Split Squat", "Legs"),
    ("Deadlift", "Back"),
    ("Barbell Row", "Back"),
    ("Pull-Up", "Back"),
    ("Lat Pulldown", "Back"),
    ("Bench Press", "Chest"),
    ("Incline Bench Press", "Chest"),
    ("Dumbbell Bench Press", "Chest"),
    ("Dip", "Chest"),
    ("Overhead Press", "Shoulders"),
    ("Lateral Raise", "Shoulders"),
    ("Barbell Curl", "Arms"),
    ("Tricep Pushdown", "Arms"),
    ("Hammer Curl", "Arms"),
    ("Cable Crunch", "Core"),
    ("Hanging Leg Raise", "Core"),
]


def upgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "exercises",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("muscle_group", sa.String(30), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_exercises_catalog_name",
        "exercises",
        [sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
    )
    op.create_index(
        "uq_exercises_user_name",
        "exercises",
        ["user_id", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.bulk_insert(
        sa.table("exercises", sa.column("name"), sa.column("muscle_group")),
        [{"name": name, "muscle_group": group} for name, group in CATALOG],
    )

    # --- Adopt rows from the single-user version ---
    owner_id = None
    if conn.execute(sa.text("SELECT EXISTS (SELECT 1 FROM workouts)")).scalar():
        from pwdlib import PasswordHash

        owner_id = conn.execute(
            sa.text(
                "INSERT INTO users (email, hashed_password, display_name) "
                "VALUES (:email, :hashed, :name) RETURNING id"
            ),
            {
                "email": DEMO_EMAIL,
                "hashed": PasswordHash.recommended().hash(DEMO_PASSWORD),
                "name": DEMO_NAME,
            },
        ).scalar_one()
        conn.execute(
            sa.text(
                """
                INSERT INTO exercises (name, muscle_group, user_id)
                SELECT DISTINCT ON (lower(ws.exercise_name)) ws.exercise_name, 'Other', :owner
                FROM workout_sets ws
                WHERE NOT EXISTS (
                    SELECT 1 FROM exercises e
                    WHERE e.user_id IS NULL AND lower(e.name) = lower(ws.exercise_name)
                )
                ORDER BY lower(ws.exercise_name), ws.exercise_name
                """
            ),
            {"owner": owner_id},
        )

    # --- workouts: owner, performed_at ---
    op.add_column("workouts", sa.Column("user_id", sa.Integer(), nullable=True))
    if owner_id is not None:
        conn.execute(sa.text("UPDATE workouts SET user_id = :owner"), {"owner": owner_id})
    op.alter_column("workouts", "user_id", nullable=False)
    op.create_foreign_key(
        "workouts_user_id_fkey", "workouts", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.alter_column("workouts", "timestamp", new_column_name="performed_at")
    conn.execute(sa.text("UPDATE workouts SET performed_at = now() WHERE performed_at IS NULL"))
    op.alter_column("workouts", "performed_at", nullable=False)
    op.drop_index("ix_workouts_id", table_name="workouts")  # duplicated the primary key index
    op.create_index("ix_workouts_user_id_performed_at", "workouts", ["user_id", "performed_at"])

    # --- workout_sets: exercise_id replaces exercise_name ---
    op.add_column("workout_sets", sa.Column("exercise_id", sa.Integer(), nullable=True))
    conn.execute(
        sa.text(
            """
            UPDATE workout_sets ws SET exercise_id = e.id
            FROM exercises e
            WHERE lower(e.name) = lower(ws.exercise_name)
              AND (e.user_id IS NULL OR e.user_id = :owner)
            """
        ),
        {"owner": owner_id},
    )
    op.alter_column("workout_sets", "exercise_id", nullable=False)
    op.create_foreign_key(
        "workout_sets_exercise_id_fkey",
        "workout_sets",
        "exercises",
        ["exercise_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_column("workout_sets", "exercise_name")
    op.drop_index("ix_workout_sets_id", table_name="workout_sets")
    op.create_index("ix_workout_sets_workout_id", "workout_sets", ["workout_id"])
    op.create_index(
        "ix_workout_sets_exercise_id_workout_id", "workout_sets", ["exercise_id", "workout_id"]
    )
    op.create_check_constraint(
        "ck_workout_sets_reps_range", "workout_sets", "reps BETWEEN 1 AND 36"
    )
    op.create_check_constraint("ck_workout_sets_weight_non_negative", "workout_sets", "weight >= 0")


def downgrade() -> None:
    conn = op.get_bind()

    op.drop_constraint("ck_workout_sets_weight_non_negative", "workout_sets", type_="check")
    op.drop_constraint("ck_workout_sets_reps_range", "workout_sets", type_="check")
    op.drop_index("ix_workout_sets_exercise_id_workout_id", table_name="workout_sets")
    op.drop_index("ix_workout_sets_workout_id", table_name="workout_sets")
    op.create_index("ix_workout_sets_id", "workout_sets", ["id"])
    op.add_column("workout_sets", sa.Column("exercise_name", sa.String(), nullable=True))
    conn.execute(
        sa.text(
            "UPDATE workout_sets ws SET exercise_name = e.name "
            "FROM exercises e WHERE e.id = ws.exercise_id"
        )
    )
    op.alter_column("workout_sets", "exercise_name", nullable=False)
    op.drop_constraint("workout_sets_exercise_id_fkey", "workout_sets", type_="foreignkey")
    op.drop_column("workout_sets", "exercise_id")

    op.drop_index("ix_workouts_user_id_performed_at", table_name="workouts")
    op.create_index("ix_workouts_id", "workouts", ["id"])
    op.alter_column("workouts", "performed_at", nullable=True, new_column_name="timestamp")
    op.drop_constraint("workouts_user_id_fkey", "workouts", type_="foreignkey")
    op.drop_column("workouts", "user_id")

    op.drop_index("uq_exercises_user_name", table_name="exercises")
    op.drop_index("uq_exercises_catalog_name", table_name="exercises")
    op.drop_table("exercises")
    op.drop_table("users")
