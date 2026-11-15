"""Analytics and reporting API routes providing SQL-aggregated portfolio and project metrics."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import CurrentUserDep, SessionDep
from app.schemas.analytics import (
    AnalyticsSummaryResponse,
    ProjectAnalyticsResponse,
    TimeSeriesResponse,
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


@router.get(
    "/timeseries",
    response_model=TimeSeriesResponse,
    summary="Cumulative carbon removal time-series curve",
    description="Uses SQL window functions to compute running cumulative gross CO2e and net credits over time.",
)
def get_carbon_timeseries(
    db: SessionDep,
    _current_user: CurrentUserDep,
    project_id: int | None = Query(
        default=None,
        description="Optional filter to scope time-series to a specific project",
    ),
    from_date: datetime | None = Query(
        default=None,
        description="Optional start timestamp (ISO-8601)",
    ),
    to_date: datetime | None = Query(
        default=None,
        description="Optional end timestamp (ISO-8601)",
    ),
) -> TimeSeriesResponse:
    """Retrieve cumulative carbon accumulation data points using an SQL window function."""
    try:
        return analytics_service.get_carbon_timeseries(
            db,
            project_id=project_id,
            from_date=from_date,
            to_date=to_date,
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/export/csv",
    summary="Export carbon credit calculations to CSV",
    description="Generates an audit-ready CSV file of all calculated carbon estimates with project, farmer, and parcel metadata.",
)
def export_carbon_estimates_csv(
    db: SessionDep,
    _current_user: CurrentUserDep,
    project_id: int | None = Query(
        default=None,
        description="Optional filter to export estimates for a specific project only",
    ),
) -> Response:
    """Stream an audit-ready CSV export of calculated carbon credits."""
    try:
        csv_data = analytics_service.generate_carbon_estimates_csv(
            db, project_id=project_id
        )
        filename = (
            f"carbon_estimates_project_{project_id}.csv"
            if project_id
            else "carbon_estimates_portfolio.csv"
        )
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    except ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
