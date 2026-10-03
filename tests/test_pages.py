from datetime import UTC, datetime

import pytest

from app.seed import DEMO_EMAIL, get_or_create_demo_user, seed_demo_history
from app.services import analytics

from helpers import PASSWORD, log_workout, register


def sign_up(client, email="page@example.com"):
    response = client.post("/register", data={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response


def test_pages_redirect_to_login_when_logged_out(client):
    for path in ("/", "/workouts", "/workouts/new"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


def test_htmx_requests_get_an_hx_redirect(client):
    response = client.get("/htmx/plateaus", headers={"HX-Request": "true"})
    assert response.headers["HX-Redirect"] == "/login"


def test_registering_logs_you_in_with_a_secure_cookie(client):
    response = sign_up(client)
    assert "No workouts yet" in response.text
    cookie = response.history[0].headers["set-cookie"]
    assert "access_token=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


@pytest.mark.parametrize(
    ("form", "message"),
    [
        ({"email": "page@example.com", "password": "short"}, "at least 8 characters"),
        ({"email": "nope", "password": PASSWORD}, "Email: value is not a valid email address"),
    ],
)
def test_register_form_shows_validation_errors(client, form, message):
    response = client.post("/register", data=form)
    assert response.status_code == 400
    assert message in response.text


def test_login_form(client):
    register(client, "page@example.com")
    bad = client.post("/login", data={"email": "page@example.com", "password": "wrong-password"})
    assert bad.status_code == 401
    assert "Incorrect email or password." in bad.text

    good = client.post("/login", data={"email": "page@example.com", "password": PASSWORD})
    assert good.status_code == 200
    assert good.url.path == "/"


def test_logout_clears_the_cookie(client):
    sign_up(client)
    response = client.post("/logout", follow_redirects=False)
    assert response.status_code == 303
    assert 'access_token=""' in response.headers["set-cookie"]


def test_login_page_offers_the_demo_account_once_it_exists(client, db):
    assert DEMO_EMAIL not in client.get("/login").text
    get_or_create_demo_user(db)
    assert DEMO_EMAIL in client.get("/login").text


def test_logged_in_pages_and_partials_render(client, catalog):
    sign_up(client)
    squat = catalog["Squat"]
    # The page cookie also authenticates API calls from the browser.
    workout = log_workout(
        client, {}, [(squat, 5, 100), (squat, 5, 100), (squat, 4, 100)], title="Legs"
    )
    log_workout(client, {}, [(squat, 5, 102.5)], days_ago=3)

    dashboard = client.get("/")
    assert f'role="option" data-id="{squat}" aria-selected="true"' in dashboard.text
    assert f'name="exercise_id" value="{squat}"' in dashboard.text
    assert client.get("/workouts/new").status_code == 200

    history = client.get("/workouts").text
    assert "2 workouts" in history
    assert "3 × 5 @ 100 kg" not in history  # mixed reps are listed set by set
    assert "5×100, 5×100, 4×100 kg" in history

    edit = client.get(f"/workouts/{workout['id']}/edit").text
    assert 'value="Legs"' in edit
    assert edit.count('class="set-row') == 3

    assert "Peak est. 1RM" in client.get(f"/htmx/metrics?exercise_id={squat}&days=0").text
    assert "Squat" in client.get("/htmx/personal-records").text
    assert "2 sessions" in client.get("/htmx/heatmap").text
    assert client.get("/htmx/plateaus").text == ""

    row = client.get(f"/htmx/set-row?exercise_id={squat}&reps=8&weight=62.5").text
    assert 'value="62.5"' in row and 'value="8"' in row
    assert f'value="{squat}" selected' in row
    assert client.get("/htmx/set-row?exercise_id=&reps=&weight=").status_code == 200

    assert client.delete(f"/htmx/workouts/{workout['id']}").text == ""
    assert client.get(f"/api/workouts/{workout['id']}").status_code == 404


def test_metrics_partial_handles_an_empty_range(client, catalog):
    sign_up(client)
    log_workout(client, {}, [(catalog["Squat"], 5, 100)], days_ago=100)
    response = client.get(f"/htmx/metrics?exercise_id={catalog['Squat']}&days=30")
    assert "No Squat sessions in this range" in response.text


def test_other_users_workouts_are_not_found(client, catalog):
    owner = register(client, "owner@example.com")
    workout = log_workout(client, owner, [(catalog["Squat"], 5, 100)])
    sign_up(client, "intruder@example.com")

    page = client.get(f"/workouts/{workout['id']}/edit")
    assert page.status_code == 404
    assert f"Workout {workout['id']} not found" in page.text

    fragment = client.delete(f"/htmx/workouts/{workout['id']}", headers={"HX-Request": "true"})
    assert "not found" in fragment.text
    assert client.get(f"/api/workouts/{workout['id']}", headers=owner).status_code == 200


def test_user_content_is_escaped(client, catalog):
    sign_up(client)
    log_workout(client, {}, [(catalog["Squat"], 5, 100)], title="<script>alert(1)</script>")
    history = client.get("/workouts").text
    assert "<script>alert(1)</script>" not in history
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in history


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_demo_seed_produces_a_plateau_to_show(db):
    now = datetime(2026, 9, 1, 12, tzinfo=UTC)
    created = seed_demo_history(db, now=now)
    assert created > 90
    user = get_or_create_demo_user(db)
    assert [p.exercise_name for p in analytics.plateaus(db, user.id, now=now)] == ["Overhead Press"]
