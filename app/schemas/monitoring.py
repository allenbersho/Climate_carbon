"""Pydantic schemas for monitoring timelines and baseline progression."""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from app.models.observation import ObservationType


class TimelineObservationItem(BaseModel):
    """An individual observation item in the chronological timeline with delta from baseline."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Observation ID")
    type: ObservationType = Field(..., description="Observation measurement type")
    observed_at: datetime = Field(..., description="Timestamp when measurement was recorded")
    is_baseline: bool = Field(..., description="True if this is the pre-project baseline measurement")
    is_superseded: bool = Field(..., description="True if this observation was replaced by a correction")
    superseded_by: int | None = Field(default=None, description="ID of superseding observation if corrected")
    values: dict[str, Any] = Field(..., description="Raw measurement values")
    baseline_id: int | None = Field(
        default=None,
        description="ID of the baseline observation used for delta calculation",
    )
    change_from_baseline: dict[str, float] | None = Field(
        default=None,
        description="Calculated delta (observation value - baseline value) for numeric metrics",
    )


class EnrollmentMonitoringTimeline(BaseModel):
    """Complete chronological timeline of monitoring observations for an enrollment."""

    enrollment_id: int
    project_id: int
    parcel_id: int
    farmer_id: int
    baseline_observations: dict[str, int] = Field(
        default_factory=dict,
        description="Map of observation type to active baseline observation ID",
    )
    timeline: list[TimelineObservationItem]
    total_observations: int
