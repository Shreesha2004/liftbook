"""Run before the web server starts: migrate the database, then optionally seed demo data.

python -m app.prestart
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.config import settings
from app.database import SessionLocal, engine
from app.seed import DEMO_EMAIL, seed_if_empty

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("prestart")


def migrate() -> None:
    config = Config(toml_file=str(ROOT / "pyproject.toml"))
    inspector = inspect(engine)
    if inspector.has_table("workouts") and not inspector.has_table("alembic_version"):
        # Created by the original create_all() version of the app, which matches revision 0001.
        log.info("Existing pre-Alembic schema found; marking it as revision 0001")
        command.stamp(config, "0001")
    command.upgrade(config, "head")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    migrate()
    if settings.SEED_DEMO_DATA:
        with SessionLocal() as db:
            created = seed_if_empty(db)
        log.info("Demo data: %s", f"seeded {created} workouts" if created else "already present")
        log.info("Demo login: %s", DEMO_EMAIL)


if __name__ == "__main__":
    main()
