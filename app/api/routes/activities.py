"""Activity management API routes."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUserDep, SessionDep, require_roles
from app.models.activity import ActivityType
from app.models.user import UserRole
from app.schemas.activity import (
    ActivityCreate,
    ActivityListResponse,
    ActivityRead,
    ActivityUpdate,
)
from app.services import activity_service
from app.services.activity_service import (
    ActivityNotFoundError,
    EnrollmentNotFoundError,
    FutureActivityDateError,
)

router = APIRouter(prefix="/activities", tags=["Activities"])

# Permissions: Admins and Field Officers can record and update management activities
CanManageActivities = Annotated[
    CurrentUserDep,
    Depends(require_roles(UserRole.ADMIN, UserRole.FIELD_OFFICER)),
]


@router.post(
    "",
    response_model=ActivityRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record a new field management activity",
    description="Requires admin or field_officer role. Activity dates in the future are rejected (422).",
)
def create_activity(
    activity_in: ActivityCreate,
    db: SessionDep,
    _current_user: CanManageActivities,
) -> ActivityRead:
    """Record an agricultural or carbon removal management activity."""
    try:
        return activity_service.create_activity(db, activity_in)
    except FutureActivityDateError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except EnrollmentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/{activity_id}",
    response_model=ActivityRead,
    summary="Get activity by ID",
    description="Accessible by all authenticated roles (admin, field_officer, verifier).",
)
def get_activity(
    activity_id: int,
    db: SessionDep,
    _current_user: CurrentUserDep,
) -> ActivityRead:
    """Fetch activity details by primary key."""
    activity = activity_service.get_activity_by_id(db, activity_id=activity_id)
    if not activity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Activity with id {activity_id} not found",
        )
    return activity


@router.get(
    "",
    response_model=ActivityListResponse,
    summary="List activities with pagination, enrollment filter, and date-range filters",
    description="Filter activities by enrollment_id, activity type, or activity_date range (from_date / to_date).",
)
def list_activities(
    db: SessionDep,
    _current_user: CurrentUserDep,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    enrollment_id: int | None = Query(default=None, description="Filter by enrollment ID"),
    activity_type: ActivityType | None = Query(
        default=None,
        alias="type",
        description="Filter by activity type (planting, cover_cropping, mulching, composting)",
    ),
    from_date: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    to_date: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
) -> ActivityListResponse:
    """List activities with pagination and filtering."""
    items, total = activity_service.list_activities(
        db,
        page=page,
        page_size=page_size,
        enrollment_id=enrollment_id,
        activity_type=activity_type,
        from_date=from_date,
        to_date=to_date,
    )
    return ActivityListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/{activity_id}",
    response_model=ActivityRead,
    summary="Update activity details",
    description="Requires admin or field_officer role. Reject future dates (422).",
)
def update_activity(
    activity_id: int,
    update_in: ActivityUpdate,
    db: SessionDep,
    _current_user: CanManageActivities,
) -> ActivityRead:
    """Update activity parameters."""
    try:
        return activity_service.update_activity(
            db,
            activity_id=activity_id,
            update_in=update_in,
        )
    except ActivityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except FutureActivityDateError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
