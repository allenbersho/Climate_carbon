"""Enrollment management API routes."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUserDep, SessionDep, require_roles
from app.models.enrollment import EnrollmentStatus
from app.models.user import UserRole
from app.schemas.activity import ActivityRead
from app.schemas.enrollment import (
    EnrollmentCreate,
    EnrollmentListResponse,
    EnrollmentRead,
    EnrollmentUpdate,
)
from app.services import activity_service, enrollment_service
from app.services.activity_service import EnrollmentNotFoundError as ActivityEnrollmentNotFoundError
from app.services.enrollment_service import (
    DuplicateActiveEnrollmentError,
    EnrollmentNotFoundError,
    EnrollmentValidationError,
)

router = APIRouter(prefix="/enrollments", tags=["Enrollments"])

# Permissions: Admins and Field Officers can create and update enrollments
CanManageEnrollments = Annotated[
    CurrentUserDep,
    Depends(require_roles(UserRole.ADMIN, UserRole.FIELD_OFFICER)),
]


@router.post(
    "",
    response_model=EnrollmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Enroll a parcel into a project",
    description="Registers a parcel into a project. A parcel cannot have two active enrollments of the same project type (returns 409).",
)
def create_enrollment(
    enrollment_in: EnrollmentCreate,
    db: SessionDep,
    _current_user: CanManageEnrollments,
) -> EnrollmentRead:
    """Enroll a land parcel into a carbon project."""
    try:
        return enrollment_service.create_enrollment(db, enrollment_in)
    except DuplicateActiveEnrollmentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except EnrollmentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get(
    "/{enrollment_id}",
    response_model=EnrollmentRead,
    summary="Get enrollment by ID",
    description="Accessible by all authenticated roles (admin, field_officer, verifier).",
)
def get_enrollment(
    enrollment_id: int,
    db: SessionDep,
    _current_user: CurrentUserDep,
) -> EnrollmentRead:
    """Fetch enrollment details by primary key."""
    enrollment = enrollment_service.get_enrollment_by_id(db, enrollment_id=enrollment_id)
    if not enrollment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Enrollment with id {enrollment_id} not found",
        )
    return enrollment


@router.get(
    "",
    response_model=EnrollmentListResponse,
    summary="List enrollments with pagination and filters",
    description="Filter enrollments by project, parcel, farmer, or lifecycle status.",
)
def list_enrollments(
    db: SessionDep,
    _current_user: CurrentUserDep,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    project_id: int | None = Query(default=None, description="Filter by project ID"),
    parcel_id: int | None = Query(default=None, description="Filter by parcel ID"),
    farmer_id: int | None = Query(default=None, description="Filter by farmer ID"),
    status_filter: EnrollmentStatus | None = Query(
        default=None,
        alias="status",
        description="Filter by enrollment status",
    ),
) -> EnrollmentListResponse:
    """List enrollments with pagination and filters."""
    items, total = enrollment_service.list_enrollments(
        db,
        page=page,
        page_size=page_size,
        project_id=project_id,
        parcel_id=parcel_id,
        farmer_id=farmer_id,
        status=status_filter,
    )
    return EnrollmentListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/{enrollment_id}",
    response_model=EnrollmentRead,
    summary="Update an enrollment",
    description="Update lifecycle status or baseline notes. Requires admin or field_officer role.",
)
def update_enrollment(
    enrollment_id: int,
    update_in: EnrollmentUpdate,
    db: SessionDep,
    _current_user: CanManageEnrollments,
) -> EnrollmentRead:
    """Update enrollment attributes."""
    try:
        return enrollment_service.update_enrollment(
            db,
            enrollment_id=enrollment_id,
            enrollment_in=update_in,
        )
    except EnrollmentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except DuplicateActiveEnrollmentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/{enrollment_id}/activities",
    response_model=list[ActivityRead],
    summary="Get all activities for an enrollment with date-range filters",
    description="Accessible by all authenticated roles. Filter by optional from_date and to_date.",
)
def get_enrollment_activities(
    enrollment_id: int,
    db: SessionDep,
    _current_user: CurrentUserDep,
    from_date: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    to_date: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
) -> list[ActivityRead]:
    """Retrieve all activities recorded for a specific enrollment."""
    try:
        return activity_service.get_activities_by_enrollment(
            db,
            enrollment_id=enrollment_id,
            from_date=from_date,
            to_date=to_date,
        )
    except ActivityEnrollmentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
