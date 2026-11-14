"""Pydantic schemas for Observation entities, polymorphic values validation, and append-only audits."""

from datetime import datetime, timezone
from typing import Any, Self
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.observation import ObservationType


class SoilObservationValues(BaseModel):
    """Schema for soil organic carbon monitoring data."""

    soc_percent: float = Field(
        ...,
        gt=0,
        le=100,
        description="Soil organic carbon percentage of soil mass (0 < soc_percent <= 100)",
    )
    bulk_density: float = Field(
        ...,
        gt=0,
        description="Soil bulk density in g/cm³ (> 0)",
    )
    depth_cm: float = Field(
        ...,
        gt=0,
        description="Soil core sampling depth in cm (> 0)",
    )


class TreeCountObservationValues(BaseModel):
    """Schema for forestry and agroforestry tree count monitoring data."""

    count: int = Field(
        ...,
        ge=0,
        description="Number of living standing trees (>= 0)",
    )
    avg_height_m: float = Field(
        ...,
        gt=0,
        description="Average tree height in meters (> 0)",
    )


class BiomassObservationValues(BaseModel):
    """Schema for biomass measurement observations."""

    biomass_kg_per_m2: float = Field(
        ...,
        gt=0,
        description="Dry biomass yield in kg/m² (> 0)",
    )


def validate_observation_values(obs_type: ObservationType, values: dict[str, Any]) -> dict[str, Any]:
    """Validate that the raw dictionary conforms to the required schema for its observation type."""
    if obs_type == ObservationType.SOIL:
        return SoilObservationValues.model_validate(values).model_dump()
    if obs_type == ObservationType.TREE_COUNT:
        return TreeCountObservationValues.model_validate(values).model_dump()
    if obs_type == ObservationType.BIOMASS:
        return BiomassObservationValues.model_validate(values).model_dump()
    raise ValueError(f"Unknown observation type: {obs_type}")


class ObservationBase(BaseModel):
    """Shared baseline properties for an observation."""

    type: ObservationType = Field(
        ...,
        description="Measurement type (soil, tree_count, biomass)",
    )
    values: dict[str, Any] = Field(
        ...,
        description="Type-specific observation measurements",
    )
    observed_at: datetime = Field(
        ...,
        description="UTC timestamp when measurement was collected. Future dates rejected.",
    )
    is_baseline: bool = Field(
        default=False,
        description="True if this observation represents the pre-project baseline measurement",
    )

    @field_validator("observed_at")
    @classmethod
    def validate_not_future(cls, v: datetime) -> datetime:
        """Reject future-dated observations per PROJECT_SPEC.md Section 6 Rule 7."""
        now = datetime.now(timezone.utc)
        v_utc = v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
        if v_utc > now:
            raise ValueError("Observation timestamp cannot be in the future.")
        return v

    @model_validator(mode="after")
    def validate_values_shape(self) -> Self:
        """Enforce strict type-specific schema validation on values."""
        try:
            self.values = validate_observation_values(self.type, self.values)
        except Exception as exc:
            raise ValueError(f"Invalid values for {self.type.value} observation: {exc}") from exc
        return self


class ObservationCreate(ObservationBase):
    """Schema for recording a new observation."""

    enrollment_id: int = Field(
        ...,
        description="ID of the enrollment this observation monitors",
    )


class ObservationCorrectionCreate(BaseModel):
    """Schema for correcting an erroneous observation (append-only correction)."""

    values: dict[str, Any] = Field(
        ...,
        description="Corrected measurement values matching the original observation type",
    )
    observed_at: datetime = Field(
        ...,
        description="Measurement timestamp. Cannot be in the future.",
    )
    is_baseline: bool | None = Field(
        default=None,
        description="Optionally update baseline flag; defaults to original observation's flag if omitted",
    )

    @field_validator("observed_at")
    @classmethod
    def validate_not_future(cls, v: datetime) -> datetime:
        """Reject future dates."""
        now = datetime.now(timezone.utc)
        v_utc = v if v.tzinfo is not None else v.replace(tzinfo=timezone.utc)
        if v_utc > now:
            raise ValueError("Observation timestamp cannot be in the future.")
        return v


class ObservationRead(BaseModel):
    """Public read schema for an observation record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    enrollment_id: int
    type: ObservationType
    values: dict[str, Any]
    observed_at: datetime
    observer_id: int
    is_baseline: bool
    superseded_by: int | None
    created_at: datetime


class ObservationListResponse(BaseModel):
    """Paginated list envelope for observation records."""

    items: list[ObservationRead]
    total: int
    page: int
    page_size: int
