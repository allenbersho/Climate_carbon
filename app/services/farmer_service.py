"""Farmer domain services and business logic."""

import csv
import io
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.farmer import Farmer
from app.models.user import User
from app.schemas.farmer import (
    FarmerBulkImportResult,
    FarmerCreate,
    FarmerImportRowError,
    FarmerUpdate,
)
from app.services.audit_service import record_audit_event


def create_farmer(
    db: Session,
    farmer_in: FarmerCreate,
    user: User | None = None,
) -> Farmer:
    """Create a new farmer record with verified consent.

    Why: Enforces that every enrolled landholder has formal consent captured on creation.
    Inputs: db (SQLAlchemy session), farmer_in (validated FarmerCreate schema), user (optional acting User)
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
    db.flush()
    record_audit_event(
        db,
        user=user,
        action="CREATE",
        entity_type="farmer",
        entity_id=farmer.id,
        before_state=None,
        after_state={
            "name": farmer.name,
            "district": farmer.district,
            "state": farmer.state,
            "consent_given": farmer.consent_given,
        },
        commit=False,
    )
    db.commit()
    db.refresh(farmer)
    return farmer


def get_farmer_by_id(
    db: Session, farmer_id: int, include_deleted: bool = False
) -> Farmer | None:
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
        base_query = base_query.where(
            func.lower(Farmer.district) == district.strip().lower()
        )

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


def update_farmer(
    db: Session,
    farmer: Farmer,
    update_in: FarmerUpdate,
    user: User | None = None,
) -> Farmer:
    """Apply partial updates to an existing farmer record.

    Why: Allows updating contact info, location, or consent status without altering ID or history.
    Inputs: db (Session), farmer (active Farmer instance), update_in (FarmerUpdate schema), user (acting User)
    Outputs: Updated Farmer model instance.
    """
    before_state = {
        "name": farmer.name,
        "phone": farmer.phone,
        "village": farmer.village,
        "district": farmer.district,
        "state": farmer.state,
        "consent_given": farmer.consent_given,
    }

    update_data = update_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(farmer, field, value)

    after_state = {
        "name": farmer.name,
        "phone": farmer.phone,
        "village": farmer.village,
        "district": farmer.district,
        "state": farmer.state,
        "consent_given": farmer.consent_given,
    }

    record_audit_event(
        db,
        user=user,
        action="UPDATE",
        entity_type="farmer",
        entity_id=farmer.id,
        before_state=before_state,
        after_state=after_state,
        commit=False,
    )

    db.add(farmer)
    db.commit()
    db.refresh(farmer)
    return farmer


def soft_delete_farmer(
    db: Session,
    farmer: Farmer,
    user: User | None = None,
) -> Farmer:
    """Mark a farmer record as soft-deleted without purging historical database rows.

    Why: Compliance with PROJECT_SPEC.md business rule #6: Farmers cannot be hard-deleted.
         Preserves audit trails and historical carbon baseline links.
    Inputs: db (Session), farmer (active Farmer instance), user (acting User)
    Outputs: Soft-deleted Farmer instance with is_deleted=True.
    """
    before_state = {"is_deleted": farmer.is_deleted}
    farmer.is_deleted = True
    after_state = {"is_deleted": True}

    record_audit_event(
        db,
        user=user,
        action="SOFT_DELETE",
        entity_type="farmer",
        entity_id=farmer.id,
        before_state=before_state,
        after_state=after_state,
        commit=False,
    )

    db.add(farmer)
    db.commit()
    db.refresh(farmer)
    return farmer


def _parse_boolean_consent(value: Any) -> bool:
    """Parse various truthy/falsy string representations into a boolean."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    return s in {"true", "1", "yes", "y", "t"}


def bulk_import_farmers_from_csv(
    db: Session,
    file_content: bytes | str,
) -> FarmerBulkImportResult:
    """Import farmers from a CSV file, validating row by row.

    Why: Task 8.1 requires bulk uploading farmer records where bad rows do not
    halt the batch, returning an error diagnostic report for rejected rows.
    Inputs: db (SQLAlchemy session), file_content (raw CSV bytes or decoded text)
    Outputs: FarmerBulkImportResult summarizing total, imported, and failed rows.
    """
    if isinstance(file_content, bytes):
        try:
            text = file_content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = file_content.decode("latin-1")
    else:
        text = file_content

    if not text.strip():
        return FarmerBulkImportResult(
            total_rows=0, imported_count=0, failed_count=0, errors=[]
        )

    stream = io.StringIO(text)
    reader = csv.reader(stream)

    try:
        raw_header = next(reader)
    except StopIteration:
        return FarmerBulkImportResult(
            total_rows=0, imported_count=0, failed_count=0, errors=[]
        )

    # Normalize header column names
    header_map: dict[int, str] = {}
    for idx, col in enumerate(raw_header):
        cleaned = col.strip().lower().replace(" ", "_")
        # Map common aliases
        if cleaned in {"consent", "farmer_consent", "is_consent_given"}:
            cleaned = "consent_given"
        elif cleaned in {"farmer_name", "full_name"}:
            cleaned = "name"
        elif cleaned in {"mobile", "phone_number", "contact"}:
            cleaned = "phone"
        header_map[idx] = cleaned

    valid_farmers: list[Farmer] = []
    errors: list[FarmerImportRowError] = []
    total_data_rows = 0

    # Start enumerating data rows at line 2 (line 1 is the header)
    for row_idx, row in enumerate(reader, start=2):
        # Skip completely blank lines
        if not row or not any(cell.strip() for cell in row):
            continue

        total_data_rows += 1

        # Build raw row dictionary
        raw_dict: dict[str, str | None] = {}
        for col_idx, col_name in header_map.items():
            if col_idx < len(row):
                raw_dict[col_name] = row[col_idx]
            else:
                raw_dict[col_name] = None

        # Clean fields
        name_val = raw_dict.get("name")
        phone_val = raw_dict.get("phone")
        village_val = raw_dict.get("village")
        district_val = raw_dict.get("district")
        state_val = raw_dict.get("state")
        consent_raw = raw_dict.get("consent_given")

        cleaned_payload = {
            "name": name_val.strip() if name_val else "",
            "phone": phone_val.strip() if phone_val and phone_val.strip() else None,
            "village": village_val.strip()
            if village_val and village_val.strip()
            else None,
            "district": district_val.strip()
            if district_val and district_val.strip()
            else None,
            "state": state_val.strip() if state_val and state_val.strip() else None,
            "consent_given": _parse_boolean_consent(consent_raw),
        }

        try:
            validated = FarmerCreate(**cleaned_payload)
            farmer_model = Farmer(
                name=validated.name,
                phone=validated.phone,
                village=validated.village,
                district=validated.district,
                state=validated.state,
                consent_given=validated.consent_given,
                is_deleted=False,
            )
            valid_farmers.append(farmer_model)
        except ValidationError as exc:
            reasons = [f"{err['loc'][-1]}: {err['msg']}" for err in exc.errors()]
            errors.append(
                FarmerImportRowError(
                    row_number=row_idx,
                    data=raw_dict,
                    reason="; ".join(reasons),
                )
            )

    # Persist all valid farmers in a single transaction
    if valid_farmers:
        db.add_all(valid_farmers)
        db.commit()

    return FarmerBulkImportResult(
        total_rows=total_data_rows,
        imported_count=len(valid_farmers),
        failed_count=len(errors),
        errors=errors,
    )
