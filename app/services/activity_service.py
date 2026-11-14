"""Activity domain services, date validation, and business logic."""

from datetime import date
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.activity import Activity, ActivityType
from app.models.enrollment import Enrollment
from app.schemas.activity import ActivityCreate, ActivityUpdate


class FutureActivityDateError(ValueError):
    """Exception raised when an activity date is in the future."""


class EnrollmentNotFoundError(ValueError):
    """Exception raised when an associated enrollment does not exist."""


class ActivityNotFoundError(ValueError):
    """Exception raised when an activity cannot be found."""


def create_activity(db: Session, activity_in: ActivityCreate) -> Activity:
    """Record a new agricultural or carbon removal management activity.

    Why: Tracks chronological interventions (planting, cover cropping, mulching, composting)
    required for MRV additionality verification and carbon stock estimation.
    Inputs: db (Session), activity_in (ActivityCreate schema)
    Outputs: Newly persisted Activity model instance.
    Raises:
        FutureActivityDateError: If activity_date is greater than today's calendar date.
        EnrollmentNotFoundError: If the referenced enrollment_id does not exist.
    """
    # 1. Enforce business rule: reject future dates
    if activity_in.activity_date > date.today():
        raise FutureActivityDateError(
            f"Cannot record activity: Date '{activity_in.activity_date}' is in the future."
        )

    # 2. Verify parent enrollment existence
    enrollment = db.get(Enrollment, activity_in.enrollment_id)
    if not enrollment:
        raise EnrollmentNotFoundError(
            f"Cannot record activity: Enrollment with ID {activity_in.enrollment_id} does not exist."
        )

    activity = Activity(
        enrollment_id=activity_in.enrollment_id,
        type=activity_in.type,
        activity_date=activity_in.activity_date,
        details=activity_in.details,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


def get_activity_by_id(db: Session, activity_id: int) -> Activity | None:
    """Fetch an activity record by primary key ID.

    Why: Allows inspecting specific management activity parameters and timestamps.
    Inputs: db (Session), activity_id (int)
    Outputs: Activity instance if found, None otherwise.
    """
    return db.get(Activity, activity_id)


def list_activities(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    enrollment_id: int | None = None,
    activity_type: ActivityType | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> tuple[list[Activity], int]:
    """Retrieve a paginated slice of activities with optional enrollment, type, and date-range filters.

    Why: Supports auditor queries and chronological analysis of field practices over seasons.
    Inputs: db (Session), page, page_size, enrollment_id, activity_type, from_date, to_date
    Outputs: Tuple of (list of Activity objects, total integer count).
    """
    base_query = select(Activity)

    if enrollment_id is not None:
        base_query = base_query.where(Activity.enrollment_id == enrollment_id)

    if activity_type is not None:
        base_query = base_query.where(Activity.type == activity_type)

    if from_date is not None:
        base_query = base_query.where(Activity.activity_date >= from_date)

    if to_date is not None:
        base_query = base_query.where(Activity.activity_date <= to_date)

    count_statement = select(func.count()).select_from(base_query.subquery())
    total = db.execute(count_statement).scalar_one() or 0

    offset = (page - 1) * page_size
    paged_query = (
        base_query.order_by(Activity.activity_date.desc(), Activity.id.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = list(db.execute(paged_query).scalars().all())

    return items, total


def get_activities_by_enrollment(
    db: Session,
    enrollment_id: int,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[Activity]:
    """Fetch all activities for a specific enrollment with optional date-range filtering.

    Why: Powers nested resource endpoint GET /api/v1/enrollments/{id}/activities.
    Inputs: db (Session), enrollment_id (int), from_date (date | None), to_date (date | None)
    Outputs: List of Activity records.
    Raises: EnrollmentNotFoundError if enrollment does not exist.
    """
    enrollment = db.get(Enrollment, enrollment_id)
    if not enrollment:
        raise EnrollmentNotFoundError(f"Enrollment with ID {enrollment_id} not found.")

    query = select(Activity).where(Activity.enrollment_id == enrollment_id)

    if from_date is not None:
        query = query.where(Activity.activity_date >= from_date)

    if to_date is not None:
        query = query.where(Activity.activity_date <= to_date)

    query = query.order_by(Activity.activity_date.desc(), Activity.id.desc())
    return list(db.execute(query).scalars().all())


def update_activity(
    db: Session,
    activity_id: int,
    update_in: ActivityUpdate,
) -> Activity:
    """Update an existing activity's attributes.

    Why: Allows corrections to activity date or details with future-date checks.
    Inputs: db (Session), activity_id (int), update_in (ActivityUpdate schema)
    Outputs: Updated Activity instance.
    Raises:
        ActivityNotFoundError: If activity does not exist.
        FutureActivityDateError: If new date is in the future.
    """
    activity = db.get(Activity, activity_id)
    if not activity:
        raise ActivityNotFoundError(f"Activity with ID {activity_id} not found.")

    update_data = update_in.model_dump(exclude_unset=True)

    if "activity_date" in update_data and update_data["activity_date"] is not None:
        if update_data["activity_date"] > date.today():
            raise FutureActivityDateError(
                f"Cannot update activity: Date '{update_data['activity_date']}' is in the future."
            )

    for field, value in update_data.items():
        setattr(activity, field, value)

    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity
