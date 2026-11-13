"""Security utilities: Argon2 password hashing and JWT token handling."""

from datetime import datetime, timedelta, timezone
from typing import Any

import argon2
import argon2.exceptions
import jwt

from app.core.config import settings

# Initialize Argon2id password hasher (OWASP recommended parameters)
_password_hasher = argon2.PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id with automatic salt generation."""
    return _password_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against an Argon2 hash.

    Returns True if valid, False otherwise.
    """
    try:
        return _password_hasher.verify(hashed_password, plain_password)
    except (
        argon2.exceptions.VerifyMismatchError,
        argon2.exceptions.VerificationError,
        argon2.exceptions.InvalidHashError,
    ):
        return False


def create_access_token(
    subject: str | int,
    role: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT access token with an expiration timestamp."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "exp": expire,
        "iat": now,
    }

    if extra_claims:
        to_encode.update(extra_claims)

    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a signed JWT token.

    Raises:
        jwt.ExpiredSignatureError: When the token has expired.
        jwt.InvalidTokenError: When the signature or format is invalid.
    """
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
    )
    return payload
