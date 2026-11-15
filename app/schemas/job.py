"""Pydantic schemas for asynchronous Job entities."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.job import JobStatus


class JobBase(BaseModel):
    """Shared baseline attributes for a job."""

    job_type: str = Field(
        ...,
        description="Classification of the asynchronous task (e.g. farmer_bulk_import)",
    )
    payload: dict[str, Any] | None = Field(
        default=None, description="Input parameters and metadata stored with the job"
    )


class JobRead(JobBase):
    """Public read representation of a background job."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Unique job identifier")
    status: JobStatus = Field(
        ...,
        description="Current lifecycle state (pending, processing, completed, failed)",
    )
    result: dict[str, Any] | None = Field(
        default=None, description="Execution outcome upon completion"
    )
    error_message: str | None = Field(
        default=None, description="Error details if the job failed"
    )
    created_at: datetime = Field(
        ..., description="UTC timestamp when the job was queued"
    )
    started_at: datetime | None = Field(
        default=None, description="UTC timestamp when execution began"
    )
    completed_at: datetime | None = Field(
        default=None, description="UTC timestamp when execution finished"
    )


class JobListResponse(BaseModel):
    """Paginated list response format per PROJECT_SPEC.md Section 8."""

    items: list[JobRead]
    total: int
    page: int
    page_size: int
