"""Training analytics computed in PostgreSQL.

Each query pushes the aggregation into the database (CTEs, window functions,
generate_series, FILTER) and returns only the rows the UI needs. All dates are
bucketed in UTC.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import schemas
from app.one_rep_max import E1RM_SQL
from app.services.exercises import get_visible_exercise

# Per-session best e1RM for one exercise. LAG gives the change since the previous session;
# a running MAX over the preceding rows flags sessions that beat every earlier one.
# Window functions run inside the CTE, before the date filter, so the first session in a
# date range still has a "previous" value to compare against.
_PROGRESSION_SQL = text(
    f"""
    WITH session_metrics AS (
        SELECT
            w.id AS workout_id,
            w.performed_at AS session_date,
            MAX(s.weight) AS max_weight,
            MAX({E1RM_SQL}) AS max_1rm,
            SUM(s.reps * s.weight) AS volume
        FROM workout_sets s
        JOIN workouts w ON w.id = s.workout_id
        WHERE w.user_id = :user_id AND s.exercise_id = :exercise_id
        GROUP BY w.id, w.performed_at
    ),
    windowed AS (
        SELECT
            *,
            LAG(max_1rm) OVER sessions AS prev_1rm,
            MAX(max_1rm) OVER (
                sessions ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) AS prev_best_1rm
        FROM session_metrics
        WINDOW sessions AS (ORDER BY session_date, workout_id)
    )
    SELECT
        workout_id,
        session_date,
        max_weight,
        max_1rm AS estimated_1rm,
        volume,
        prev_1rm AS previous_1rm,
        max_1rm - prev_1rm AS delta_1rm,
        COALESCE(max_1rm > prev_best_1rm, FALSE) AS is_pr
    FROM windowed
    WHERE CAST(:since AS timestamptz) IS NULL OR session_date >= CAST(:since AS timestamptz)
    ORDER BY session_date, workout_id
    """
)

# Best set per exercise by e1RM (earliest one wins ties), plus the heaviest weight ever moved.
_PERSONAL_RECORDS_SQL = text(
    f"""
    WITH scored_sets AS (
        SELECT s.exercise_id, s.weight, s.reps, w.performed_at, {E1RM_SQL} AS e1rm
        FROM workout_sets s
        JOIN workouts w ON w.id = s.workout_id
        WHERE w.user_id = :user_id
    ),
    ranked AS (
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY exercise_id ORDER BY e1rm DESC, performed_at
            ) AS rank,
            MAX(weight) OVER (PARTITION BY exercise_id) AS heaviest_weight
        FROM scored_sets
    )
    SELECT
        e.id AS exercise_id,
        e.name AS exercise_name,
        e.muscle_group,
        r.e1rm AS best_estimated_1rm,
        r.weight,
        r.reps,
        r.performed_at AS achieved_at,
        r.heaviest_weight
    FROM ranked r
    JOIN exercises e ON e.id = r.exercise_id
    WHERE r.rank = 1
    ORDER BY r.e1rm DESC
    """
)

# Volume (reps x kg) per Monday-starting UTC week and muscle group. Weeks with no training
# are missing here; weekly_volume() fills them with zeros.
_WEEKLY_VOLUME_SQL = text(
    """
    SELECT
        CAST(date_trunc('week', w.performed_at AT TIME ZONE 'UTC') AS date) AS week_start,
        e.muscle_group,
        SUM(s.reps * s.weight) AS volume
    FROM workout_sets s
    JOIN workouts w ON w.id = s.workout_id
    JOIN exercises e ON e.id = s.exercise_id
    WHERE w.user_id = :user_id AND w.performed_at >= :since
    GROUP BY 1, 2
    """
)

# generate_series builds every calendar day so rest days come back as zero rows.
_FREQUENCY_SQL = text(
    """
    WITH calendar AS (
        SELECT CAST(d AS date) AS day
        FROM generate_series(
            CAST(:start AS timestamp), CAST(:end AS timestamp), interval '1 day'
        ) AS d
    ),
    daily AS (
        SELECT
            CAST(w.performed_at AT TIME ZONE 'UTC' AS date) AS day,
            COUNT(DISTINCT w.id) AS sessions,
            SUM(s.reps * s.weight) AS volume
        FROM workouts w
        JOIN workout_sets s ON s.workout_id = w.id
        WHERE w.user_id = :user_id
          AND w.performed_at >= :start_ts AND w.performed_at < :end_ts
        GROUP BY 1
    )
    SELECT calendar.day, COALESCE(daily.sessions, 0) AS sessions,
           COALESCE(daily.volume, 0) AS volume
    FROM calendar
    LEFT JOIN daily ON daily.day = calendar.day
    ORDER BY calendar.day
    """
)

# An exercise has plateaued when none of its last :window sessions beat the best from
# before them. Only lifts trained recently, with some history before the window, count.
_PLATEAU_SQL = text(
    f"""
    WITH session_best AS (
        SELECT s.exercise_id, w.id AS workout_id, w.performed_at, MAX({E1RM_SQL}) AS best_1rm
        FROM workout_sets s
        JOIN workouts w ON w.id = s.workout_id
        WHERE w.user_id = :user_id
        GROUP BY s.exercise_id, w.id, w.performed_at
    ),
    ranked AS (
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY exercise_id ORDER BY performed_at DESC, workout_id DESC
            ) AS recency
        FROM session_best
    ),
    per_exercise AS (
        SELECT
            exercise_id,
            COUNT(*) AS sessions,
            MAX(performed_at) AS last_session,
            MAX(best_1rm) FILTER (WHERE recency <= :window) AS recent_best,
            MAX(best_1rm) FILTER (WHERE recency > :window) AS earlier_best
        FROM ranked
        GROUP BY exercise_id
    )
    SELECT
        p.exercise_id,
        e.name AS exercise_name,
        :window AS sessions_checked,
        p.recent_best,
        p.earlier_best AS all_time_best,
        (
            SELECT MIN(r.performed_at) FROM ranked r
            WHERE r.exercise_id = p.exercise_id AND r.best_1rm = p.earlier_best
        ) AS best_achieved_at
    FROM per_exercise p
    JOIN exercises e ON e.id = p.exercise_id
    WHERE p.sessions >= :window + :min_history
      AND p.last_session >= :active_since
      AND p.recent_best <= p.earlier_best
    ORDER BY p.earlier_best - p.recent_best DESC, e.name
    """
)


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _start_of_day(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def progression(
    db: Session,
    user_id: int,
    exercise_id: int,
    days: int | None = None,
    now: datetime | None = None,
) -> schemas.Progression:
    exercise = get_visible_exercise(db, user_id, exercise_id)
    since = _now(now) - timedelta(days=days) if days else None
    rows = db.execute(
        _PROGRESSION_SQL, {"user_id": user_id, "exercise_id": exercise_id, "since": since}
    ).mappings()
    history = [schemas.ProgressionPoint(**row) for row in rows]
    return schemas.Progression(
        exercise_id=exercise.id,
        exercise_name=exercise.name,
        days=days or None,
        total_sessions=len(history),
        history=history,
    )


def personal_records(db: Session, user_id: int) -> list[schemas.PersonalRecord]:
    rows = db.execute(_PERSONAL_RECORDS_SQL, {"user_id": user_id}).mappings()
    return [schemas.PersonalRecord(**row) for row in rows]


def weekly_volume(
    db: Session, user_id: int, weeks: int = 12, now: datetime | None = None
) -> schemas.WeeklyVolume:
    this_week = _monday(_now(now).date())
    week_starts = [this_week - timedelta(weeks=i) for i in reversed(range(weeks))]
    rows = db.execute(
        _WEEKLY_VOLUME_SQL, {"user_id": user_id, "since": _start_of_day(week_starts[0])}
    )

    by_group: dict[str, dict[date, float]] = defaultdict(dict)
    for week_start, muscle_group, volume in rows:
        by_group[muscle_group][week_start] = float(volume)

    # Fixed muscle-group order, so a group's stack position and color never shift.
    rank = {group: i for i, group in enumerate(schemas.MUSCLE_GROUPS)}
    groups = sorted(by_group, key=lambda g: (rank.get(g, len(rank)), g))
    return schemas.WeeklyVolume(
        weeks=week_starts,
        series=[
            schemas.VolumeSeries(
                muscle_group=group,
                volumes=[by_group[group].get(week, 0.0) for week in week_starts],
            )
            for group in groups
        ],
    )


def training_frequency(
    db: Session, user_id: int, weeks: int = 26, now: datetime | None = None
) -> schemas.TrainingFrequency:
    end = _now(now).date()
    start = _monday(end) - timedelta(weeks=weeks - 1)
    rows = db.execute(
        _FREQUENCY_SQL,
        {
            "user_id": user_id,
            "start": start,
            "end": end,
            "start_ts": _start_of_day(start),
            "end_ts": _start_of_day(end + timedelta(days=1)),
        },
    ).mappings()
    days = [schemas.FrequencyDay(**row) for row in rows]
    active_weeks = {_monday(d.day) for d in days if d.sessions}
    return schemas.TrainingFrequency(
        start=start,
        end=end,
        total_sessions=sum(d.sessions for d in days),
        active_weeks=len(active_weeks),
        weeks=weeks,
        days=days,
    )


def plateaus(
    db: Session,
    user_id: int,
    window: int = 4,
    min_history: int = 2,
    active_days: int = 30,
    now: datetime | None = None,
) -> list[schemas.Plateau]:
    rows = db.execute(
        _PLATEAU_SQL,
        {
            "user_id": user_id,
            "window": window,
            "min_history": min_history,
            "active_since": _now(now) - timedelta(days=active_days),
        },
    ).mappings()
    return [schemas.Plateau(**row) for row in rows]
