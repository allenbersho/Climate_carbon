"""Tests for the demo data seed script (Task 10.3)."""

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.farmer import Farmer
from app.models.land_parcel import LandParcel
from app.models.project import Project
from app.models.user import UserRole
from scripts.seed_demo_data import seed_demo_data


def test_seed_demo_data_execution_and_idempotency(db_session: Session) -> None:
    """Verify that seed_demo_data populates entities and handles existing counts."""
    # 1. Run seeder for a slice of 10 demo farmers
    stats = seed_demo_data(db_session, target_farmer_count=10, random_seed=123)

    assert stats["farmers"] == 10
    assert stats["parcels"] >= 10
    assert stats["enrollments"] >= 10
    assert stats["observations"] >= 20
    assert stats["activities"] >= 20
    assert stats["estimates"] >= 10

    # Verify database counts directly
    farmer_count = db_session.query(Farmer).filter(Farmer.is_deleted == False).count()  # noqa: E712
    assert farmer_count == 10

    parcel_count = db_session.query(LandParcel).count()
    assert parcel_count >= 10

    project_count = db_session.query(Project).count()
    assert project_count == 4

    # 2. Second execution with same target should detect existing farmers and generate 0 new ones
    second_stats = seed_demo_data(db_session, target_farmer_count=10, random_seed=123)
    assert second_stats["farmers"] == 0


def test_analytics_summary_with_seeded_demo_data(
    client: TestClient, db_session: Session
) -> None:
    """Verify that seeded demo data properly drives the analytics summary endpoint."""
    # Seed 15 demo farmers
    seed_demo_data(db_session, target_farmer_count=15, random_seed=999)

    # Login as admin to query analytics
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@carbontrack.org", "password": "AdminPassword123!"},
    )
    assert login_res.status_code == status.HTTP_200_OK
    token = login_res.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {token}"}

    summary_res = client.get("/api/v1/analytics/summary", headers=admin_headers)
    assert summary_res.status_code == status.HTTP_200_OK
    summary = summary_res.json()

    assert summary["total_farmers"] >= 15
    assert summary["total_acres"] > 0
    assert summary["total_co2e"] > 0
    assert summary["total_net_credits"] > 0
    assert len(summary["by_district"]) >= 1
