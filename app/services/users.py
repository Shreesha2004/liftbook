from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError
from app.models import User
from app.schemas import UserCreate
from app.security import hash_password, verify_password


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


def register(db: Session, data: UserCreate) -> User:
    if get_by_email(db, data.email):
        raise ConflictError("An account with this email already exists")
    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        display_name=data.display_name,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # lost a race with a concurrent signup
        db.rollback()
        raise ConflictError("An account with this email already exists") from None
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = get_by_email(db, email)
    if not verify_password(password, user.hashed_password if user else None):
        return None
    return user
