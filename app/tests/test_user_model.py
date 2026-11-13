"""Tests for User model, constraints, and Pydantic schemas."""

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserRead


def test_create_user_model(db_session: Session) -> None:
    """Verify creating a User in the database with valid fields."""
    user = User(
        email="farmer.john@example.com",
        hashed_password="argon2_hashed_dummy_password",
        role=UserRole.FIELD_OFFICER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    assert user.id is not None
    assert user.email == "farmer.john@example.com"
    assert user.role == UserRole.FIELD_OFFICER
    assert user.is_active is True
    assert user.created_at is not None


def test_user_email_unique_constraint(db_session: Session) -> None:
    """Verify that inserting two users with the same email raises IntegrityError."""
    user1 = User(
        email="duplicate@example.com",
        hashed_password="hash1",
        role=UserRole.ADMIN,
    )
    db_session.add(user1)
    db_session.commit()

    user2 = User(
        email="duplicate@example.com",
        hashed_password="hash2",
        role=UserRole.VERIFIER,
    )
    db_session.add(user2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_user_create_schema_validation() -> None:
    """Verify UserCreate schema validates inputs and rejects invalid data."""
    # Valid input
    valid = UserCreate(
        email="officer@carbontrack.org",
        password="securepassword123",
        role=UserRole.FIELD_OFFICER,
    )
    assert valid.email == "officer@carbontrack.org"
    assert valid.role == UserRole.FIELD_OFFICER

    # Invalid email rejected
    with pytest.raises(ValidationError):
        UserCreate(email="not-an-email", password="securepassword123")

    # Short password rejected (<8 chars)
    with pytest.raises(ValidationError):
        UserCreate(email="officer@carbontrack.org", password="short")


def test_user_read_schema_never_exposes_password(db_session: Session) -> None:
    """Verify UserRead serializes User model and never exposes password fields."""
    user = User(
        email="verifier@carbontrack.org",
        hashed_password="super_secret_argon2_hash",
        role=UserRole.VERIFIER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    user_read = UserRead.model_validate(user)

    # Validate output dictionary
    user_dict = user_read.model_dump()
    assert user_dict["id"] == user.id
    assert user_dict["email"] == "verifier@carbontrack.org"
    assert user_dict["role"] == UserRole.VERIFIER
    assert user_dict["is_active"] is True
    assert "created_at" in user_dict

    # Crucial security guarantee: password and hashed_password must never exist in UserRead
    assert "hashed_password" not in user_dict
    assert "password" not in user_dict
    assert "hashed_password" not in UserRead.model_fields
    assert "password" not in UserRead.model_fields
