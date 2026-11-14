"""Land parcel domain services and business logic."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.farmer import Farmer
from app.models.land_parcel import LandParcel
from app.schemas.land_parcel import LandParcelCreate, LandParcelUpdate
from app.services import farmer_service


class FarmerNotFoundError(ValueError):
    """Exception raised when an associated farmer is not found or is soft-deleted."""


def create_parcel(db: Session, parcel_in: LandParcelCreate) -> LandParcel:
    """Create a new land parcel linked to an active farmer.

    Why: Validates that the referenced farmer exists and is active before creating parcel bounds.
    Inputs: db (SQLAlchemy session), parcel_in (validated LandParcelCreate schema)
    Outputs: Newly persisted LandParcel model instance.
    Raises: FarmerNotFoundError if the farmer_id is invalid or soft-deleted.
    """
    farmer = farmer_service.get_farmer_by_id(db, farmer_id=parcel_in.farmer_id)
    if not farmer:
        raise FarmerNotFoundError(
            f"Cannot create land parcel: Farmer with ID {parcel_in.farmer_id} does not exist or has been deleted."
        )

    parcel = LandParcel(
        farmer_id=parcel_in.farmer_id,
        area_acres=parcel_in.area_acres,
        soil_type=parcel_in.soil_type.strip() if parcel_in.soil_type else None,
        crop=parcel_in.crop.strip() if parcel_in.crop else None,
    )
    db.add(parcel)
    db.commit()
    db.refresh(parcel)
    return parcel


def get_parcel_by_id(db: Session, parcel_id: int) -> LandParcel | None:
    """Fetch a single land parcel by primary key ID.

    Why: Used for parcel inspection and enrollment linking.
    Inputs: db (Session), parcel_id (int)
    Outputs: LandParcel instance if found, None otherwise.
    """
    return db.get(LandParcel, parcel_id)


def list_parcels(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    farmer_id: int | None = None,
    crop: str | None = None,
    soil_type: str | None = None,
) -> tuple[list[LandParcel], int]:
    """Retrieve a paginated slice of land parcels with optional filters.

    Why: Supports geographic and crop-type queries across the land inventory.
    Inputs: db (Session), page (int), page_size (int), farmer_id (int), crop (str), soil_type (str)
    Outputs: Tuple of (list of LandParcel objects, total integer count).
    """
    base_query = select(LandParcel)

    if farmer_id is not None:
        base_query = base_query.where(LandParcel.farmer_id == farmer_id)

    if crop and crop.strip():
        base_query = base_query.where(func.lower(LandParcel.crop) == crop.strip().lower())

    if soil_type and soil_type.strip():
        base_query = base_query.where(func.lower(LandParcel.soil_type) == soil_type.strip().lower())

    count_statement = select(func.count()).select_from(base_query.subquery())
    total = db.execute(count_statement).scalar_one() or 0

    offset = (page - 1) * page_size
    paged_query = (
        base_query.order_by(LandParcel.created_at.desc(), LandParcel.id.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = list(db.execute(paged_query).scalars().all())

    return items, total


def get_parcels_by_farmer(db: Session, farmer_id: int) -> list[LandParcel]:
    """Fetch all land parcels belonging to an active farmer.

    Why: Powers the GET /api/v1/farmers/{id}/parcels nested route.
    Inputs: db (Session), farmer_id (int)
    Outputs: List of LandParcel instances.
    Raises: FarmerNotFoundError if the farmer is not found or is soft-deleted.
    """
    farmer = farmer_service.get_farmer_by_id(db, farmer_id=farmer_id)
    if not farmer:
        raise FarmerNotFoundError(f"Farmer with id {farmer_id} not found")

    statement = (
        select(LandParcel)
        .where(LandParcel.farmer_id == farmer_id)
        .order_by(LandParcel.id.asc())
    )
    return list(db.execute(statement).scalars().all())


def update_parcel(db: Session, parcel: LandParcel, update_in: LandParcelUpdate) -> LandParcel:
    """Apply partial updates to parcel attributes.

    Why: Allows updating acreage, soil classification, or current crop.
    Inputs: db (Session), parcel (existing LandParcel), update_in (LandParcelUpdate schema)
    Outputs: Updated LandParcel model instance.
    """
    update_data = update_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(parcel, field, value)

    db.add(parcel)
    db.commit()
    db.refresh(parcel)
    return parcel


def delete_parcel(db: Session, parcel: LandParcel) -> None:
    """Delete a land parcel record.

    Why: Allows administrators to remove mistakenly created parcel boundaries.
    Inputs: db (Session), parcel (LandParcel instance to remove)
    """
    db.delete(parcel)
    db.commit()
