from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

PASSWORD = "correct-horse-battery"


def register(
    client: TestClient, email: str = "lifter@example.com", password: str = PASSWORD
) -> dict[str, str]:
    """Create an account through the API and return Authorization headers for it."""
    response = client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    response = client.post("/api/auth/token", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def log_workout(
    client: TestClient,
    headers: dict[str, str],
    sets: list[tuple[int, int, float]],
    *,
    at: datetime | None = None,
    days_ago: float = 0,
    title: str = "Session",
) -> dict:
    """Log a workout. `sets` is a list of (exercise_id, reps, weight)."""
    performed_at = at or datetime.now(UTC) - timedelta(days=days_ago)
    response = client.post(
        "/api/workouts",
        headers=headers,
        json={
            "title": title,
            "performed_at": performed_at.isoformat(),
            "sets": [{"exercise_id": e, "reps": r, "weight": w} for e, r, w in sets],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()
