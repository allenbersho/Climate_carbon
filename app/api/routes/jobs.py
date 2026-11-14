"""Job management API routes for checking background task progress and status."""

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUserDep, SessionDep
from app.models.job import JobStatus
from app.schemas.job import JobListResponse, JobRead
from app.services import job_service

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get(
    "",
    response_model=JobListResponse,
    summary="List background jobs",
    description="Retrieve a paginated list of background tasks with optional status filtering.",
)
def list_jobs(
    db: SessionDep,
    _current_user: CurrentUserDep,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status_filter: JobStatus | None = Query(
        default=None,
        alias="status",
        description="Filter jobs by status (pending, processing, completed, failed)",
    ),
) -> JobListResponse:
    """Fetch paginated background jobs."""
    items, total = job_service.list_jobs(
        db,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
    )
    return JobListResponse(
        items=[JobRead.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{job_id}",
    response_model=JobRead,
    summary="Get job status and result",
    description="Retrieve the current status, execution timestamps, and results or failure reasons for a background job.",
)
def get_job_status(
    job_id: int,
    db: SessionDep,
    _current_user: CurrentUserDep,
) -> JobRead:
    """Poll the status and output of an asynchronous background job."""
    job = job_service.get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID {job_id} not found.",
        )
    return JobRead.model_validate(job)
