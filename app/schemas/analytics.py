"""Pydantic schemas for analytics summaries, project reporting, and district aggregations."""

from pydantic import BaseModel, ConfigDict, Field


class DistrictBreakdown(BaseModel):
    """Aggregated metrics for a single administrative district."""

    model_config = ConfigDict(from_attributes=True)

    district: str = Field(..., description="District name")
    state: str = Field(..., description="State name")
    farmers_count: int = Field(..., description="Number of distinct enrolled farmers in this district")
    total_acres: float = Field(..., description="Total enrolled acreage in this district")
    total_co2e: float = Field(..., description="Total gross CO2e sequestered in tonnes")
    net_credits: float = Field(..., description="Total net verified carbon credits in tonnes CO2e")


class AnalyticsSummaryResponse(BaseModel):
    """Portfolio-wide or filtered analytics summary."""

    model_config = ConfigDict(from_attributes=True)

    total_farmers: int = Field(..., description="Total distinct active farmers enrolled")
    total_acres: float = Field(..., description="Total enrolled land area in acres")
    total_co2e: float = Field(..., description="Total gross CO2e sequestered in metric tonnes")
    total_net_credits: float = Field(..., description="Total net carbon credits issued in metric tonnes CO2e")
    by_district: list[DistrictBreakdown] = Field(
        default_factory=list,
        description="District-level geographic aggregation breakdown",
    )


class ProjectAnalyticsResponse(AnalyticsSummaryResponse):
    """Project-specific analytics summary with project metadata."""

    project_id: int = Field(..., description="Project ID")
    project_name: str = Field(..., description="Project name")
    project_type: str = Field(..., description="Project type (afforestation, regen_ag, biochar)")
    project_status: str = Field(..., description="Project lifecycle status (draft, active, closed)")
