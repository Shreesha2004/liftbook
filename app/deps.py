from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import LoginRequired
from app.models import User
from app.security import decode_access_token

AUTH_COOKIE = "access_token"

# auto_error=False so the browser UI can fall back to the httpOnly cookie.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_optional_user(
    request: Request,
    db: DbSession,
    bearer_token: Annotated[str | None, Depends(oauth2_scheme)],
) -> User | None:
    """Resolve the user from an `Authorization: Bearer` header (API) or the auth cookie (UI)."""
    token = bearer_token or request.cookies.get(AUTH_COOKIE)
    if not token:
        return None
    user_id = decode_access_token(token)
    return db.get(User, user_id) if user_id is not None else None


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def get_current_user(user: OptionalUser) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_page_user(user: OptionalUser) -> User:
    if user is None:
        raise LoginRequired
    return user


PageUser = Annotated[User, Depends(get_page_user)]
