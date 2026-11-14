"""Enrollment domain services, verification logic, and business rule enforcement."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.farmer import Farmer
from app.models.land_parcel import LandParcel
from app.models.project import Project
from app.schemas.enrollment import EnrollmentCreate, EnrollmentUpdate


class DuplicateActiveEnrollmentError(ValueError):
    """Exception raised when a parcel is already enrolled in an active project of the same type."""


class EnrollmentNotFoundError(ValueError):
    """Exception raised when an enrollment is not found."""


class EnrollmentValidationError(ValueError):
    """Exception raised when enrollment relationship or business constraints are violated."""


def _check_duplicate_active_enrollment(
    db: Session,
    parcel_id: int,
    project: Project,
    exclude_enrollment_id: int | None = None,
) -> None:
    """Verify that a parcel does not have another active enrollment of the same project type.

    Why: PROJECT_SPEC.md Rule 2 strictly prohibits double-counting carbon claims by preventing
    the same land parcel from being concurrently enrolled in two active projects of the same type.
    Inputs: db (Session), parcel_id (int), project (Project entity), exclude_enrollment_id (optional int)
    Outputs: None
    Raises: DuplicateActiveEnrollmentError if a conflicting active enrollment exists.
    """
    statement = (
        select(Enrollment)
        .join(Project, Enrollment.project_id == Project.id)
        .where(
            Enrollment.parcel_id == parcel_id,
            Enrollment.status == EnrollmentStatus.ACTIVE,
            Project.type == project.type,
        )
    )

    if exclude_enrollment_id is not None:
        statement = statement.where(Enrollment.id != exclude_enrollment_id)

    conflicting_enrollment = db.execute(statement).scalars().first()
    if conflicting_enrollment:
        raise DuplicateActiveEnrollmentError(
            f"Land parcel {parcel_id} already has an active enrollment (ID {conflicting_enrollment.id}) "
            f"in a project of type '{project.type.value}'."
        )


def create_enrollment(db: Session, enrollment_in: EnrollmentCreate) -> Enrollment:
    """Create a new project enrollment linking a parcel and farmer to a project.

    Why: Registers land parcels into MRV carbon crediting pipelines with baseline tracking.
    Enforces referential integrity and duplicate active enrollment constraints.
    Inputs: db (Session), enrollment_in (EnrollmentCreate schema)
    Outputs: Persisted Enrollment instance.
    Raises:
        EnrollmentValidationError: If farmer, project, or parcel do not exist, or parcel ownership mismatches.
        DuplicateActiveEnrollmentError: If parcel is already in an active enrollment of the same project type.
    """
    # 1. Validate Project existence
    project = db.get(Project, enrollment_in.project_id)
    if not project:
        raise EnrollmentValidationError(
            f"Project with ID {enrollment_in.project_id} does not exist."
        )

    # 2. Validate Farmer existence and active status
    farmer = db.get(Farmer, enrollment_in.farmer_id)
    if not farmer or farmer.is_deleted:
        raise EnrollmentValidationError(
            f"Farmer with ID {enrollment_in.farmer_id} does not exist or has been deleted."
        )

    # 3. Validate LandParcel existence
    parcel = db.get(LandParcel, enrollment_in.parcel_id)
    if not parcel:
        raise EnrollmentValidationError(
            f"Land parcel with ID {enrollment_in.parcel_id} does not exist."
        )

    # 4. Verify that the parcel belongs to the specified farmer
    if parcel.farmer_id != enrollment_in.farmer_id:
        raise EnrollmentValidationError(
            f"Land parcel {enrollment_in.parcel_id} belongs to farmer {parcel.farmer_id}, "
            f"not farmer {enrollment_in.farmer_id}."
        )

    # 5. Enforce Business Rule 2: No duplicate active enrollments of the same project type
    if enrollment_in.status == EnrollmentStatus.ACTIVE:
        _check_duplicate_active_enrollment(
            db=db,
            parcel_id=enrollment_in.parcel_id,
            project=project,
        )

    enrollment = Enrollment(
        project_id=enrollment_in.project_id,
        parcel_id=enrollment_in.parcel_id,
        farmer_id=enrollment_in.farmer_id,
        baseline_date=enrollment_in.baseline_date,
        status=enrollment_in.status,
        additionality_note=enrollment_in.additionality_note.strip()
        if enrollment_in.additionality_note
        else None,
    )
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    return enrollment


def get_enrollment_by_id(db: Session, enrollment_id: int) -> Enrollment | None:
    """Fetch an enrollment by primary key ID.

    Why: Enables retrieving enrollment details for observation logging and verification.
    Inputs: db (Session), enrollment_id (int)
    Outputs: Enrollment instance if found, None otherwise.
    """
    return db.get(Enrollment, enrollment_id)


def list_enrollments(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    project_id: int | None = None,
    parcel_id: int | None = None,
    farmer_id: int | None = None,
    status: EnrollmentStatus | None = None,
) -> tuple[list[Enrollment], int]:
    """Retrieve a paginated slice of enrollments with optional filtering.

    Why: Allows querying enrollments across projects, parcels, farmers, or lifecycle statuses.
    Inputs: db (Session), page (int), page_size (int), project_id, parcel_id, farmer_id, status
    Outputs: Tuple of (list of Enrollment objects, total integer count).
    """
    base_query = select(Enrollment)

    if project_id is not None:
        base_query = base_query.where(Enrollment.project_id == project_id)

    if parcel_id is not None:
        base_query = base_query.where(Enrollment.parcel_id == parcel_id)

    if farmer_id is not None:
        base_query = base_query.where(Enrollment.farmer_id == farmer_id)

    if status is not None:
        base_query = base_query.where(Enrollment.status == status)

    count_statement = select(func.count()).select_from(base_query.subquery())
    total = db.execute(count_statement).scalar_one() or 0

    offset = (page - 1) * page_size
    paged_query = (
        base_query.order_by(Enrollment.created_at.desc(), Enrollment.id.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = list(db.execute(paged_query).scalars().all())

    return items, total


def update_enrollment(
    db: Session,
    enrollment_id: int,
    enrollment_in: EnrollmentUpdate,
) -> Enrollment:
    """Update enrollment attributes including status and additionality notes.

    Why: Supports lifecycle progressions (e.g. pending -> active -> completed/terminated).
    Inputs: db (Session), enrollment_id (int), enrollment_in (EnrollmentUpdate schema)
    Outputs: Updated Enrollment instance.
    Raises:
        EnrollmentNotFoundError: If the enrollment is not found.
        DuplicateActiveEnrollmentError: If updated to ACTIVE and another active enrollment exists for the same project type.
    """
    enrollment = db.get(Enrollment, enrollment_id)
    if not enrollment:
        raise EnrollmentNotFoundError(f"Enrollment with ID {enrollment_id} not found.")

    update_data = enrollment_in.model_dump(exclude_unset=True)

    # If updating to ACTIVE status, ensure no duplicate active enrollment exists
    if "status" in update_data and update_data["status"] == EnrollmentStatus.ACTIVE:
        project = db.get(Project, enrollment.project_id)
        if project:
            _check_duplicate_active_enrollment(
                db=db,
                parcel_id=enrollment.parcel_id,
                project=project,
                exclude_enrollment_id=enrollment.id,
            )

    for field, value in update_data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(enrollment, field, value)

    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    return enrollment
