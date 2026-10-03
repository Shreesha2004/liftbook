import pytest

from helpers import log_workout, register


def test_catalog_is_shared(client, auth):
    exercises = client.get("/api/exercises", headers=auth).json()
    names = {e["name"] for e in exercises}
    assert {"Squat", "Bench Press", "Deadlift", "Overhead Press"} <= names
    assert not any(e["is_custom"] for e in exercises)


def test_custom_exercises_are_private(client, catalog):
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")
    response = client.post(
        "/api/exercises", headers=alice, json={"name": "  Hip   Thrust ", "muscle_group": "Legs"}
    )
    assert response.status_code == 201
    hip_thrust = response.json()
    assert hip_thrust["name"] == "Hip Thrust"
    assert hip_thrust["is_custom"] is True

    log_workout(client, alice, [(hip_thrust["id"], 8, 120)])
    assert "Hip Thrust" not in {e["name"] for e in client.get("/api/exercises", headers=bob).json()}
    response = client.post(
        "/api/workouts",
        headers=bob,
        json={"title": "x", "sets": [{"exercise_id": hip_thrust["id"], "reps": 8, "weight": 1}]},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("name", ["squat", "Hip Thrust"])
def test_exercise_names_cannot_clash(client, auth, name):
    client.post("/api/exercises", headers=auth, json={"name": "Hip Thrust", "muscle_group": "Legs"})
    response = client.post(
        "/api/exercises", headers=auth, json={"name": name, "muscle_group": "Legs"}
    )
    assert response.status_code == 409


def test_muscle_group_must_be_known(client, auth):
    response = client.post(
        "/api/exercises", headers=auth, json={"name": "Neck Curl", "muscle_group": "Neck"}
    )
    assert response.status_code == 422
