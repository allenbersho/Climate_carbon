"""User domain services and business logic."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.user import UserCreate


def get_user_by_email(db: Session, email: str) -> User | None:
    """Retrieve a single active or inactive user by exact email address.

    Why: Used during registration to check duplicates, and during login authentication.
    Inputs: db (SQLAlchemy session), email (case-normalized string)
    Outputs: User model instance if found, None otherwise.
    """
    normalized_email = email.strip().lower()
    statement = select(User).where(func.lower(User.email) == normalized_email)
    return db.execute(statement).scalar_one_or_none()


def get_user_by_id(db: Session, user_id: int) -> User | None:
    """Retrieve a user by primary key ID.

    Why: Used by authentication dependencies to fetch the current user from JWT 'sub'.
    Inputs: db (SQLAlchemy session), user_id (integer primary key)
    Outputs: User model instance if found, None otherwise.
    """
    return db.get(User, user_id)


def count_users(db: Session) -> int:
    """Count the total number of users registered in the database.

    Why: Determines whether the system is bootstrapping (allowing first user registration)
         or requiring existing admin credentials to register subsequent users.
    Inputs: db (SQLAlchemy session)
    Outputs: Total integer count of user records.
    """
    statement = select(func.count(User.id))
    return db.execute(statement).scalar_one() or 0


def create_user(db: Session, user_create: UserCreate) -> User:
    """Create a new user with a securely hashed Argon2 password.

    Why: Enforces that plain passwords are never persisted to disk.
    Inputs: db (SQLAlchemy session), user_create (validated Pydantic schema)
    Outputs: Newly persisted User model instance.
    """
    hashed_pwd = hash_password(user_create.password)
    user = User(
        email=user_create.email.strip().lower(),
        hashed_password=hashed_pwd,
        role=user_create.role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """Authenticate credentials against database records.

    Why: Centralizes login verification logic away from API controllers.
    Inputs: db (SQLAlchemy session), email (plain string), password (plaintext string)
    Outputs: Authenticated User model if valid and active, None otherwise.
    """
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
