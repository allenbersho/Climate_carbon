"""Pydantic schemas for Enrollment entities."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enrollment import EnrollmentStatus


class EnrollmentBase(BaseModel):
    """Shared baseline properties for an enrollment."""

    project_id: int = Field(..., description="ID of the project being enrolled into")
    parcel_id: int = Field(..., description="ID of the land parcel being enrolled")
    farmer_id: int = Field(..., description="ID of the farmer owning the parcel")
    baseline_date: date | None = Field(
        default=None,
        description="Date when the baseline measurement was established",
    )
    status: EnrollmentStatus = Field(
        default=EnrollmentStatus.ACTIVE,
        description="Current lifecycle status of the enrollment",
    )
    additionality_note: str | None = Field(
        default=None,
        description="Justification note documenting additionality criteria",
    )


class EnrollmentCreate(EnrollmentBase):
    """Schema for creating a new project enrollment."""

    pass


class EnrollmentUpdate(BaseModel):
    """Schema for updating an existing enrollment."""

    status: EnrollmentStatus | None = Field(
        default=None,
        description="Updated lifecycle status (e.g. active, completed, terminated)",
    )
    baseline_date: date | None = Field(
        default=None,
        description="Updated baseline measurement date",
    )
    additionality_note: str | None = Field(
        default=None,
        description="Updated additionality rationale or notes",
    )


class EnrollmentRead(EnrollmentBase):
    """Public read schema representing an enrollment record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class EnrollmentListResponse(BaseModel):
    """Paginated list envelope per PROJECT_SPEC.md Section 8."""

    items: list[EnrollmentRead]
    total: int
    page: int
    page_size: int
