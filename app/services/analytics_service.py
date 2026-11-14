"""Analytics domain service executing pure SQL aggregations for portfolio and project reporting."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.carbon_estimate import CarbonEstimate
from app.models.enrollment import Enrollment
from app.models.farmer import Farmer
from app.models.land_parcel import LandParcel
from app.models.project import Project
from app.schemas.analytics import (
    AnalyticsSummaryResponse,
    DistrictBreakdown,
    ProjectAnalyticsResponse,
)


class ProjectNotFoundError(ValueError):
    """Exception raised when the requested project does not exist."""


def get_analytics_summary(
    db: Session,
    project_id: int | None = None,
) -> AnalyticsSummaryResponse:
    """Compute portfolio-wide or project-filtered reporting analytics using pure SQL aggregation.

    Why: PROJECT_SPEC Section 7 & Task 7.1 require database-level GROUP BY aggregation
    rather than slow, unscalable Python loops.

    Algorithm:
    1. Subquery 'enrolled_parcels': Joins enrollments, land_parcels, and farmers to isolate
       distinct enrolled acres and geographic location per enrollment (1 row per enrollment).
    2. Subquery 'carbon_by_enrollment': Pre-aggregates carbon estimates by enrollment_id
       (at most 1 row per enrollment) to prevent Cartesian duplication of acres.
    3. District Aggregation: Joins enrolled_parcels to carbon_by_enrollment and groups
       by (district, state) in SQL.
    4. Overall Totals: Aggregates total farmers, total acres, total CO2e, and net credits.
    """
    # 1. Subquery: 1 row per enrollment with parcel acres and farmer location
    enrollment_query = (
        select(
            Enrollment.id.label("enrollment_id"),
            Enrollment.project_id.label("project_id"),
            Enrollment.farmer_id.label("farmer_id"),
            LandParcel.area_acres.label("area_acres"),
            Farmer.district.label("district"),
            Farmer.state.label("state"),
        )
        .join(LandParcel, Enrollment.parcel_id == LandParcel.id)
        .join(Farmer, Enrollment.farmer_id == Farmer.id)
        .where(Farmer.is_deleted == False)  # noqa: E712
    )
    if project_id is not None:
        enrollment_query = enrollment_query.where(Enrollment.project_id == project_id)

    enrolled_sub = enrollment_query.subquery("enrolled_sub")

    # 2. Subquery: Pre-aggregated carbon removals per enrollment
    carbon_query = (
        select(
            CarbonEstimate.enrollment_id.label("enrollment_id"),
            func.coalesce(func.sum(CarbonEstimate.co2e_tonnes), 0.0).label("co2e_tonnes"),
            func.coalesce(func.sum(CarbonEstimate.net_credits), 0.0).label("net_credits"),
        )
        .group_by(CarbonEstimate.enrollment_id)
    )
    carbon_sub = carbon_query.subquery("carbon_sub")

    # 3. District Breakdown SQL Query: GROUP BY district, state
    district_stmt = (
        select(
            enrolled_sub.c.district,
            enrolled_sub.c.state,
            func.count(func.distinct(enrolled_sub.c.farmer_id)).label("farmers_count"),
            func.coalesce(func.sum(enrolled_sub.c.area_acres), 0.0).label("total_acres"),
            func.coalesce(func.sum(carbon_sub.c.co2e_tonnes), 0.0).label("total_co2e"),
            func.coalesce(func.sum(carbon_sub.c.net_credits), 0.0).label("net_credits"),
        )
        .outerjoin(carbon_sub, enrolled_sub.c.enrollment_id == carbon_sub.c.enrollment_id)
        .group_by(enrolled_sub.c.district, enrolled_sub.c.state)
        .order_by(
            func.coalesce(func.sum(carbon_sub.c.net_credits), 0.0).desc(),
            enrolled_sub.c.district.asc(),
        )
    )
    district_rows = db.execute(district_stmt).all()

    by_district = [
        DistrictBreakdown(
            district=row.district,
            state=row.state,
            farmers_count=int(row.farmers_count),
            total_acres=round(float(row.total_acres), 4),
            total_co2e=round(float(row.total_co2e), 4),
            net_credits=round(float(row.net_credits), 4),
        )
        for row in district_rows
    ]

    # 4. Overall Totals SQL Query (Single round-trip scalar aggregation)
    totals_stmt = (
        select(
            func.count(func.distinct(enrolled_sub.c.farmer_id)).label("total_farmers"),
            func.coalesce(func.sum(enrolled_sub.c.area_acres), 0.0).label("total_acres"),
            func.coalesce(func.sum(carbon_sub.c.co2e_tonnes), 0.0).label("total_co2e"),
            func.coalesce(func.sum(carbon_sub.c.net_credits), 0.0).label("total_net_credits"),
        )
        .outerjoin(carbon_sub, enrolled_sub.c.enrollment_id == carbon_sub.c.enrollment_id)
    )
    totals_row = db.execute(totals_stmt).one()

    return AnalyticsSummaryResponse(
        total_farmers=int(totals_row.total_farmers or 0),
        total_acres=round(float(totals_row.total_acres or 0.0), 4),
        total_co2e=round(float(totals_row.total_co2e or 0.0), 4),
        total_net_credits=round(float(totals_row.total_net_credits or 0.0), 4),
        by_district=by_district,
    )


def get_project_analytics(
    db: Session,
    project_id: int,
) -> ProjectAnalyticsResponse:
    """Retrieve reporting analytics for a single project.

    Why: Enables per-project dashboard summaries and MRV verification reviews.
    Inputs: db (Session), project_id (int)
    Outputs: ProjectAnalyticsResponse with project metadata and aggregated metrics.
    Raises: ProjectNotFoundError if project_id does not exist.
    """
    project = db.get(Project, project_id)
    if not project:
        raise ProjectNotFoundError(f"Project with ID {project_id} not found.")

    summary = get_analytics_summary(db, project_id=project_id)

    return ProjectAnalyticsResponse(
        project_id=project.id,
        project_name=project.name,
        project_type=project.type.value,
        project_status=project.status.value,
        total_farmers=summary.total_farmers,
        total_acres=summary.total_acres,
        total_co2e=summary.total_co2e,
        total_net_credits=summary.total_net_credits,
        by_district=summary.by_district,
    )
