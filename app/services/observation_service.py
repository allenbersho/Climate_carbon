"""Observation domain services, append-only superseding logic, and data verification."""

from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.enrollment import Enrollment
from app.models.observation import Observation, ObservationType
from app.schemas.observation import (
    ObservationCorrectionCreate,
    ObservationCreate,
    validate_observation_values,
)


class FutureObservationDateError(ValueError):
    """Exception raised when an observation timestamp is in the future."""


class EnrollmentNotFoundError(ValueError):
    """Exception raised when the referenced enrollment does not exist."""


class ObservationNotFoundError(ValueError):
    """Exception raised when an observation record is not found."""


class ObservationAlreadySupersededError(ValueError):
    """Exception raised when attempting to supersede an observation that is already superseded."""


class InvalidObservationValuesError(ValueError):
    """Exception raised when values dictionary fails schema validation for its type."""


def _ensure_not_future(timestamp: datetime) -> None:
    """Validate that a timestamp is not in the future relative to UTC now."""
    now = datetime.now(timezone.utc)
    ts_utc = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=timezone.utc)
    if ts_utc > now:
        raise FutureObservationDateError("Observation timestamp cannot be in the future.")


def create_observation(
    db: Session,
    observation_in: ObservationCreate,
    observer_id: int,
) -> Observation:
    """Record a new monitoring observation for an enrolled parcel.

    Why: Captures primary ground-truth field data (soil cores, tree counts, biomass)
    essential for MRV carbon accounting and model verification.
    Inputs: db (Session), observation_in (ObservationCreate schema), observer_id (int)
    Outputs: Newly persisted Observation instance.
    Raises:
        FutureObservationDateError: If observed_at is in the future.
        EnrollmentNotFoundError: If the associated enrollment_id does not exist.
        InvalidObservationValuesError: If measurement values fail shape validation.
    """
    _ensure_not_future(observation_in.observed_at)

    enrollment = db.get(Enrollment, observation_in.enrollment_id)
    if not enrollment:
        raise EnrollmentNotFoundError(
            f"Cannot record observation: Enrollment with ID {observation_in.enrollment_id} does not exist."
        )

    try:
        validated_values = validate_observation_values(
            observation_in.type, observation_in.values
        )
    except Exception as exc:
        raise InvalidObservationValuesError(str(exc)) from exc

    observation = Observation(
        enrollment_id=observation_in.enrollment_id,
        type=observation_in.type,
        values=validated_values,
        observed_at=observation_in.observed_at,
        observer_id=observer_id,
        is_baseline=observation_in.is_baseline,
        superseded_by=None,
    )
    db.add(observation)
    db.commit()
    db.refresh(observation)
    return observation


def supersede_observation(
    db: Session,
    old_observation_id: int,
    correction_in: ObservationCorrectionCreate,
    observer_id: int,
) -> tuple[Observation, Observation]:
    """Supersede an existing observation with a corrected new observation.

    Why: PROJECT_SPEC.md Rule 1 dictates that observations are strictly APPEND-ONLY.
    Historical measurements are never deleted or updated in place; instead, a new
    observation row is created, and the original row points to it via superseded_by.
    Inputs: db (Session), old_observation_id (int), correction_in (ObservationCorrectionCreate), observer_id (int)
    Outputs: Tuple of (new_observation, old_observation).
    Raises:
        ObservationNotFoundError: If the observation to supersede does not exist.
        ObservationAlreadySupersededError: If the observation was previously superseded.
        FutureObservationDateError: If correction timestamp is in the future.
        InvalidObservationValuesError: If corrected values fail shape validation.
    """
    old_observation = db.get(Observation, old_observation_id)
    if not old_observation:
        raise ObservationNotFoundError(f"Observation with ID {old_observation_id} not found.")

    if old_observation.superseded_by is not None:
        raise ObservationAlreadySupersededError(
            f"Observation {old_observation_id} has already been superseded by observation {old_observation.superseded_by}."
        )

    _ensure_not_future(correction_in.observed_at)

    try:
        validated_values = validate_observation_values(
            old_observation.type, correction_in.values
        )
    except Exception as exc:
        raise InvalidObservationValuesError(str(exc)) from exc

    # Inherit original baseline flag unless explicitly overridden
    is_baseline = (
        correction_in.is_baseline
        if correction_in.is_baseline is not None
        else old_observation.is_baseline
    )

    new_observation = Observation(
        enrollment_id=old_observation.enrollment_id,
        type=old_observation.type,
        values=validated_values,
        observed_at=correction_in.observed_at,
        observer_id=observer_id,
        is_baseline=is_baseline,
        superseded_by=None,
    )
    db.add(new_observation)
    db.flush()  # Obtain new_observation.id before committing

    # Link the old observation to the newly created replacement
    old_observation.superseded_by = new_observation.id
    db.add(old_observation)
    db.commit()

    db.refresh(new_observation)
    db.refresh(old_observation)
    return new_observation, old_observation


def get_observation_by_id(db: Session, observation_id: int) -> Observation | None:
    """Fetch a single observation record by primary key ID.

    Why: Allows auditors and verifiers to review specific measurements, lineage, and issues.
    Inputs: db (Session), observation_id (int)
    Outputs: Observation instance if found, None otherwise.
    """
    stmt = (
        select(Observation)
        .options(selectinload(Observation.validation_issues))
        .where(Observation.id == observation_id)
    )
    return db.execute(stmt).scalars().first()


def list_observations(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    enrollment_id: int | None = None,
    observation_type: ObservationType | None = None,
    is_baseline: bool | None = None,
    active_only: bool = False,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> tuple[list[Observation], int]:
    """Retrieve a paginated slice of observations with optional filters.

    Why: Powers the observation registry and estimation pipeline data loading.
    active_only=True excludes superseded observations from calculations.
    Inputs: db (Session), page, page_size, enrollment_id, observation_type, is_baseline, active_only, from_date, to_date
    Outputs: Tuple of (list of Observation objects, total integer count).
    """
    base_query = select(Observation)

    if enrollment_id is not None:
        base_query = base_query.where(Observation.enrollment_id == enrollment_id)

    if observation_type is not None:
        base_query = base_query.where(Observation.type == observation_type)

    if is_baseline is not None:
        base_query = base_query.where(Observation.is_baseline == is_baseline)

    if active_only:
        base_query = base_query.where(Observation.superseded_by.is_(None))

    if from_date is not None:
        base_query = base_query.where(Observation.observed_at >= from_date)

    if to_date is not None:
        base_query = base_query.where(Observation.observed_at <= to_date)

    count_statement = select(func.count()).select_from(base_query.subquery())
    total = db.execute(count_statement).scalar_one() or 0

    offset = (page - 1) * page_size
    paged_query = (
        base_query.options(selectinload(Observation.validation_issues))
        .order_by(Observation.observed_at.desc(), Observation.id.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = list(db.execute(paged_query).scalars().all())

    return items, total


def get_observations_by_enrollment(
    db: Session,
    enrollment_id: int,
    active_only: bool = False,
) -> list[Observation]:
    """Fetch all observations for a specific enrollment.

    Why: Powers the sub-resource route GET /api/v1/enrollments/{id}/observations.
    Inputs: db (Session), enrollment_id (int), active_only (bool)
    Outputs: List of Observation instances.
    Raises: EnrollmentNotFoundError if enrollment does not exist.
    """
    enrollment = db.get(Enrollment, enrollment_id)
    if not enrollment:
        raise EnrollmentNotFoundError(f"Enrollment with ID {enrollment_id} not found.")

    query = (
        select(Observation)
        .options(selectinload(Observation.validation_issues))
        .where(Observation.enrollment_id == enrollment_id)
    )
    if active_only:
        query = query.where(Observation.superseded_by.is_(None))

    query = query.order_by(Observation.observed_at.asc(), Observation.id.asc())
    return list(db.execute(query).scalars().all())
