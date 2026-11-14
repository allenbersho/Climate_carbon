"""Pydantic schemas for Project entities."""

from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field

from app.models.project import ProjectStatus, ProjectType


class ProjectBase(BaseModel):
    """Shared baseline properties for a project."""

    name: str = Field(..., min_length=2, max_length=255, description="Project name")
    type: ProjectType = Field(..., description="Carbon removal project type (afforestation, regen_ag, biochar)")
    methodology_id: int | None = Field(default=None, description="Associated methodology ID")
    start_date: date | None = Field(default=None, description="Official project start date")


class ProjectCreate(ProjectBase):
    """Schema for initializing a new project (defaults to DRAFT status)."""

    status: ProjectStatus = Field(
        default=ProjectStatus.DRAFT,
        description="Initial status of the project (defaults to draft)",
    )


class ProjectUpdate(BaseModel):
    """Schema for updating project properties, including status transitions."""

    name: str | None = Field(default=None, min_length=2, max_length=255)
    type: ProjectType | None = None
    status: ProjectStatus | None = None
    methodology_id: int | None = None
    start_date: date | None = None


class ProjectRead(ProjectBase):
    """Public read representation of a Project."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: ProjectStatus
    created_at: datetime


class ProjectListResponse(BaseModel):
    """Paginated list response format per PROJECT_SPEC.md Section 8."""

    items: list[ProjectRead]
    total: int
    page: int
    page_size: int
