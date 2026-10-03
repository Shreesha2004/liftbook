from datetime import UTC, date, datetime, timedelta

import pytest

from app.services import analytics

from helpers import log_workout, register

# A fixed "now" (a Wednesday) for analytics that depend on the current date.
NOW = datetime(2026, 3, 18, 12, 0, tzinfo=UTC)


def at(day: str, hour: int = 18) -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, tzinfo=UTC)


@pytest.fixture
def squat_history(client, auth, catalog):
    """Four squat sessions with e1RMs of 112.5, 118.125, 112.5 and 123.75 kg."""
    squat = catalog["Squat"]
    for days_ago, weight in [(30, 100), (20, 105), (10, 100), (1, 110)]:
        log_workout(client, auth, [(squat, 5, weight), (squat, 5, weight - 10)], days_ago=days_ago)
    return squat


def test_progression_tracks_change_and_records(client, auth, squat_history):
    response = client.get(f"/api/analytics/progression/{squat_history}?days=0", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["exercise_name"] == "Squat"
    assert body["total_sessions"] == 4

    history = body["history"]
    assert [p["estimated_1rm"] for p in history] == pytest.approx(
        [112.5, 118.12, 112.5, 123.75], abs=0.01
    )
    assert [p["max_weight"] for p in history] == [100, 105, 100, 110]
    assert [p["is_pr"] for p in history] == [False, True, False, True]
    assert history[0]["delta_1rm"] is None
    assert history[2]["delta_1rm"] == pytest.approx(-5.62, abs=0.01)
    assert history[3]["previous_1rm"] == 112.5


def test_date_range_keeps_the_previous_session_for_comparison(client, auth, squat_history):
    history = client.get(
        f"/api/analytics/progression/{squat_history}?days=15", headers=auth
    ).json()["history"]
    assert len(history) == 2
    # The session from 20 days ago is outside the range but still drives the first delta.
    assert history[0]["previous_1rm"] == pytest.approx(118.12, abs=0.01)
    assert history[0]["delta_1rm"] == pytest.approx(-5.62, abs=0.01)


def test_progression_for_an_unknown_exercise_is_404(client, auth):
    assert client.get("/api/analytics/progression/999999", headers=auth).status_code == 404


def test_progression_is_scoped_to_the_user(client, catalog, squat_history):
    other = register(client, "other@example.com")
    response = client.get(f"/api/analytics/progression/{squat_history}?days=0", headers=other)
    assert response.json()["history"] == []


def test_personal_records(client, auth, catalog):
    squat, bench = catalog["Squat"], catalog["Bench Press"]
    log_workout(client, auth, [(squat, 5, 100), (bench, 8, 60)], days_ago=10)
    log_workout(client, auth, [(squat, 1, 120), (squat, 8, 90)], days_ago=5)
    log_workout(client, auth, [(squat, 5, 100)], days_ago=1)

    records = client.get("/api/analytics/personal-records", headers=auth).json()
    assert [r["exercise_name"] for r in records] == ["Squat", "Bench Press"]
    squat_record = records[0]
    assert squat_record["best_estimated_1rm"] == 120
    assert (squat_record["weight"], squat_record["reps"]) == (120, 1)
    assert squat_record["heaviest_weight"] == 120
    assert records[1]["best_estimated_1rm"] == pytest.approx(74.48, abs=0.01)


def test_tied_records_credit_the_earliest_set(client, auth, catalog):
    first = log_workout(client, auth, [(catalog["Squat"], 5, 100)], days_ago=10)
    log_workout(client, auth, [(catalog["Squat"], 5, 100)], days_ago=2)
    [record] = client.get("/api/analytics/personal-records", headers=auth).json()
    assert record["achieved_at"] == first["performed_at"]


def test_weekly_volume_is_zero_filled_and_grouped(db, client, auth, user_id, catalog):
    log_workout(
        client,
        auth,
        [(catalog["Squat"], 5, 100), (catalog["Bench Press"], 5, 60)],
        at=at("2026-03-17"),
    )
    log_workout(client, auth, [(catalog["Deadlift"], 5, 140)], at=at("2026-03-03"))
    log_workout(client, auth, [(catalog["Squat"], 5, 100)], at=at("2026-02-01"))  # out of range

    volume = analytics.weekly_volume(db, user_id, weeks=4, now=NOW)
    assert volume.weeks == [
        date(2026, 2, 23),
        date(2026, 3, 2),
        date(2026, 3, 9),
        date(2026, 3, 16),
    ]
    assert [(s.muscle_group, s.volumes) for s in volume.series] == [
        ("Legs", [0, 0, 0, 500]),
        ("Back", [0, 700, 0, 0]),
        ("Chest", [0, 0, 0, 300]),
    ]


def test_training_frequency_includes_rest_days(db, client, auth, user_id, catalog):
    squat = catalog["Squat"]
    log_workout(client, auth, [(squat, 5, 100)], at=at("2026-03-16"))
    log_workout(client, auth, [(squat, 5, 100)], at=at("2026-03-18", hour=7))
    log_workout(client, auth, [(squat, 5, 100)], at=at("2026-03-18", hour=11))

    frequency = analytics.training_frequency(db, user_id, weeks=2, now=NOW)
    assert (frequency.start, frequency.end) == (date(2026, 3, 9), date(2026, 3, 18))
    assert len(frequency.days) == 10
    sessions = {d.day: d.sessions for d in frequency.days}
    assert sessions[date(2026, 3, 16)] == 1
    assert sessions[date(2026, 3, 18)] == 2
    assert sum(sessions.values()) == frequency.total_sessions == 3
    assert frequency.active_weeks == 1


def _log_series(client, auth, exercise_id, weights, last_day=NOW):
    """One session per weights entry, two days apart, ending the day before last_day."""
    for i, weight in enumerate(reversed(weights)):
        log_workout(
            client, auth, [(exercise_id, 5, weight)], at=last_day - timedelta(days=1 + 2 * i)
        )


def test_plateau_when_recent_sessions_do_not_beat_the_best(db, client, auth, user_id, catalog):
    press = catalog["Overhead Press"]
    _log_series(client, auth, press, [40, 42, 45, 44, 44.5, 43, 45])

    [plateau] = analytics.plateaus(db, user_id, now=NOW)
    assert plateau.exercise_name == "Overhead Press"
    assert plateau.all_time_best == 50.62  # 45 kg x 5
    assert plateau.recent_best == 50.62  # matched, but not beaten
    assert plateau.best_achieved_at == NOW - timedelta(days=9)  # first time 45 kg was hit


@pytest.mark.parametrize(
    ("weights", "last_day"),
    [
        ([40, 42, 43, 44, 45, 46, 47], NOW),  # still improving
        ([45, 44, 44, 44, 44], NOW),  # not enough history before the window
        ([40, 45, 44, 44, 44, 44, 44], NOW - timedelta(days=45)),  # not trained lately
    ],
)
def test_no_plateau_reported(db, client, auth, user_id, catalog, weights, last_day):
    _log_series(client, auth, catalog["Overhead Press"], weights, last_day)
    assert analytics.plateaus(db, user_id, now=NOW) == []


def test_analytics_endpoints_respond(client, auth, squat_history):
    for path in ("weekly-volume?weeks=8", "frequency?weeks=4", "plateaus?window=3"):
        assert client.get(f"/api/analytics/{path}", headers=auth).status_code == 200
