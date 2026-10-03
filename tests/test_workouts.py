import pytest

from helpers import log_workout, register


def test_create_and_fetch_a_workout(client, auth, catalog):
    squat = catalog["Squat"]
    created = log_workout(client, auth, [(squat, 5, 100), (squat, 3, 110)], title="Leg day")

    assert created["title"] == "Leg day"
    assert created["total_volume"] == 830
    assert [s["exercise_name"] for s in created["sets"]] == ["Squat", "Squat"]
    assert [s["estimated_1rm"] for s in created["sets"]] == [112.5, 116.47]

    fetched = client.get(f"/api/workouts/{created['id']}", headers=auth)
    assert fetched.status_code == 200
    created.pop("new_personal_records")
    assert fetched.json() == created


def test_performed_at_defaults_to_now(client, auth, catalog):
    response = client.post(
        "/api/workouts",
        headers=auth,
        json={"title": "Quick", "sets": [{"exercise_id": catalog["Dip"], "reps": 10, "weight": 0}]},
    )
    assert response.status_code == 201
    assert response.json()["performed_at"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"sets": []}, "at least 1 item"),
        ({"sets": [{"exercise_id": 1, "reps": 0, "weight": 100}]}, "greater than or equal to 1"),
        ({"sets": [{"exercise_id": 1, "reps": 37, "weight": 100}]}, "less than or equal to 36"),
        ({"sets": [{"exercise_id": 1, "reps": 5, "weight": -1}]}, "greater than or equal to 0"),
        ({"title": ""}, "at least 1 character"),
        ({"performed_at": "2999-01-01T00:00:00Z"}, "cannot be in the future"),
    ],
)
def test_invalid_workouts_are_rejected(client, auth, catalog, change, message):
    payload = {
        "title": "Session",
        "sets": [{"exercise_id": catalog["Squat"], "reps": 5, "weight": 100}],
    } | change
    response = client.post("/api/workouts", headers=auth, json=payload)
    assert response.status_code == 422
    assert message in response.text


def test_sets_must_reference_a_known_exercise(client, auth):
    response = client.post(
        "/api/workouts",
        headers=auth,
        json={"title": "Session", "sets": [{"exercise_id": 999999, "reps": 5, "weight": 100}]},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown exercise id(s): 999999"


def test_list_is_newest_first_and_paginated(client, auth, catalog):
    for days_ago in (3, 1, 2):
        log_workout(
            client, auth, [(catalog["Squat"], 5, 100)], days_ago=days_ago, title=f"{days_ago}d"
        )

    first = client.get("/api/workouts?limit=2", headers=auth).json()
    assert first["total"] == 3
    assert [w["title"] for w in first["items"]] == ["1d", "2d"]

    rest = client.get("/api/workouts?skip=2&limit=2", headers=auth).json()
    assert [w["title"] for w in rest["items"]] == ["3d"]


def test_update_replaces_details_and_sets(client, auth, catalog):
    original = log_workout(client, auth, [(catalog["Squat"], 5, 100)] * 3, days_ago=2)
    response = client.put(
        f"/api/workouts/{original['id']}",
        headers=auth,
        json={
            "title": "Edited",
            "notes": "felt strong",
            "sets": [{"exercise_id": catalog["Bench Press"], "reps": 8, "weight": 60}],
        },
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["title"] == "Edited"
    assert updated["notes"] == "felt strong"
    assert [(s["exercise_name"], s["reps"], s["weight"]) for s in updated["sets"]] == [
        ("Bench Press", 8, 60)
    ]
    assert updated["performed_at"] == original["performed_at"]  # kept when not sent


def test_delete(client, auth, catalog):
    workout = log_workout(client, auth, [(catalog["Squat"], 5, 100)])
    assert client.delete(f"/api/workouts/{workout['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/workouts/{workout['id']}", headers=auth).status_code == 404


def test_summary_totals_each_exercise(client, auth, catalog):
    workout = log_workout(
        client,
        auth,
        [(catalog["Squat"], 5, 100), (catalog["Squat"], 5, 110), (catalog["Bench Press"], 8, 60)],
    )
    summary = client.get(f"/api/workouts/{workout['id']}/summary", headers=auth).json()
    assert summary["total_sets"] == 3
    assert summary["total_reps"] == 18
    assert summary["total_volume"] == 1530
    by_name = {e["exercise_name"]: e for e in summary["exercises"]}
    assert by_name["Squat"]["total_volume"] == 1050
    assert by_name["Squat"]["best_estimated_1rm"] == 123.75
    assert by_name["Bench Press"]["total_sets"] == 1


def test_users_cannot_touch_each_others_workouts(client, catalog):
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")
    workout = log_workout(client, alice, [(catalog["Squat"], 5, 100)])
    url = f"/api/workouts/{workout['id']}"
    replacement = {
        "title": "Mine now",
        "sets": [{"exercise_id": catalog["Squat"], "reps": 1, "weight": 1}],
    }

    assert client.get(url, headers=bob).status_code == 404
    assert client.put(url, headers=bob, json=replacement).status_code == 404
    assert client.delete(url, headers=bob).status_code == 404
    assert client.get("/api/workouts", headers=bob).json()["total"] == 0
    assert client.get(url, headers=alice).json()["title"] == "Session"


def test_new_estimated_1rm_records_are_reported(client, auth, catalog):
    squat, bench = catalog["Squat"], catalog["Bench Press"]
    first = log_workout(client, auth, [(squat, 5, 100)], days_ago=7)
    assert first["new_personal_records"] == []  # nothing to beat yet

    tie = log_workout(client, auth, [(squat, 5, 100)], days_ago=3)
    assert tie["new_personal_records"] == []

    better = log_workout(client, auth, [(squat, 5, 105), (squat, 5, 95), (bench, 5, 60)])
    [record] = better["new_personal_records"]
    assert record["exercise_name"] == "Squat"
    assert record["estimated_1rm"] == pytest.approx(118.125, abs=0.01)
    assert record["previous_best"] == 112.5
