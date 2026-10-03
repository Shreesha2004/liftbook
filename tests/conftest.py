import os

os.environ["ENVIRONMENT"] = "test"
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.main import app
from app.models import Exercise

from helpers import register

ROOT = Path(__file__).resolve().parent.parent


def _test_database_url() -> URL:
    """TEST_DATABASE_URL, or DATABASE_URL with "_test" appended to the database name."""
    if explicit := os.environ.get("TEST_DATABASE_URL"):
        url = make_url(explicit)
    else:
        url = make_url(settings.DATABASE_URL)
        url = url.set(database=f"{url.database}_test")
    if not (url.database or "").endswith("_test"):
        raise RuntimeError(f"Refusing to use {url.database!r}: test databases must end in _test")
    return url


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """A fresh database built by running every migration, once per test run."""
    url = _test_database_url()
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()

    engine = create_engine(url, connect_args={"options": "-c timezone=UTC"})
    config = Config(toml_file=str(ROOT / "pyproject.toml"))
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """A session inside a transaction that is rolled back after the test.

    The app's own commits become savepoint releases, so nothing persists between tests.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def catalog(db: Session) -> dict[str, int]:
    """Catalog exercise name -> id."""
    rows = db.execute(select(Exercise.name, Exercise.id).where(Exercise.user_id.is_(None)))
    return dict(rows.all())


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    """Authorization headers for a freshly registered user."""
    return register(client)


@pytest.fixture
def user_id(client: TestClient, auth: dict[str, str]) -> int:
    return client.get("/api/auth/me", headers=auth).json()["id"]
