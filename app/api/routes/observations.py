"""Observation management API routes enforcing append-only semantics."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUserDep, SessionDep, require_roles
from app.models.observation import ObservationType
from app.models.user import UserRole
from app.schemas.observation import (
    ObservationCorrectionCreate,
    ObservationCreate,
    ObservationListResponse,
    ObservationRead,
)
from app.services import observation_service
from app.services.observation_service import (
    EnrollmentNotFoundError,
    FutureObservationDateError,
    InvalidObservationValuesError,
    ObservationAlreadySupersededError,
    ObservationNotFoundError,
)

router = APIRouter(prefix="/observations", tags=["Observations"])

# Permissions: Field officers and Admins can record and supersede observations
CanRecordObservations = Annotated[
    CurrentUserDep,
    Depends(require_roles(UserRole.ADMIN, UserRole.FIELD_OFFICER)),
]


@router.post(
    "",
    response_model=ObservationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record a new field observation",
    description="Requires admin or field_officer role. Values are strictly validated against observation type schema.",
)
def create_observation(
    observation_in: ObservationCreate,
    db: SessionDep,
    current_user: CanRecordObservations,
) -> ObservationRead:
    """Record a new monitoring observation."""
    try:
        return observation_service.create_observation(
            db,
            observation_in=observation_in,
            observer_id=current_user.id,
        )
    except EnrollmentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (FutureObservationDateError, InvalidObservationValuesError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.post(
    "/{observation_id}/supersede",
    response_model=ObservationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Supersede an existing observation (append-only correction)",
    description="Observations cannot be edited or deleted. Corrections create a new observation row and mark the old row as superseded.",
)
def supersede_observation(
    observation_id: int,
    correction_in: ObservationCorrectionCreate,
    db: SessionDep,
    current_user: CanRecordObservations,
) -> ObservationRead:
    """Record an append-only correction superseding a prior observation."""
    try:
        new_obs, _old_obs = observation_service.supersede_observation(
            db,
            old_observation_id=observation_id,
            correction_in=correction_in,
            observer_id=current_user.id,
        )
        return new_obs
    except ObservationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ObservationAlreadySupersededError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (FutureObservationDateError, InvalidObservationValuesError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get(
    "/{observation_id}",
    response_model=ObservationRead,
    summary="Get observation by ID",
    description="Accessible by all authenticated roles (admin, field_officer, verifier).",
)
def get_observation(
    observation_id: int,
    db: SessionDep,
    _current_user: CurrentUserDep,
) -> ObservationRead:
    """Fetch observation details and superseding lineage by primary key."""
    observation = observation_service.get_observation_by_id(db, observation_id=observation_id)
    if not observation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Observation with id {observation_id} not found",
        )
    return observation


@router.get(
    "",
    response_model=ObservationListResponse,
    summary="List observations with pagination and filters",
    description="Filter by enrollment, type, baseline status, date range, or active_only (to exclude superseded observations).",
)
def list_observations(
    db: SessionDep,
    _current_user: CurrentUserDep,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    enrollment_id: int | None = Query(default=None, description="Filter by enrollment ID"),
    observation_type: ObservationType | None = Query(
        default=None,
        alias="type",
        description="Filter by observation type (soil, tree_count, biomass)",
    ),
    is_baseline: bool | None = Query(default=None, description="Filter by baseline flag"),
    active_only: bool = Query(
        default=False,
        description="If true, returns only active (non-superseded) observations",
    ),
    from_date: datetime | None = Query(default=None, description="Start timestamp (ISO-8601)"),
    to_date: datetime | None = Query(default=None, description="End timestamp (ISO-8601)"),
) -> ObservationListResponse:
    """List observations with pagination and filters."""
    items, total = observation_service.list_observations(
        db,
        page=page,
        page_size=page_size,
        enrollment_id=enrollment_id,
        observation_type=observation_type,
        is_baseline=is_baseline,
        active_only=active_only,
        from_date=from_date,
        to_date=to_date,
    )
    return ObservationListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
