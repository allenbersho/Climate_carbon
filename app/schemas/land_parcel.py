"""Pydantic schemas for LandParcel entities."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LandParcelBase(BaseModel):
    """Shared baseline properties for a land parcel."""

    area_acres: float = Field(
        ...,
        gt=0,
        description="Parcel land area in acres (strictly positive > 0)",
    )
    soil_type: str | None = Field(
        default=None,
        max_length=100,
        description="Soil classification (e.g. clay_loam, sandy, black_soil)",
    )
    crop: str | None = Field(
        default=None,
        max_length=100,
        description="Primary crop or vegetation cover",
    )


class LandParcelCreate(LandParcelBase):
    """Schema for registering a new land parcel linked to a farmer."""

    farmer_id: int = Field(
        ...,
        description="Foreign key ID of the farmer who owns this parcel",
    )


class LandParcelUpdate(BaseModel):
    """Schema for updating parcel details."""

    area_acres: float | None = Field(default=None, gt=0)
    soil_type: str | None = Field(default=None, max_length=100)
    crop: str | None = Field(default=None, max_length=100)


class LandParcelRead(LandParcelBase):
    """Public read schema representing a land parcel."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    farmer_id: int
    created_at: datetime


class LandParcelListResponse(BaseModel):
    """Paginated list response format per PROJECT_SPEC.md Section 8."""

    items: list[LandParcelRead]
    total: int
    page: int
    page_size: int
