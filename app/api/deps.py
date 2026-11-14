"""Shared API dependencies for FastAPI routers."""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models.user import User, UserRole
from app.services import user_service

# OAuth2 scheme for extracting Bearer tokens from HTTP Authorization header
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login",
    auto_error=False,
)


def get_db() -> Generator[Session, None, None]:
    """Yield a transactional database session per request and close it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Type alias for database session injection
SessionDep = Annotated[Session, Depends(get_db)]


def get_current_user_optional(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: SessionDep,
) -> User | None:
    """Optionally extract the current user if a valid Bearer token is provided."""
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub", 0))
    except (jwt.PyJWTError, ValueError):
        return None

    return user_service.get_user_by_id(db, user_id=user_id)


def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: SessionDep,
) -> User:
    """Validate Bearer token and return the active User record.

    Raises:
        HTTPException 401: If token is missing, expired, invalid, or user inactive.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception

    try:
        payload = decode_access_token(token)
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise credentials_exception
        user_id = int(user_id_str)
    except (jwt.PyJWTError, ValueError) as exc:
        raise credentials_exception from exc

    user = user_service.get_user_by_id(db, user_id=user_id)
    if not user:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
OptionalUserDep = Annotated[User | None, Depends(get_current_user_optional)]


def require_roles(*allowed_roles: UserRole):
    """Factory dependency verifying the authenticated user holds an authorized role."""

    def role_checker(current_user: CurrentUserDep) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted. Requires role in {[r.value for r in allowed_roles]}",
            )
        return current_user

    return role_checker


# Alias for singular/plural flexibility
require_role = require_roles

# Convenient dependency for admin-only endpoints
AdminUserDep = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
