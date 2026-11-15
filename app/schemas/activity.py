"""Pydantic schemas for Activity entities and payload validation."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.activity import ActivityType


class ActivityBase(BaseModel):
    """Shared baseline properties for an agricultural or carbon removal activity."""

    type: ActivityType = Field(
        ...,
        description="Type of field management activity (planting, cover_cropping, mulching, composting)",
    )
    activity_date: date = Field(
        ...,
        description="Date when the activity was performed. Cannot be in the future.",
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON dictionary storing activity-specific parameters (e.g. tree species, biomass weight)",
    )

    @field_validator("activity_date")
    @classmethod
    def validate_not_future(cls, v: date) -> date:
        """Reject future-dated activities per PROJECT_SPEC.md Section 6."""
        if v > date.today():
            raise ValueError("Activity date cannot be in the future.")
        return v


class ActivityCreate(ActivityBase):
    """Schema for recording a new management activity linked to an enrollment."""

    enrollment_id: int = Field(
        ...,
        description="ID of the enrollment this activity belongs to",
    )


class ActivityUpdate(BaseModel):
    """Schema for updating activity details."""

    type: ActivityType | None = Field(default=None)
    activity_date: date | None = Field(default=None)
    details: dict[str, Any] | None = Field(default=None)

    @field_validator("activity_date")
    @classmethod
    def validate_not_future(cls, v: date | None) -> date | None:
        """Reject future-dated updates."""
        if v is not None and v > date.today():
            raise ValueError("Activity date cannot be in the future.")
        return v


class ActivityRead(ActivityBase):
    """Public read schema representing a persisted activity record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    enrollment_id: int
    created_at: datetime


class ActivityListResponse(BaseModel):
    """Paginated list envelope for activity records."""

    items: list[ActivityRead]
    total: int
    page: int
    page_size: int
