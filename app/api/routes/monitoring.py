"""Monitoring and timeline analytics API routes."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUserDep, SessionDep
from app.models.observation import ObservationType
from app.schemas.monitoring import EnrollmentMonitoringTimeline
from app.services import monitoring_service
from app.services.observation_service import EnrollmentNotFoundError

router = APIRouter(prefix="/monitoring", tags=["Monitoring"])


@router.get(
    "/{enrollment_id}/timeline",
    response_model=EnrollmentMonitoringTimeline,
    summary="Get monitoring timeline with change from baseline",
    description="Returns chronological observations for an enrollment with delta from baseline for each measurement.",
)
def get_monitoring_timeline(
    enrollment_id: int,
    db: SessionDep,
    _current_user: CurrentUserDep,
    from_date: datetime | None = Query(
        default=None,
        description="Filter observations from this timestamp onwards (ISO-8601 UTC)",
    ),
    to_date: datetime | None = Query(
        default=None,
        description="Filter observations up to this timestamp (ISO-8601 UTC)",
    ),
    observation_type: ObservationType | None = Query(
        default=None,
        alias="type",
        description="Filter timeline to a specific measurement type (soil, tree_count, biomass)",
    ),
    include_superseded: bool = Query(
        default=False,
        description="If true, includes historical superseded observations in the timeline",
    ),
) -> EnrollmentMonitoringTimeline:
    """Retrieve chronological observation timeline with baseline change metrics."""
    try:
        return monitoring_service.get_enrollment_monitoring_timeline(
            db,
            enrollment_id=enrollment_id,
            from_date=from_date,
            to_date=to_date,
            observation_type=observation_type,
            include_superseded=include_superseded,
        )
    except EnrollmentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
