"""Carbon estimation service orchestrating data gathering, validation filtering, and pure calculator execution."""

from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.carbon_estimate import CarbonEstimate, EstimateStatus
from app.models.enrollment import Enrollment
from app.models.land_parcel import LandParcel
from app.models.methodology import Methodology
from app.models.observation import Observation, ObservationType
from app.models.project import Project, ProjectType
from app.models.validation_issue import ValidationIssue, ValidationSeverity
from app.services.carbon.afforestation import AfforestationCalculator
from app.services.carbon.soil_carbon import SoilCarbonCalculator
from app.services.methodology_service import (
    MethodologyNotFoundError,
    get_methodology_by_id,
    get_methodology_by_name_and_version,
)


class EnrollmentNotFoundError(ValueError):
    """Exception raised when the referenced enrollment does not exist."""


class InsufficientObservationsError(ValueError):
    """Exception raised when an enrollment lacks required baseline or monitoring observations."""


class UnsupportedProjectTypeError(ValueError):
    """Exception raised when attempting carbon estimation for an unsupported project type."""


def _get_valid_active_observations(
    db: Session,
    enrollment_id: int,
    obs_type: ObservationType,
) -> list[Observation]:
    """Retrieve all active (non-superseded) observations for an enrollment excluding error-flagged records.

    Why: PROJECT_SPEC.md Section 6 Rule 4 states:
    'Observations with error-severity validation issues are EXCLUDED from estimates.'
    """
    # Exclude superseded observations and observations that have any error-severity validation issue
    stmt = (
        select(Observation)
        .options(selectinload(Observation.validation_issues))
        .where(
            Observation.enrollment_id == enrollment_id,
            Observation.type == obs_type,
            Observation.superseded_by.is_(None),
            ~Observation.validation_issues.any(ValidationIssue.severity == ValidationSeverity.ERROR),
        )
        .order_by(Observation.observed_at.asc(), Observation.id.asc())
    )
    return list(db.execute(stmt).scalars().all())


def resolve_methodology_for_project(
    db: Session,
    project: Project,
    requested_methodology_id: int | None = None,
) -> Methodology:
    """Resolve the versioned Methodology entity to use for this project's carbon estimation.

    Why: PROJECT_SPEC.md Section 7 states that parameters live in the methodologies table (versioned).
    """
    if requested_methodology_id is not None:
        methodology = get_methodology_by_id(db, requested_methodology_id)
        if not methodology:
            raise MethodologyNotFoundError(
                f"Requested methodology with ID {requested_methodology_id} not found."
            )
        return methodology

    if project.methodology_id is not None:
        methodology = get_methodology_by_id(db, project.methodology_id)
        if methodology:
            return methodology

    # Fallback to standard active default methodology based on project type
    if project.type == ProjectType.AFFORESTATION:
        methodology = get_methodology_by_name_and_version(db, name="Afforestation", version="v1")
    elif project.type == ProjectType.REGEN_AG:
        methodology = get_methodology_by_name_and_version(db, name="Soil Carbon", version="v1")
    else:
        raise UnsupportedProjectTypeError(
            f"No default methodology configured for project type '{project.type.value}'."
        )

    if not methodology:
        raise MethodologyNotFoundError(
            f"Default active methodology for project type '{project.type.value}' not found in database. "
            "Please run the methodology seeder."
        )

    return methodology


def create_carbon_estimate(
    db: Session,
    enrollment_id: int,
    methodology_id: int | None = None,
) -> CarbonEstimate:
    """Calculate and persist an auditable CarbonEstimate for an enrollment.

    Workflow:
    1. Fetch enrollment, parcel (area), and project (type).
    2. Query active, valid observations (excluding error-severity records per Rule 4).
    3. Enforce Rule 3: Must have >= 1 valid baseline and >= 1 later monitoring observation.
    4. Resolve versioned Methodology and extract parameters JSON.
    5. Call pure calculator (AfforestationCalculator or SoilCarbonCalculator).
    6. Construct inputs_snapshot preserving all input values, observation IDs, and parameters (Rule 5).
    7. Persist and return CarbonEstimate record with status 'draft'.

    Raises:
        EnrollmentNotFoundError: If enrollment_id does not exist.
        InsufficientObservationsError: If missing required baseline or monitoring observations.
        UnsupportedProjectTypeError: If project type does not have an MRV calculator.
        MethodologyNotFoundError: If referenced methodology cannot be resolved.
    """
    enrollment = db.get(Enrollment, enrollment_id)
    if not enrollment:
        raise EnrollmentNotFoundError(f"Enrollment with ID {enrollment_id} not found.")

    project = db.get(Project, enrollment.project_id)
    if not project:
        raise ValueError(f"Project with ID {enrollment.project_id} not found for enrollment {enrollment_id}.")

    parcel = db.get(LandParcel, enrollment.parcel_id)
    if not parcel:
        raise ValueError(f"Land parcel with ID {enrollment.parcel_id} not found for enrollment {enrollment_id}.")

    # 1. Determine observation type
    if project.type == ProjectType.AFFORESTATION:
        obs_type = ObservationType.TREE_COUNT
    elif project.type == ProjectType.REGEN_AG:
        obs_type = ObservationType.SOIL
    else:
        raise UnsupportedProjectTypeError(
            f"Carbon estimation is not supported for project type '{project.type.value}'."
        )

    # 2. Gather valid observations excluding error-flagged records (Rule 4)
    valid_observations = _get_valid_active_observations(db, enrollment_id=enrollment_id, obs_type=obs_type)

    # 3. Enforce Rule 3: Baseline observation + at least one later observation
    baseline_obs = next((o for o in valid_observations if o.is_baseline), None)
    if not baseline_obs:
        raise InsufficientObservationsError(
            f"Cannot estimate carbon for enrollment {enrollment_id}: Lacks a valid baseline observation "
            f"of type '{obs_type.value}' (or existing baseline is flagged with validation errors)."
        )

    later_observations = [
        o for o in valid_observations if not o.is_baseline and o.observed_at > baseline_obs.observed_at
    ]
    if not later_observations:
        raise InsufficientObservationsError(
            f"Cannot estimate carbon for enrollment {enrollment_id}: Requires at least one valid monitoring "
            f"observation of type '{obs_type.value}' observed after baseline date ({baseline_obs.observed_at})."
        )

    # Pick the most recent valid monitoring observation
    latest_monitoring = later_observations[-1]

    # 4. Resolve Methodology parameters
    methodology = resolve_methodology_for_project(
        db,
        project=project,
        requested_methodology_id=methodology_id,
    )

    # 5. Dispatch to pure functional calculator
    if project.type == ProjectType.AFFORESTATION:
        calculator = AfforestationCalculator()
        inputs: dict[str, Any] = {
            "trees": latest_monitoring.values.get("count", 0),
        }
        calc_result = calculator.calculate(inputs=inputs, parameters=methodology.parameters)

    elif project.type == ProjectType.REGEN_AG:
        calculator = SoilCarbonCalculator()
        inputs = {
            "area_acres": parcel.area_acres,
            "baseline": baseline_obs.values,
            "current": latest_monitoring.values,
        }
        calc_result = calculator.calculate(inputs=inputs, parameters=methodology.parameters)

    # 6. Assemble complete inputs_snapshot for permanent audit reproducibility (Rule 5)
    snapshot = dict(calc_result.inputs_snapshot)
    snapshot["meta"] = {
        "enrollment_id": enrollment.id,
        "parcel_id": parcel.id,
        "parcel_area_acres": parcel.area_acres,
        "project_id": project.id,
        "project_type": project.type.value,
        "methodology_id": methodology.id,
        "methodology_name": methodology.name,
        "methodology_version": methodology.version,
        "baseline_observation_id": baseline_obs.id,
        "baseline_observed_at": baseline_obs.observed_at.isoformat(),
        "monitoring_observation_id": latest_monitoring.id,
        "monitoring_observed_at": latest_monitoring.observed_at.isoformat(),
        "calculation_details": calc_result.details,
    }

    # 7. Persist CarbonEstimate record
    estimate = CarbonEstimate(
        enrollment_id=enrollment_id,
        methodology_id=methodology.id,
        methodology_version=methodology.version,
        inputs_snapshot=snapshot,
        co2e_tonnes=calc_result.co2e_gross_tonnes,
        uncertainty_pct=calc_result.uncertainty_pct,
        buffer_pct=calc_result.buffer_pct,
        net_credits=calc_result.net_credits,
        status=EstimateStatus.DRAFT,
    )
    db.add(estimate)
    db.commit()
    db.refresh(estimate)
    return estimate


def get_estimates_by_enrollment(
    db: Session,
    enrollment_id: int,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[CarbonEstimate], int]:
    """Retrieve a paginated history of carbon estimates for an enrollment.

    Why: Allows auditors and verifiers to review historical credit calculations and lineage.
    Inputs: db (Session), enrollment_id (int), page, page_size
    Outputs: Tuple of (list of CarbonEstimate entities, total count).
    """
    enrollment = db.get(Enrollment, enrollment_id)
    if not enrollment:
        raise EnrollmentNotFoundError(f"Enrollment with ID {enrollment_id} not found.")

    base_query = (
        select(CarbonEstimate)
        .where(CarbonEstimate.enrollment_id == enrollment_id)
    )

    count_stmt = select(func.count()).select_from(base_query.subquery())
    total = db.execute(count_stmt).scalar_one() or 0

    offset = (page - 1) * page_size
    paged_query = (
        base_query.order_by(CarbonEstimate.computed_at.desc(), CarbonEstimate.id.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = list(db.execute(paged_query).scalars().all())
    return items, total


def get_estimate_by_id(db: Session, estimate_id: int) -> CarbonEstimate | None:
    """Fetch a single carbon estimate by ID."""
    return db.get(CarbonEstimate, estimate_id)
