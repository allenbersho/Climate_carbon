"""Carbon credit estimation API endpoints."""

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUserDep, SessionDep, require_roles
from app.models.user import UserRole
from app.schemas.carbon import (
    CarbonEstimateListResponse,
    CarbonEstimateRead,
    EstimateCreateRequest,
)
from app.services import carbon_service
from app.services.carbon_service import (
    EnrollmentNotFoundError,
    InsufficientObservationsError,
    MethodologyNotFoundError,
    UnsupportedProjectTypeError,
)

router = APIRouter(prefix="/carbon", tags=["Carbon Engine"])

# Permissions: Estimations can be triggered by Admins and Verifiers
CanRunEstimation = Annotated[
    CurrentUserDep,
    Depends(require_roles(UserRole.ADMIN, UserRole.VERIFIER)),
]


@router.post(
    "/estimate",
    response_model=CarbonEstimateRead,
    status_code=status.HTTP_201_CREATED,
    summary="Calculate carbon credits for an enrollment",
    description="Requires admin or verifier role. Excludes error-flagged observations and records an immutable inputs snapshot.",
)
def estimate_carbon_credits(
    estimate_in: EstimateCreateRequest,
    db: SessionDep,
    _current_user: CanRunEstimation,
) -> CarbonEstimateRead:
    """Run automated carbon estimation pipeline for an enrolled parcel."""
    try:
        estimate = carbon_service.create_carbon_estimate(
            db,
            enrollment_id=estimate_in.enrollment_id,
            methodology_id=estimate_in.methodology_id,
        )
        return estimate
    except EnrollmentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InsufficientObservationsError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except (MethodologyNotFoundError, UnsupportedProjectTypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/estimates/{enrollment_id}",
    response_model=CarbonEstimateListResponse,
    summary="Get calculation history for an enrollment",
    description="Accessible by all authenticated roles (admin, verifier, field_officer).",
)
def get_enrollment_estimates(
    enrollment_id: int,
    db: SessionDep,
    _current_user: CurrentUserDep,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
) -> CarbonEstimateListResponse:
    """Retrieve historical carbon estimates and inputs snapshots for an enrollment."""
    try:
        items, total = carbon_service.get_estimates_by_enrollment(
            db,
            enrollment_id=enrollment_id,
            page=page,
            page_size=page_size,
        )
        return CarbonEstimateListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )
    except EnrollmentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
