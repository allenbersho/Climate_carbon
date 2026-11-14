"""Automated validation pipeline implementing a pluggable rule engine via the Strategy/Registry pattern."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.enrollment import Enrollment
from app.models.land_parcel import LandParcel
from app.models.observation import Observation, ObservationType
from app.models.validation_issue import ValidationIssue, ValidationSeverity
from app.schemas.validation import (
    ObservationValidationSummary,
    ValidationIssueItem,
    ValidationIssueRead,
)
from app.services.observation_service import ObservationNotFoundError

# --- Scientific & Domain Validation Constants ---
# ASSUMPTION: Typical mineral soils in agricultural lands have SOC% between 0.1% and 10.0%.
MIN_SOC_PERCENT: float = 0.1
MAX_SOC_PERCENT: float = 10.0

# ASSUMPTION: Tree mortality or drop exceeding 30% between consecutive observations indicates possible reversal.
MAX_ALLOWED_TREE_DROP_PCT: float = 30.0

# ASSUMPTION: Physical maximum planting density for agroforestry and afforestation is 2,500 trees per acre.
MAX_PLAUSIBLE_TREES_PER_ACRE: float = 2500.0


@dataclass
class ValidationContext:
    """Encapsulates all domain entities and historical observations needed for rule evaluation."""

    observation: Observation
    enrollment: Enrollment | None = None
    parcel: LandParcel | None = None
    prior_observations: list[Observation] = field(default_factory=list)
    active_baseline: Observation | None = None


# Type alias for a validation rule strategy
ValidationRule = Callable[[ValidationContext], list[ValidationIssueItem]]


# =====================================================================
# Individual Validation Rules (Strategies)
# =====================================================================

def check_soc_range(context: ValidationContext) -> list[ValidationIssueItem]:
    """Flag soil observations where SOC% is outside the biologically plausible 0.1% - 10.0% range."""
    if context.observation.type != ObservationType.SOIL:
        return []

    soc = context.observation.values.get("soc_percent")
    if soc is None:
        return []

    if soc < MIN_SOC_PERCENT or soc > MAX_SOC_PERCENT:
        return [
            ValidationIssueItem(
                rule="soc_range_check",
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Soil Organic Carbon ({soc}%) is outside plausible agronomic range "
                    f"[{MIN_SOC_PERCENT}%, {MAX_SOC_PERCENT}%]. ASSUMPTION: Mineral agricultural "
                    f"soils range between {MIN_SOC_PERCENT}% and {MAX_SOC_PERCENT}% SOC."
                ),
            )
        ]
    return []


def check_tree_count_drop(context: ValidationContext) -> list[ValidationIssueItem]:
    """Flag tree count observations where tree count dropped by over 30% since the prior observation."""
    if context.observation.type != ObservationType.TREE_COUNT:
        return []

    current_count = context.observation.values.get("count")
    if current_count is None:
        return []

    # Find the most recent prior tree count observation
    prior_tree_obs = next(
        (o for o in context.prior_observations if o.type == ObservationType.TREE_COUNT),
        None,
    )
    if not prior_tree_obs:
        return []

    prior_count = prior_tree_obs.values.get("count")
    if prior_count is None or prior_count <= 0:
        return []

    if current_count < prior_count:
        drop_pct = ((prior_count - current_count) / prior_count) * 100.0
        if drop_pct > MAX_ALLOWED_TREE_DROP_PCT:
            return [
                ValidationIssueItem(
                    rule="tree_count_drop_check",
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Tree count dropped by {drop_pct:.1f}% (> {MAX_ALLOWED_TREE_DROP_PCT}% threshold) "
                        f"since previous observation (from {prior_count} to {current_count}). "
                        f"Possible carbon reversal, harvest, or dieback requiring field audit."
                    ),
                )
            ]
    return []


def check_missing_baseline(context: ValidationContext) -> list[ValidationIssueItem]:
    """Flag non-baseline observations when no active baseline observation exists for the enrollment."""
    # If the observation itself is the baseline, this rule passes
    if context.observation.is_baseline:
        return []

    if context.active_baseline is None:
        return [
            ValidationIssueItem(
                rule="missing_baseline_check",
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Monitoring observation of type '{context.observation.type.value}' lacks an active "
                    f"baseline observation for enrollment {context.observation.enrollment_id}. "
                    f"Baseline study is required before carbon removal can be verified."
                ),
            )
        ]
    return []


def check_future_date(context: ValidationContext) -> list[ValidationIssueItem]:
    """Flag observations whose observation timestamp is in the future."""
    now = datetime.now(timezone.utc)
    obs_time = context.observation.observed_at
    obs_time_utc = obs_time if obs_time.tzinfo is not None else obs_time.replace(tzinfo=timezone.utc)

    if obs_time_utc > now:
        return [
            ValidationIssueItem(
                rule="future_date_check",
                severity=ValidationSeverity.ERROR,
                message=f"Observation timestamp '{context.observation.observed_at}' is in the future.",
            )
        ]
    return []


def check_implausible_trees_per_acre(context: ValidationContext) -> list[ValidationIssueItem]:
    """Flag tree count observations where calculated density exceeds 2500 trees/acre."""
    if context.observation.type != ObservationType.TREE_COUNT:
        return []

    count = context.observation.values.get("count")
    if count is None:
        return []

    if context.parcel is None or context.parcel.area_acres <= 0:
        return []

    density = count / context.parcel.area_acres
    if density > MAX_PLAUSIBLE_TREES_PER_ACRE:
        return [
            ValidationIssueItem(
                rule="implausible_trees_per_acre_check",
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Implausible tree density of {density:.1f} trees/acre exceeds physical maximum "
                    f"of {MAX_PLAUSIBLE_TREES_PER_ACRE:.0f} trees/acre for parcel area "
                    f"{context.parcel.area_acres} acres. ASSUMPTION: Maximum agroforestry density is 2500 stems/acre."
                ),
            )
        ]
    return []


# =====================================================================
# Strategy Registry & Orchestrator
# =====================================================================

# Global list of registered validation rule functions
DEFAULT_RULES: list[ValidationRule] = [
    check_future_date,
    check_soc_range,
    check_tree_count_drop,
    check_missing_baseline,
    check_implausible_trees_per_acre,
]

_RULE_REGISTRY: list[ValidationRule] = list(DEFAULT_RULES)


def get_registered_rules() -> list[ValidationRule]:
    """Return the list of currently registered validation rules."""
    return list(_RULE_REGISTRY)


def register_rule(rule: ValidationRule) -> None:
    """Dynamically register a new validation rule into the pipeline."""
    if rule not in _RULE_REGISTRY:
        _RULE_REGISTRY.append(rule)


def reset_rules_to_default() -> None:
    """Reset the registry to standard built-in rules."""
    global _RULE_REGISTRY
    _RULE_REGISTRY = list(DEFAULT_RULES)


def build_validation_context(db: Session, observation: Observation) -> ValidationContext:
    """Assemble all related entities and historical observations into a ValidationContext.

    Why: Rules require parcel acreage and prior observations to evaluate rates of change.
    """
    enrollment = db.get(Enrollment, observation.enrollment_id)
    parcel: LandParcel | None = None
    if enrollment:
        parcel = db.get(LandParcel, enrollment.parcel_id)

    # Active baseline for this observation type
    baseline_query = select(Observation).where(
        Observation.enrollment_id == observation.enrollment_id,
        Observation.type == observation.type,
        Observation.is_baseline == True,  # noqa: E712
        Observation.superseded_by.is_(None),
    )
    active_baseline = db.execute(baseline_query).scalars().first()

    # Prior active observations ordered by observed_at descending
    prior_query = (
        select(Observation)
        .where(
            Observation.enrollment_id == observation.enrollment_id,
            Observation.type == observation.type,
            Observation.id != observation.id,
            Observation.observed_at < observation.observed_at,
            Observation.superseded_by.is_(None),
        )
        .order_by(Observation.observed_at.desc(), Observation.id.desc())
    )
    prior_observations = list(db.execute(prior_query).scalars().all())

    return ValidationContext(
        observation=observation,
        enrollment=enrollment,
        parcel=parcel,
        prior_observations=prior_observations,
        active_baseline=active_baseline,
    )


def validate_observation(
    db: Session,
    observation_id: int,
    persist: bool = True,
) -> list[ValidationIssue]:
    """Execute all registered validation rules against an observation and optionally persist issues.

    Why: Identifies measurement anomalies before carbon estimates are computed.
    Inputs: db (Session), observation_id (int), persist (bool)
    Outputs: List of ValidationIssue entities.
    Raises: ObservationNotFoundError if observation_id does not exist.
    """
    observation = db.get(Observation, observation_id)
    if not observation:
        raise ObservationNotFoundError(f"Observation with ID {observation_id} not found.")

    context = build_validation_context(db, observation)

    # Execute all strategy rules
    collected_issues: list[ValidationIssueItem] = []
    for rule_fn in _RULE_REGISTRY:
        rule_issues = rule_fn(context)
        collected_issues.extend(rule_issues)

    if not persist:
        # Return transient model instances without saving
        return [
            ValidationIssue(
                observation_id=observation_id,
                rule=item.rule,
                severity=item.severity,
                message=item.message,
            )
            for item in collected_issues
        ]

    # Clear prior issues for this observation to support clean re-runs
    db.execute(delete(ValidationIssue).where(ValidationIssue.observation_id == observation_id))

    persisted_issues: list[ValidationIssue] = []
    for item in collected_issues:
        issue = ValidationIssue(
            observation_id=observation_id,
            rule=item.rule,
            severity=item.severity,
            message=item.message,
        )
        db.add(issue)
        persisted_issues.append(issue)

    db.commit()
    for issue in persisted_issues:
        db.refresh(issue)

    return persisted_issues


def get_observation_validation_summary(
    db: Session,
    observation_id: int,
) -> ObservationValidationSummary:
    """Return the validation summary and stored issues for an observation.

    Why: Allows frontend and estimation engine to verify if an observation has blocking errors.
    """
    observation = db.get(Observation, observation_id)
    if not observation:
        raise ObservationNotFoundError(f"Observation with ID {observation_id} not found.")

    statement = (
        select(ValidationIssue)
        .where(ValidationIssue.observation_id == observation_id)
        .order_by(ValidationIssue.id.asc())
    )
    issues = list(db.execute(statement).scalars().all())

    error_count = sum(1 for i in issues if i.severity == ValidationSeverity.ERROR)
    warning_count = sum(1 for i in issues if i.severity == ValidationSeverity.WARNING)
    info_count = sum(1 for i in issues if i.severity == ValidationSeverity.INFO)

    return ObservationValidationSummary(
        observation_id=observation_id,
        is_valid=(error_count == 0),
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        issues=[ValidationIssueRead.model_validate(i) for i in issues],
    )
