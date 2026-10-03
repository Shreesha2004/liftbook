from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import settings

from helpers import PASSWORD, register


def test_register_returns_the_user_without_password_data(client):
    response = client.post(
        "/api/auth/register",
        json={"email": "Ana@Example.com", "password": PASSWORD, "display_name": "Ana"},
    )
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "email", "display_name", "created_at"}
    assert body["email"] == "ana@example.com"
    assert body["display_name"] == "Ana"


def test_email_must_be_unique_ignoring_case(client):
    register(client, "ana@example.com")
    response = client.post(
        "/api/auth/register", json={"email": "ANA@example.com", "password": PASSWORD}
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": PASSWORD},
        {"email": "ana@example.com", "password": "short"},
    ],
)
def test_register_validates_input(client, payload):
    assert client.post("/api/auth/register", json=payload).status_code == 422


def test_token_unlocks_me(client):
    headers = register(client, "ana@example.com")
    response = client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["email"] == "ana@example.com"


def test_login_is_case_insensitive_on_email(client):
    register(client, "ana@example.com")
    response = client.post(
        "/api/auth/token", data={"username": "Ana@Example.COM", "password": PASSWORD}
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("username", "password"),
    [("ana@example.com", "wrong-password"), ("nobody@example.com", PASSWORD)],
)
def test_bad_credentials_get_the_same_answer(client, username, password):
    register(client, "ana@example.com")
    response = client.post("/api/auth/token", data={"username": username, "password": password})
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/me",
        "/api/workouts",
        "/api/exercises",
        "/api/analytics/personal-records",
        "/api/analytics/weekly-volume",
    ],
)
def test_api_requires_authentication(client, path):
    response = client.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_tampered_token_is_rejected(client):
    headers = register(client)
    token = headers["Authorization"].removeprefix("Bearer ")
    forged = jwt.encode({"sub": "1"}, "an-attacker-chosen-secret-of-32-bytes", algorithm="HS256")
    for bad in (token[:-2] + "xx", forged):
        response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {bad}"})
        assert response.status_code == 401


def test_expired_token_is_rejected(client):
    user_id = client.get("/api/auth/me", headers=register(client)).json()["id"]
    expired = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) - timedelta(minutes=1)},
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401
