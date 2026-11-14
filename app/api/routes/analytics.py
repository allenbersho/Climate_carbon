"""Analytics and reporting API routes providing SQL-aggregated portfolio and project metrics."""

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUserDep, SessionDep
from app.schemas.analytics import (
    AnalyticsSummaryResponse,
    ProjectAnalyticsResponse,
)
from app.services import analytics_service
from app.services.analytics_service import ProjectNotFoundError

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get(
    "/summary",
    response_model=AnalyticsSummaryResponse,
    summary="Portfolio analytics summary with district breakdown",
    description="Returns aggregate farmer count, enrolled acres, total CO2e, net credits, and district groupings using pure SQL aggregation.",
)
def get_portfolio_summary(
    db: SessionDep,
    _current_user: CurrentUserDep,
    project_id: int | None = Query(
        default=None,
        description="Optional filter to aggregate metrics for a specific project",
    ),
) -> AnalyticsSummaryResponse:
    """Retrieve high-level portfolio reporting metrics and geographic breakdown."""
    return analytics_service.get_analytics_summary(db, project_id=project_id)


@router.get(
    "/projects/{project_id}",
    response_model=ProjectAnalyticsResponse,
    summary="Per-project analytics summary",
    description="Returns aggregate reporting metrics and district breakdown for a specific project.",
)
def get_project_summary(
    project_id: int,
    db: SessionDep,
    _current_user: CurrentUserDep,
) -> ProjectAnalyticsResponse:
    """Retrieve reporting analytics for a single project by ID."""
    try:
        return analytics_service.get_project_analytics(db, project_id=project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
