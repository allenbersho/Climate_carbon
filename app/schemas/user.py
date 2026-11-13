"""Pydantic schemas for User validation and serialization."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserBase(BaseModel):
    """Shared user properties."""

    email: EmailStr
    role: UserRole = UserRole.FIELD_OFFICER


class UserCreate(UserBase):
    """Schema for user creation (accepts plain password)."""

    password: str = Field(
        ...,
        min_length=8,
        description="Plaintext password (minimum 8 characters)",
    )


class UserRead(UserBase):
    """Public user schema returned in API responses.

    Note: hashed_password and password are never included here.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime


class LoginRequest(BaseModel):
    """Payload for user login requests."""

    email: EmailStr
    password: str


class Token(BaseModel):
    """Schema for JWT authentication responses."""

    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    """Decoded JWT payload data."""

    sub: str
    role: str
    exp: int
    iat: int
