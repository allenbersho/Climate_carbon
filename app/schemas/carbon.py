"""Pydantic schemas for carbon estimation requests, responses, and audit records."""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from app.models.carbon_estimate import EstimateStatus


class EstimateCreateRequest(BaseModel):
    """Request payload for triggering an automated carbon estimate for an enrollment."""

    enrollment_id: int = Field(
        ...,
        description="ID of the enrollment to calculate carbon credits for",
    )
    methodology_id: int | None = Field(
        default=None,
        description="Optional methodology ID; if omitted, defaults to the active methodology matching project type",
    )


class CarbonEstimateRead(BaseModel):
    """Public read schema for a persisted carbon estimate record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    enrollment_id: int
    methodology_id: int
    methodology_version: str
    inputs_snapshot: dict[str, Any] = Field(
        ...,
        description="Audit snapshot of all observations and methodology parameters used in the calculation",
    )
    co2e_tonnes: float = Field(..., description="Gross greenhouse gas removals in tonnes CO2e")
    uncertainty_pct: float = Field(..., description="Deduction ratio for measurement variance (e.g. 0.10 for 10%)")
    buffer_pct: float = Field(..., description="Withholding ratio for permanence risk buffer (e.g. 0.15 for 15%)")
    net_credits: float = Field(..., description="Net issued credits in metric tonnes CO2e")
    status: EstimateStatus = Field(..., description="Lifecycle status (draft, verified, issued)")
    computed_at: datetime = Field(..., description="UTC timestamp when estimate was executed")


class CarbonEstimateListResponse(BaseModel):
    """Paginated list envelope for carbon estimates."""

    items: list[CarbonEstimateRead]
    total: int
    page: int
    page_size: int
