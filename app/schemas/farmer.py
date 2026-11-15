"""Pydantic schemas for Farmer entities."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FarmerBase(BaseModel):
    """Shared baseline properties for a farmer."""

    name: str = Field(
        ..., min_length=2, max_length=255, description="Full name of the farmer"
    )
    phone: str | None = Field(
        default=None, max_length=50, description="Contact phone number"
    )
    village: str | None = Field(
        default=None, max_length=255, description="Village name"
    )
    district: str | None = Field(
        default=None, max_length=255, description="Administrative district"
    )
    state: str | None = Field(
        default=None, max_length=255, description="State / Province"
    )


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
            raise ValueError(
                "Farmer consent must be recorded as True to enroll in CarbonTrack"
            )
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


class FarmerImportRowError(BaseModel):
    """Details of a single CSV row validation failure during bulk import."""

    row_number: int = Field(
        ..., description="1-indexed row number in the CSV file (row 1 is header)"
    )
    data: dict[str, str | None] = Field(
        ..., description="Raw row values parsed from the CSV"
    )
    reason: str = Field(
        ..., description="Description of why this row failed validation"
    )


class FarmerBulkImportResult(BaseModel):
    """Aggregated outcome of a CSV bulk farmer import operation."""

    total_rows: int = Field(
        ..., description="Total data rows evaluated (excluding header)"
    )
    imported_count: int = Field(
        ..., description="Number of valid farmer records successfully created"
    )
    failed_count: int = Field(
        ..., description="Number of rows rejected due to validation errors"
    )
    errors: list[FarmerImportRowError] = Field(
        default_factory=list,
        description="Detailed list of error diagnostics for each rejected row",
    )
