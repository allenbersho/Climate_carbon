"""Project management API routes."""

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import AdminUserDep, CurrentUserDep, SessionDep
from app.models.project import ProjectStatus, ProjectType
from app.schemas.project import (
    ProjectCreate,
    ProjectListResponse,
    ProjectRead,
    ProjectUpdate,
)
from app.services import project_service
from app.services.project_service import InvalidStatusTransitionError

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new carbon project",
    description="Administrative action. Initializes a new carbon project in DRAFT status.",
)
def create_project(
    project_in: ProjectCreate,
    db: SessionDep,
    _admin_user: AdminUserDep,
) -> ProjectRead:
    """Create a new project record."""
    return project_service.create_project(db, project_in)


@router.get(
    "/{project_id}",
    response_model=ProjectRead,
    summary="Get project by ID",
    description="Accessible by all authenticated roles (admin, field_officer, verifier).",
)
def get_project(
    project_id: int,
    db: SessionDep,
    _current_user: CurrentUserDep,
) -> ProjectRead:
    """Fetch project details by primary key ID."""
    project = project_service.get_project_by_id(db, project_id=project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with id {project_id} not found",
        )
    return project


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List projects with pagination and filters",
    description="Filter projects by status, carbon removal type, or name search.",
)
def list_projects(
    db: SessionDep,
    _current_user: CurrentUserDep,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status: ProjectStatus | None = Query(default=None, description="Filter by status (draft, active, closed)"),
    type: ProjectType | None = Query(default=None, description="Filter by type (afforestation, regen_ag, biochar)"),
    search: str | None = Query(default=None, description="Search project name substring"),
) -> ProjectListResponse:
    """List projects with pagination and filtering."""
    items, total = project_service.list_projects(
        db,
        page=page,
        page_size=page_size,
        status=status,
        type=type,
        search=search,
    )
    return ProjectListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/{project_id}",
    response_model=ProjectRead,
    summary="Update project details or advance status",
    description="Administrative action. Enforces state transitions: draft -> active -> closed only (no skipping back).",
)
def update_project(
    project_id: int,
    update_in: ProjectUpdate,
    db: SessionDep,
    _admin_user: AdminUserDep,
) -> ProjectRead:
    """Update project attributes and validate lifecycle transitions."""
    project = project_service.get_project_by_id(db, project_id=project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with id {project_id} not found",
        )

    try:
        updated_project = project_service.update_project(db, project=project, update_in=update_in)
    except InvalidStatusTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return updated_project
