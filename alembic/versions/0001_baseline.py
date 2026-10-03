"""Baseline: the original single-user schema

Matches what the first version of the app created with Base.metadata.create_all(),
so existing databases can be stamped at this revision and upgraded from here.

Revision ID: 0001
Revises:
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("notes", sa.String(), nullable=True),
    )
    op.create_index("ix_workouts_id", "workouts", ["id"])
    op.create_table(
        "workout_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workout_id",
            sa.Integer(),
            sa.ForeignKey("workouts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("exercise_name", sa.String(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
    )
    op.create_index("ix_workout_sets_id", "workout_sets", ["id"])


def downgrade() -> None:
    op.drop_table("workout_sets")
    op.drop_table("workouts")
