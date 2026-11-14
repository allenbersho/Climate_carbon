"""Land parcel management API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.deps import AdminUserDep, CurrentUserDep, SessionDep, require_roles
from app.models.user import UserRole
from app.schemas.land_parcel import (
    LandParcelCreate,
    LandParcelListResponse,
    LandParcelRead,
    LandParcelUpdate,
)
from app.services import parcel_service
from app.services.parcel_service import FarmerNotFoundError

router = APIRouter(prefix="/parcels", tags=["Land Parcels"])

# Permissions: Field officers and Admins can create and update parcels
CanManageParcels = Annotated[
    CurrentUserDep,
    Depends(require_roles(UserRole.ADMIN, UserRole.FIELD_OFFICER)),
]


@router.post(
    "",
    response_model=LandParcelRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new land parcel",
    description="Requires admin or field_officer role. Linked farmer must exist and be active.",
)
def create_parcel(
    parcel_in: LandParcelCreate,
    db: SessionDep,
    _current_user: CanManageParcels,
) -> LandParcelRead:
    """Create a new land parcel linked to a farmer."""
    try:
        return parcel_service.create_parcel(db, parcel_in)
    except FarmerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/{parcel_id}",
    response_model=LandParcelRead,
    summary="Get land parcel by ID",
    description="Accessible by all authenticated roles (admin, field_officer, verifier).",
)
def get_parcel(
    parcel_id: int,
    db: SessionDep,
    _current_user: CurrentUserDep,
) -> LandParcelRead:
    """Fetch parcel details by ID."""
    parcel = parcel_service.get_parcel_by_id(db, parcel_id=parcel_id)
    if not parcel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Land parcel with id {parcel_id} not found",
        )
    return parcel


@router.get(
    "",
    response_model=LandParcelListResponse,
    summary="List land parcels with pagination and filters",
    description="Filter parcels by owning farmer_id, crop type, or soil classification.",
)
def list_parcels(
    db: SessionDep,
    _current_user: CurrentUserDep,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    farmer_id: int | None = Query(default=None, description="Filter by owning farmer ID"),
    crop: str | None = Query(default=None, description="Filter by crop name"),
    soil_type: str | None = Query(default=None, description="Filter by soil classification"),
) -> LandParcelListResponse:
    """List parcels with pagination and filters."""
    items, total = parcel_service.list_parcels(
        db,
        page=page,
        page_size=page_size,
        farmer_id=farmer_id,
        crop=crop,
        soil_type=soil_type,
    )
    return LandParcelListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/{parcel_id}",
    response_model=LandParcelRead,
    summary="Update land parcel attributes",
    description="Requires admin or field_officer role.",
)
def update_parcel(
    parcel_id: int,
    update_in: LandParcelUpdate,
    db: SessionDep,
    _current_user: CanManageParcels,
) -> LandParcelRead:
    """Update parcel attributes."""
    parcel = parcel_service.get_parcel_by_id(db, parcel_id=parcel_id)
    if not parcel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Land parcel with id {parcel_id} not found",
        )
    return parcel_service.update_parcel(db, parcel=parcel, update_in=update_in)


@router.delete(
    "/{parcel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a land parcel",
    description="Administrative action. Removes a land parcel boundary.",
)
def delete_parcel(
    parcel_id: int,
    db: SessionDep,
    _admin_user: AdminUserDep,
) -> Response:
    """Delete a parcel record."""
    parcel = parcel_service.get_parcel_by_id(db, parcel_id=parcel_id)
    if not parcel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Land parcel with id {parcel_id} not found",
        )
    parcel_service.delete_parcel(db, parcel=parcel)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
