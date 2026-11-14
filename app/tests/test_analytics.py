"""Integration tests for Analytics reporting summaries, SQL GROUP BY aggregations,

and per-project analytics.
"""

from fastapi import status
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from app.models.user import UserRole
from app.services.methodology_service import seed_default_methodologies


def _create_user_and_login(client: TestClient, email: str, role: UserRole) -> dict[str, str]:
    """Helper to bootstrap an admin, register an actor with a specific role, and return auth headers."""
    client.post(
        "/api/v1/auth/register",
        json={"email": "super.admin@carbontrack.org", "password": "AdminPassword123!"},
    )
    admin_login = client.post(
        "/api/v1/auth/login",
        json={"email": "super.admin@carbontrack.org", "password": "AdminPassword123!"},
    )
    admin_token = admin_login.json()["access_token"]

    if role == UserRole.ADMIN and email == "super.admin@carbontrack.org":
        return {"Authorization": f"Bearer {admin_token}"}

    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "UserPassword123!", "role": role.value},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    user_login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "UserPassword123!"},
    )
    user_token = user_login.json()["access_token"]
    return {"Authorization": f"Bearer {user_token}"}


def test_empty_analytics_summary_returns_zeros(client: TestClient) -> None:
    """Verify that an empty database returns zeros without crashing SQL aggregations."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)

    res = client.get("/api/v1/analytics/summary", headers=admin_headers)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["total_farmers"] == 0
    assert data["total_acres"] == 0.0
    assert data["total_co2e"] == 0.0
    assert data["total_net_credits"] == 0.0
    assert data["by_district"] == []


def test_portfolio_and_project_analytics_sql_aggregation(client: TestClient, db_session: Session) -> None:
    """Verify SQL GROUP BY aggregations across multiple districts, projects, and farmers."""
    seed_default_methodologies(db_session)
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.ana1@carbontrack.org", UserRole.FIELD_OFFICER)
    verifier_headers = _create_user_and_login(client, "verifier.ana1@carbontrack.org", UserRole.VERIFIER)

    # 1. Create Projects
    proj1 = client.post(
        "/api/v1/projects",
        json={"name": "Mandya Regen Ag", "type": "regen_ag", "start_date": "2025-01-01"},
        headers=admin_headers,
    ).json()
    proj1_id = proj1["id"]

    proj2 = client.post(
        "/api/v1/projects",
        json={"name": "Uttara Afforestation", "type": "afforestation", "start_date": "2025-01-01"},
        headers=admin_headers,
    ).json()
    proj2_id = proj2["id"]

    # 2. Setup Farmer 1 in Mandya (10 acres, Regen Ag)
    f1_id = client.post(
        "/api/v1/farmers",
        json={"name": "Boregowda", "district": "Mandya", "state": "Karnataka", "consent_given": True},
        headers=officer_headers,
    ).json()["id"]
    p1_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": f1_id, "area_acres": 10.0},
        headers=officer_headers,
    ).json()["id"]
    e1_id = client.post(
        "/api/v1/enrollments",
        json={"project_id": proj1_id, "parcel_id": p1_id, "farmer_id": f1_id, "status": "active"},
        headers=officer_headers,
    ).json()["id"]

    # Observations + Estimate for E1 (Soil Carbon: net = 133.191468)
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": e1_id,
            "type": "soil",
            "values": {"soc_percent": 1.2, "bulk_density": 1.30, "depth_cm": 30.0},
            "observed_at": "2025-01-01T10:00:00Z",
            "is_baseline": True,
        },
        headers=officer_headers,
    )
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": e1_id,
            "type": "soil",
            "values": {"soc_percent": 1.6, "bulk_density": 1.25, "depth_cm": 30.0},
            "observed_at": "2025-06-01T10:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    )
    client.post("/api/v1/carbon/estimate", json={"enrollment_id": e1_id}, headers=verifier_headers)

    # 3. Setup Farmer 2 in Mandya (5 acres, Regen Ag, no estimate yet)
    f2_id = client.post(
        "/api/v1/farmers",
        json={"name": "Thimmegowda", "district": "Mandya", "state": "Karnataka", "consent_given": True},
        headers=officer_headers,
    ).json()["id"]
    p2_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": f2_id, "area_acres": 5.0},
        headers=officer_headers,
    ).json()["id"]
    client.post(
        "/api/v1/enrollments",
        json={"project_id": proj1_id, "parcel_id": p2_id, "farmer_id": f2_id, "status": "active"},
        headers=officer_headers,
    )

    # 4. Setup Farmer 3 in Uttara Kannada (8 acres, Afforestation)
    f3_id = client.post(
        "/api/v1/farmers",
        json={"name": "Hegde", "district": "Uttara Kannada", "state": "Karnataka", "consent_given": True},
        headers=officer_headers,
    ).json()["id"]
    p3_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": f3_id, "area_acres": 8.0},
        headers=officer_headers,
    ).json()["id"]
    e3_id = client.post(
        "/api/v1/enrollments",
        json={"project_id": proj2_id, "parcel_id": p3_id, "farmer_id": f3_id, "status": "active"},
        headers=officer_headers,
    ).json()["id"]

    # Observations + Estimate for E3 (Afforestation: net = 32.95905)
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": e3_id,
            "type": "tree_count",
            "values": {"count": 100, "avg_height_m": 1.5},
            "observed_at": "2025-01-01T10:00:00Z",
            "is_baseline": True,
        },
        headers=officer_headers,
    )
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": e3_id,
            "type": "tree_count",
            "values": {"count": 500, "avg_height_m": 2.5},
            "observed_at": "2025-06-01T10:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    )
    client.post("/api/v1/carbon/estimate", json={"enrollment_id": e3_id}, headers=verifier_headers)

    # -------------------------------------------------------------
    # 5. Verify Portfolio-Wide Analytics (GET /api/v1/analytics/summary)
    # -------------------------------------------------------------
    summary_res = client.get("/api/v1/analytics/summary", headers=officer_headers)
    assert summary_res.status_code == status.HTTP_200_OK
    summary = summary_res.json()

    assert summary["total_farmers"] == 3
    assert summary["total_acres"] == pytest.approx(23.0, abs=1e-4)  # 10 + 5 + 8
    expected_total_credits = 133.191468 + 32.95905
    assert summary["total_net_credits"] == pytest.approx(expected_total_credits, abs=1e-3)

    # Verify District Breakdown (GROUP BY district, state)
    districts = {d["district"]: d for d in summary["by_district"]}
    assert "Mandya" in districts
    assert "Uttara Kannada" in districts

    mandya = districts["Mandya"]
    assert mandya["farmers_count"] == 2
    assert mandya["total_acres"] == pytest.approx(15.0, abs=1e-4)
    assert mandya["net_credits"] == pytest.approx(133.191468, abs=1e-3)

    uttara = districts["Uttara Kannada"]
    assert uttara["farmers_count"] == 1
    assert uttara["total_acres"] == pytest.approx(8.0, abs=1e-4)
    assert uttara["net_credits"] == pytest.approx(32.95905, abs=1e-3)

    # -------------------------------------------------------------
    # 6. Verify Per-Project Analytics (GET /api/v1/analytics/projects/{id})
    # -------------------------------------------------------------
    p1_res = client.get(f"/api/v1/analytics/projects/{proj1_id}", headers=officer_headers)
    assert p1_res.status_code == status.HTTP_200_OK
    p1_data = p1_res.json()
    assert p1_data["project_id"] == proj1_id
    assert p1_data["project_name"] == "Mandya Regen Ag"
    assert p1_data["project_type"] == "regen_ag"
    assert p1_data["total_farmers"] == 2
    assert p1_data["total_acres"] == pytest.approx(15.0, abs=1e-4)
    assert p1_data["total_net_credits"] == pytest.approx(133.191468, abs=1e-3)
    assert len(p1_data["by_district"]) == 1
    assert p1_data["by_district"][0]["district"] == "Mandya"

    p2_res = client.get(f"/api/v1/analytics/projects/{proj2_id}", headers=officer_headers)
    assert p2_res.status_code == status.HTTP_200_OK
    p2_data = p2_res.json()
    assert p2_data["total_farmers"] == 1
    assert p2_data["total_acres"] == pytest.approx(8.0, abs=1e-4)
    assert p2_data["total_net_credits"] == pytest.approx(32.95905, abs=1e-3)


def test_soft_deleted_farmers_excluded_from_analytics(client: TestClient) -> None:
    """Verify that soft-deleted farmers are excluded from analytics aggregates."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.ana2@carbontrack.org", UserRole.FIELD_OFFICER)

    proj_id = client.post(
        "/api/v1/projects",
        json={"name": "Soft Delete Project", "type": "regen_ag", "start_date": "2025-01-01"},
        headers=admin_headers,
    ).json()["id"]

    farmer_id = client.post(
        "/api/v1/farmers",
        json={"name": "Gowdappa", "district": "Mysuru", "state": "Karnataka", "consent_given": True},
        headers=officer_headers,
    ).json()["id"]

    parcel_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 25.0},
        headers=officer_headers,
    ).json()["id"]

    client.post(
        "/api/v1/enrollments",
        json={"project_id": proj_id, "parcel_id": parcel_id, "farmer_id": farmer_id, "status": "active"},
        headers=officer_headers,
    )

    # 1. Active: 1 farmer, 25 acres
    active_res = client.get("/api/v1/analytics/summary", headers=officer_headers).json()
    assert active_res["total_farmers"] >= 1

    # 2. Soft-delete farmer
    client.delete(f"/api/v1/farmers/{farmer_id}", headers=admin_headers)

    # 3. Post-delete: farmer and acreage must be excluded
    post_res = client.get(f"/api/v1/analytics/projects/{proj_id}", headers=officer_headers).json()
    assert post_res["total_farmers"] == 0
    assert post_res["total_acres"] == 0.0


def test_analytics_project_not_found_404(client: TestClient) -> None:
    """Verify 404 Not Found when querying non-existent project ID."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    res = client.get("/api/v1/analytics/projects/999999", headers=admin_headers)
    assert res.status_code == status.HTTP_404_NOT_FOUND


def test_analytics_role_permissions(client: TestClient) -> None:
    """Verify unauthenticated requests return 401, authenticated roles return 200."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)

    # 1. Unauthenticated -> 401
    unauth = client.get("/api/v1/analytics/summary")
    assert unauth.status_code == status.HTTP_401_UNAUTHORIZED

    # 2. Authenticated -> 200
    auth_res = client.get("/api/v1/analytics/summary", headers=admin_headers)
    assert auth_res.status_code == status.HTTP_200_OK
