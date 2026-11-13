"""Seed script to bootstrap the initial administrator user from environment settings."""

from pathlib import Path
import sys

# Ensure repository root is on sys.path for direct CLI execution
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import UserRole
from app.schemas.user import UserCreate
from app.services import user_service


def _create_admin_in_session(db: Session, email: str, password: str) -> None:
    existing_user = user_service.get_user_by_email(db, email)
    if existing_user:
        print(f"[Seed] Admin user '{email}' already exists. Skipping.")
        return

    user_create = UserCreate(
        email=email,
        password=password,
        role=UserRole.ADMIN,
    )
    admin = user_service.create_user(db, user_create)
    print(f"[Seed] Successfully created administrator: id={admin.id}, email={admin.email}, role={admin.role.value}")


def seed_admin(db: Session | None = None) -> None:
    """Create the initial admin user if not already present.

    Accepts an optional SQLAlchemy Session (e.g. for testing); otherwise opens SessionLocal.
    """
    email = settings.FIRST_ADMIN_EMAIL
    password = settings.FIRST_ADMIN_PASSWORD

    print(f"[Seed] Checking initial administrator account: {email}")

    if db is not None:
        _create_admin_in_session(db, email, password)
    else:
        with SessionLocal() as session:
            _create_admin_in_session(session, email, password)


if __name__ == "__main__":
    try:
        seed_admin()
    except Exception as exc:
        print(f"[Seed Error] Failed to seed admin: {exc}", file=sys.stderr)
        sys.exit(1)
