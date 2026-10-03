"""Generate a realistic six-month training history for the demo account.

    python -m app.seed             # replace the demo account's history
    python -m app.seed --if-empty  # only seed if the demo account has no workouts yet

The history follows a push/pull/legs rotation on weekdays with missed sessions,
a deload every fourth week, and an Overhead Press that stalls partway through,
so every dashboard panel (including the plateau alert) has something to show.
"""

import argparse
import random
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Exercise, User, Workout, WorkoutSet
from app.security import hash_password

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo1234"
DEMO_NAME = "Demo Lifter"

# exercise: (starting kg, kg gained per week, week it stops progressing or None)
PROGRAM: dict[str, tuple[float, float, int | None]] = {
    "Squat": (80.0, 1.25, None),
    "Bench Press": (60.0, 0.75, None),
    "Deadlift": (100.0, 1.5, None),
    "Overhead Press": (40.0, 0.5, 16),
    "Barbell Row": (55.0, 0.75, None),
    "Romanian Deadlift": (70.0, 1.0, None),
    "Barbell Curl": (25.0, 0.25, None),
    "Tricep Pushdown": (25.0, 0.4, None),
    "Cable Crunch": (30.0, 0.3, None),
}

# (title, [(exercise, sets, reps)])
ROUTINES = [
    ("Push Day", [("Bench Press", 4, 6), ("Overhead Press", 3, 8), ("Tricep Pushdown", 3, 12)]),
    ("Pull Day", [("Deadlift", 3, 5), ("Barbell Row", 4, 8), ("Barbell Curl", 3, 10)]),
    ("Leg Day", [("Squat", 4, 5), ("Romanian Deadlift", 3, 8), ("Cable Crunch", 3, 12)]),
]


def get_or_create_demo_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is None:
        user = User(
            email=DEMO_EMAIL, hashed_password=hash_password(DEMO_PASSWORD), display_name=DEMO_NAME
        )
        db.add(user)
        db.flush()
    return user


def seed_demo_history(
    db: Session, days: int = 182, seed: int = 42, now: datetime | None = None
) -> int:
    """Replace the demo user's workouts with `days` of generated history ending yesterday."""
    user = get_or_create_demo_user(db)
    db.execute(delete(Workout).where(Workout.user_id == user.id))
    catalog = dict(
        db.execute(select(Exercise.name, Exercise.id).where(Exercise.user_id.is_(None))).all()
    )

    rng = random.Random(seed)
    start = (now or datetime.now(UTC)).date() - timedelta(days=days)
    created = 0
    for offset in range(days):
        day = start + timedelta(days=offset)
        if day.weekday() >= 5 or rng.random() < 0.2:  # weekends off, about 1 in 5 days missed
            continue
        week = offset // 7
        deload = week % 4 == 3
        title, plan = ROUTINES[created % len(ROUTINES)]

        sets = []
        for name, set_count, reps in plan:
            base, weekly_gain, stall_week = PROGRAM[name]
            weight = base + min(week, stall_week or week) * weekly_gain
            weight += rng.uniform(-0.25, 0.25) * weekly_gain
            if stall_week is not None and week > stall_week:
                weight -= rng.uniform(0, 2 * weekly_gain)  # grinding just under the old best
            if deload:
                weight *= 0.8
            weight = round(weight * 2) / 2  # nearest 0.5 kg
            for i in range(set_count):
                # The last set of each exercise loses a rep to fatigue.
                sets.append(
                    WorkoutSet(
                        exercise_id=catalog[name],
                        reps=reps - (i == set_count - 1),
                        weight=weight,
                    )
                )

        performed_at = datetime.combine(day, time(17, 30), tzinfo=UTC) + timedelta(
            minutes=rng.randint(0, 150)
        )
        db.add(
            Workout(
                user_id=user.id,
                title=title,
                notes="Deload week" if deload else None,
                performed_at=performed_at,
                sets=sets,
            )
        )
        created += 1

    db.commit()
    return created


def seed_if_empty(db: Session) -> int:
    user = get_or_create_demo_user(db)
    has_history = db.scalar(select(func.count()).where(Workout.user_id == user.id))
    if has_history:
        db.commit()
        return 0
    return seed_demo_history(db)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--days", type=int, default=182)
    parser.add_argument("--if-empty", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db:
        created = seed_if_empty(db) if args.if_empty else seed_demo_history(db, days=args.days)
    if created:
        print(f"Seeded {created} workouts for {DEMO_EMAIL} (password: {DEMO_PASSWORD}).")
    else:
        print(f"{DEMO_EMAIL} already has workouts; nothing to do.")


if __name__ == "__main__":
    main()
