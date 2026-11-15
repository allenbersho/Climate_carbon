"""Monitoring domain service: timeline assembly, baseline matching, and delta calculations."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enrollment import Enrollment
from app.models.observation import Observation, ObservationType
from app.schemas.monitoring import EnrollmentMonitoringTimeline, TimelineObservationItem
from app.services.observation_service import EnrollmentNotFoundError


def get_enrollment_monitoring_timeline(
    db: Session,
    enrollment_id: int,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    observation_type: ObservationType | None = None,
    include_superseded: bool = False,
) -> EnrollmentMonitoringTimeline:
    """Retrieve chronological observation timeline for an enrollment with deltas from baseline.

    Why: MRV verification requires tracking how soil organic carbon, tree counts, and biomass
    evolve relative to the pre-project baseline measurement over multi-year monitoring cycles.
    Inputs:
        db: SQLAlchemy session
        enrollment_id: ID of the enrollment to inspect
        from_date: Optional lower bound timestamp filter (UTC)
        to_date: Optional upper bound timestamp filter (UTC)
        observation_type: Optional filter for a single measurement type
        include_superseded: If False (default), filters out superseded rows
    Outputs:
        EnrollmentMonitoringTimeline schema containing chronological items and computed deltas.
    Raises:
        EnrollmentNotFoundError: If enrollment_id does not exist.
    """
    enrollment = db.get(Enrollment, enrollment_id)
    if not enrollment:
        raise EnrollmentNotFoundError(f"Enrollment with ID {enrollment_id} not found.")

    # 1. Fetch active baseline observations for each measurement type
    # If a baseline was superseded, we want the authoritative active replacement (superseded_by IS NULL)
    baseline_query = select(Observation).where(
        Observation.enrollment_id == enrollment_id,
        Observation.is_baseline == True,  # noqa: E712
        Observation.superseded_by.is_(None),
    )
    active_baselines = list(db.execute(baseline_query).scalars().all())
    baselines_by_type: dict[ObservationType, Observation] = {
        b.type: b for b in active_baselines
    }
    baseline_id_map: dict[str, int] = {b.type.value: b.id for b in active_baselines}

    # 2. Fetch timeline observations matching filters
    timeline_query = select(Observation).where(
        Observation.enrollment_id == enrollment_id
    )

    if not include_superseded:
        timeline_query = timeline_query.where(Observation.superseded_by.is_(None))

    if observation_type is not None:
        timeline_query = timeline_query.where(Observation.type == observation_type)

    if from_date is not None:
        timeline_query = timeline_query.where(Observation.observed_at >= from_date)

    if to_date is not None:
        timeline_query = timeline_query.where(Observation.observed_at <= to_date)

    # Order strictly chronological so progress is viewed sequentially
    timeline_query = timeline_query.order_by(
        Observation.observed_at.asc(), Observation.id.asc()
    )
    observations = list(db.execute(timeline_query).scalars().all())

    # 3. Calculate delta from baseline for each observation item
    timeline_items: list[TimelineObservationItem] = []
    for obs in observations:
        is_superseded = obs.superseded_by is not None
        baseline = baselines_by_type.get(obs.type)

        baseline_id: int | None = None
        change_from_baseline: dict[str, float] | None = None

        if baseline is not None:
            baseline_id = baseline.id
            if obs.id == baseline.id:
                # Baseline observation itself has zero change relative to itself
                change_from_baseline = {
                    k: 0.0 for k, v in obs.values.items() if isinstance(v, (int, float))
                }
            else:
                # Compute (observation - baseline) for all numerical metrics
                deltas: dict[str, float] = {}
                for key, current_val in obs.values.items():
                    if isinstance(current_val, (int, float)):
                        baseline_val = baseline.values.get(key)
                        if isinstance(baseline_val, (int, float)):
                            diff = current_val - baseline_val
                            deltas[key] = round(float(diff), 4)
                change_from_baseline = deltas

        item = TimelineObservationItem(
            id=obs.id,
            type=obs.type,
            observed_at=obs.observed_at,
            is_baseline=obs.is_baseline,
            is_superseded=is_superseded,
            superseded_by=obs.superseded_by,
            values=obs.values,
            baseline_id=baseline_id,
            change_from_baseline=change_from_baseline,
        )
        timeline_items.append(item)

    return EnrollmentMonitoringTimeline(
        enrollment_id=enrollment.id,
        project_id=enrollment.project_id,
        parcel_id=enrollment.parcel_id,
        farmer_id=enrollment.farmer_id,
        baseline_observations=baseline_id_map,
        timeline=timeline_items,
        total_observations=len(timeline_items),
    )
