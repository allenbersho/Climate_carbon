"""Pydantic schemas for Farmer entities."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


class FarmerBase(BaseModel):
    """Shared baseline properties for a farmer."""

    name: str = Field(..., min_length=2, max_length=255, description="Full name of the farmer")
    phone: str | None = Field(default=None, max_length=50, description="Contact phone number")
    village: str | None = Field(default=None, max_length=255, description="Village name")
    district: str | None = Field(default=None, max_length=255, description="Administrative district")
    state: str | None = Field(default=None, max_length=255, description="State / Province")


class FarmerCreate(FarmerBase):
    """Schema for registering a new farmer.

    Business rule: consent_given is required to create.
    """

    consent_given: bool = Field(
        ...,
        description="Whether the farmer signed/provided formal MRV project consent (must be True)",
    )

    @field_validator("consent_given")
    @classmethod
    def validate_consent_required(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Farmer consent must be recorded as True to enroll in CarbonTrack")
        return v


class FarmerUpdate(BaseModel):
    """Schema for updating farmer details (partial updates allowed)."""

    name: str | None = Field(default=None, min_length=2, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    village: str | None = Field(default=None, max_length=255)
    district: str | None = Field(default=None, max_length=255)
    state: str | None = Field(default=None, max_length=255)
    consent_given: bool | None = None


class FarmerRead(FarmerBase):
    """Public read schema representing a farmer."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    consent_given: bool
    is_deleted: bool
    created_at: datetime


class FarmerListResponse(BaseModel):
    """Paginated list response format per PROJECT_SPEC.md Section 8."""

    items: list[FarmerRead]
    total: int
    page: int
    page_size: int
