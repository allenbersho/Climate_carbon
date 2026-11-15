"""Methodology API routes for inspecting and registering calculation parameters."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUserDep, SessionDep, require_roles
from app.models.user import UserRole
from app.schemas.methodology import (
    MethodologyCreate,
    MethodologyListResponse,
    MethodologyRead,
    MethodologyUpdate,
)
from app.services import methodology_service
from app.services.methodology_service import (
    MethodologyAlreadyExistsError,
    MethodologyNotFoundError,
)

router = APIRouter(prefix="/methodologies", tags=["Methodologies"])

# Permissions: Only Admin can create or update methodologies
AdminUserDep = Annotated[CurrentUserDep, Depends(require_roles(UserRole.ADMIN))]


@router.get(
    "",
    response_model=MethodologyListResponse,
    summary="List methodologies with pagination and active filter",
    description="Accessible by all authenticated roles (admin, field_officer, verifier).",
)
def list_methodologies(
    db: SessionDep,
    _current_user: CurrentUserDep,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    is_active: bool | None = Query(default=None, description="Filter by active status"),
) -> MethodologyListResponse:
    """Retrieve a paginated list of methodology versions."""
    items, total = methodology_service.list_methodologies(
        db,
        page=page,
        page_size=page_size,
        is_active=is_active,
    )
    return MethodologyListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{methodology_id}",
    response_model=MethodologyRead,
    summary="Get methodology by ID",
    description="Accessible by all authenticated roles (admin, field_officer, verifier).",
)
def get_methodology(
    methodology_id: int,
    db: SessionDep,
    _current_user: CurrentUserDep,
) -> MethodologyRead:
    """Fetch methodology details and calculation parameters by ID."""
    methodology = methodology_service.get_methodology_by_id(
        db, methodology_id=methodology_id
    )
    if not methodology:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Methodology with id {methodology_id} not found",
        )
    return methodology


@router.post(
    "",
    response_model=MethodologyRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new methodology version",
    description="Requires admin role. Unique on (name, version).",
)
def create_methodology(
    methodology_in: MethodologyCreate,
    db: SessionDep,
    _admin: AdminUserDep,
) -> MethodologyRead:
    """Register a new methodology with calibrated parameters."""
    try:
        return methodology_service.create_methodology(db, methodology_in=methodology_in)
    except MethodologyAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.patch(
    "/{methodology_id}",
    response_model=MethodologyRead,
    summary="Update methodology parameters or status",
    description="Requires admin role.",
)
def update_methodology(
    methodology_id: int,
    update_in: MethodologyUpdate,
    db: SessionDep,
    _admin: AdminUserDep,
) -> MethodologyRead:
    """Update methodology parameters or active status."""
    try:
        return methodology_service.update_methodology(
            db,
            methodology_id=methodology_id,
            update_in=update_in,
        )
    except MethodologyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
