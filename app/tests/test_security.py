"""Unit tests for Argon2 password hashing and JWT security functions."""

from datetime import timedelta

import jwt
import pytest

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hashing_and_verification() -> None:
    """Verify password hashing produces verifiable hashes and rejects wrong passwords."""
    raw_password = "CorrectHorseBatteryStaple123!"
    hashed = hash_password(raw_password)

    # Must not store plaintext
    assert hashed != raw_password
    assert "$argon2" in hashed

    # Valid password verification succeeds
    assert verify_password(raw_password, hashed) is True

    # Incorrect password verification fails
    assert verify_password("WrongPassword123!", hashed) is False


def test_password_salting_uniqueness() -> None:
    """Verify that hashing the same password twice yields distinct hashes due to random salting."""
    raw_password = "identical_password_value"
    hash1 = hash_password(raw_password)
    hash2 = hash_password(raw_password)

    # Distinct salts ensure hashes are never identical
    assert hash1 != hash2

    # Both hashes must still verify the original password
    assert verify_password(raw_password, hash1) is True
    assert verify_password(raw_password, hash2) is True


def test_verify_password_invalid_hash() -> None:
    """Verify malformed hash strings fail safely without throwing unhandled exceptions."""
    assert verify_password("secret", "invalid$not$a$hash") is False
    assert verify_password("secret", "") is False


def test_jwt_create_and_decode() -> None:
    """Verify creating and decoding a valid JWT access token."""
    user_id = 42
    role = "field_officer"

    token = create_access_token(
        subject=user_id,
        role=role,
        expires_delta=timedelta(minutes=15),
    )

    assert isinstance(token, str)

    payload = decode_access_token(token)
    assert payload["sub"] == "42"
    assert payload["role"] == "field_officer"
    assert "exp" in payload
    assert "iat" in payload


def test_jwt_expiration() -> None:
    """Verify that an expired JWT token raises ExpiredSignatureError upon decoding."""
    expired_token = create_access_token(
        subject="1",
        role="admin",
        expires_delta=timedelta(seconds=-1),  # Already expired
    )

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired_token)


def test_jwt_tampered_signature() -> None:
    """Verify that tampering with token content raises InvalidTokenError."""
    token = create_access_token(subject="1", role="admin")

    # Tamper with the token string
    tampered_token = token[:-4] + "ABCD"

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(tampered_token)


def test_jwt_wrong_secret() -> None:
    """Verify token signed with an unauthorized secret fails decoding."""
    unauthorized_token = jwt.encode(
        {"sub": "1", "role": "admin"},
        key="unauthorized-malicious-attacker-secret-key!",
        algorithm="HS256",
    )

    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(unauthorized_token)
