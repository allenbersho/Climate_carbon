"""Farmer domain services and business logic."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.farmer import Farmer
from app.schemas.farmer import FarmerCreate, FarmerUpdate


def create_farmer(db: Session, farmer_in: FarmerCreate) -> Farmer:
    """Create a new farmer record with verified consent.

    Why: Enforces that every enrolled landholder has formal consent captured on creation.
    Inputs: db (SQLAlchemy session), farmer_in (validated FarmerCreate schema)
    Outputs: Newly persisted Farmer model instance.
    """
    farmer = Farmer(
        name=farmer_in.name.strip(),
        phone=farmer_in.phone.strip() if farmer_in.phone else None,
        village=farmer_in.village.strip() if farmer_in.village else None,
        district=farmer_in.district.strip() if farmer_in.district else None,
        state=farmer_in.state.strip() if farmer_in.state else None,
        consent_given=farmer_in.consent_given,
        is_deleted=False,
    )
    db.add(farmer)
    db.commit()
    db.refresh(farmer)
    return farmer


def get_farmer_by_id(db: Session, farmer_id: int, include_deleted: bool = False) -> Farmer | None:
    """Fetch a single farmer by ID, filtering out soft-deleted records by default.

    Why: Standard lookups must not expose deactivated/archived farmers unless requested.
    Inputs: db (SQLAlchemy session), farmer_id (int), include_deleted (bool)
    Outputs: Farmer instance if found and active, None otherwise.
    """
    statement = select(Farmer).where(Farmer.id == farmer_id)
    if not include_deleted:
        statement = statement.where(Farmer.is_deleted == False)  # noqa: E712
    return db.execute(statement).scalar_one_or_none()


def list_farmers(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    district: str | None = None,
    state: str | None = None,
    search: str | None = None,
) -> tuple[list[Farmer], int]:
    """Retrieve a paginated slice of active farmers with optional filtering and name search.

    Why: Prevents memory exhaustion on large datasets while supporting administrative lookup.
    Inputs: db (Session), page (1-indexed int), page_size (int), district (str), state (str), search (str)
    Outputs: Tuple of (list of Farmer objects, total integer count matching filters).
    """
    base_query = select(Farmer).where(Farmer.is_deleted == False)  # noqa: E712

    # Filter by exact district (case-insensitive)
    if district and district.strip():
        base_query = base_query.where(func.lower(Farmer.district) == district.strip().lower())

    # Filter by exact state (case-insensitive)
    if state and state.strip():
        base_query = base_query.where(func.lower(Farmer.state) == state.strip().lower())

    # Search name by substring (case-insensitive)
    if search and search.strip():
        base_query = base_query.where(Farmer.name.ilike(f"%{search.strip()}%"))

    # Execute total count query
    count_statement = select(func.count()).select_from(base_query.subquery())
    total = db.execute(count_statement).scalar_one() or 0

    # Paginate results
    offset = (page - 1) * page_size
    paged_query = (
        base_query.order_by(Farmer.created_at.desc(), Farmer.id.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = list(db.execute(paged_query).scalars().all())

    return items, total


def update_farmer(db: Session, farmer: Farmer, update_in: FarmerUpdate) -> Farmer:
    """Apply partial updates to an existing farmer record.

    Why: Allows updating contact info, location, or consent status without altering ID or history.
    Inputs: db (Session), farmer (active Farmer instance), update_in (FarmerUpdate schema)
    Outputs: Updated Farmer model instance.
    """
    update_data = update_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(farmer, field, value)

    db.add(farmer)
    db.commit()
    db.refresh(farmer)
    return farmer


def soft_delete_farmer(db: Session, farmer: Farmer) -> Farmer:
    """Mark a farmer record as soft-deleted without purging historical database rows.

    Why: Compliance with PROJECT_SPEC.md business rule #6: Farmers cannot be hard-deleted.
         Preserves audit trails and historical carbon baseline links.
    Inputs: db (Session), farmer (active Farmer instance)
    Outputs: Soft-deleted Farmer instance with is_deleted=True.
    """
    farmer.is_deleted = True
    db.add(farmer)
    db.commit()
    db.refresh(farmer)
    return farmer
