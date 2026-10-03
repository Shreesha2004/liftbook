from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# Sessions run in UTC so returned timestamps match the UTC day/week bucketing in analytics.
engine = create_engine(
    settings.DATABASE_URL, pool_pre_ping=True, connect_args={"options": "-c timezone=UTC"}
)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db
