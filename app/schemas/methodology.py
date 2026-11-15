"""Pydantic schemas for Methodology records and parameter definitions."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MethodologyBase(BaseModel):
    """Shared baseline properties for a methodology."""

    name: str = Field(
        ...,
        max_length=100,
        description="Name of methodology (e.g. Afforestation, Soil Carbon)",
    )
    version: str = Field(
        ..., max_length=20, description="Version string (e.g. v1, v1.1)"
    )
    parameters: dict[str, Any] = Field(
        ...,
        description="Versioned scientific parameters, coefficients, and default assumptions",
    )
    is_active: bool = Field(
        default=True,
        description="Whether this methodology version is active for new calculations",
    )


class MethodologyCreate(MethodologyBase):
    """Schema for registering a new methodology version."""

    pass


class MethodologyUpdate(BaseModel):
    """Schema for updating an existing methodology (e.g. deprecating or deactivating)."""

    parameters: dict[str, Any] | None = Field(
        default=None, description="Updated parameters dictionary"
    )
    is_active: bool | None = Field(default=None, description="Active status")


class MethodologyRead(MethodologyBase):
    """Public read schema for a methodology."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class MethodologyListResponse(BaseModel):
    """Paginated list envelope for methodologies."""

    items: list[MethodologyRead]
    total: int
    page: int
    page_size: int
