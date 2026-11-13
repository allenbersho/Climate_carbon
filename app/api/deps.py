"""Shared API dependencies for FastAPI routers."""

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Yield a transactional database session per request and close it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Type alias for easy dependency injection in route functions
SessionDep = Annotated[Session, Depends(get_db)]
