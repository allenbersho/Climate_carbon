"""Integration tests for Analytics reporting summaries, SQL GROUP BY aggregations,

and per-project analytics.
"""

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import UserRole
from app.services.methodology_service import seed_default_methodologies


def _create_user_and_login(
    client: TestClient, email: str, role: UserRole
) -> dict[str, str]:
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
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )

    res = client.get("/api/v1/analytics/summary", headers=admin_headers)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["total_farmers"] == 0
    assert data["total_acres"] == 0.0
    assert data["total_co2e"] == 0.0
    assert data["total_net_credits"] == 0.0
    assert data["by_district"] == []


def test_portfolio_and_project_analytics_sql_aggregation(
    client: TestClient, db_session: Session
) -> None:
    """Verify SQL GROUP BY aggregations across multiple districts, projects, and farmers."""
    seed_default_methodologies(db_session)
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.ana1@carbontrack.org", UserRole.FIELD_OFFICER
    )
    verifier_headers = _create_user_and_login(
        client, "verifier.ana1@carbontrack.org", UserRole.VERIFIER
    )

    # 1. Create Projects
    proj1 = client.post(
        "/api/v1/projects",
        json={
            "name": "Mandya Regen Ag",
            "type": "regen_ag",
            "start_date": "2025-01-01",
        },
        headers=admin_headers,
    ).json()
    proj1_id = proj1["id"]

    proj2 = client.post(
        "/api/v1/projects",
        json={
            "name": "Uttara Afforestation",
            "type": "afforestation",
            "start_date": "2025-01-01",
        },
        headers=admin_headers,
    ).json()
    proj2_id = proj2["id"]

    # 2. Setup Farmer 1 in Mandya (10 acres, Regen Ag)
    f1_id = client.post(
        "/api/v1/farmers",
        json={
            "name": "Boregowda",
            "district": "Mandya",
            "state": "Karnataka",
            "consent_given": True,
        },
        headers=officer_headers,
    ).json()["id"]
    p1_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": f1_id, "area_acres": 10.0},
        headers=officer_headers,
    ).json()["id"]
    e1_id = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": proj1_id,
            "parcel_id": p1_id,
            "farmer_id": f1_id,
            "status": "active",
        },
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
    client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": e1_id},
        headers=verifier_headers,
    )

    # 3. Setup Farmer 2 in Mandya (5 acres, Regen Ag, no estimate yet)
    f2_id = client.post(
        "/api/v1/farmers",
        json={
            "name": "Thimmegowda",
            "district": "Mandya",
            "state": "Karnataka",
            "consent_given": True,
        },
        headers=officer_headers,
    ).json()["id"]
    p2_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": f2_id, "area_acres": 5.0},
        headers=officer_headers,
    ).json()["id"]
    client.post(
        "/api/v1/enrollments",
        json={
            "project_id": proj1_id,
            "parcel_id": p2_id,
            "farmer_id": f2_id,
            "status": "active",
        },
        headers=officer_headers,
    )

    # 4. Setup Farmer 3 in Uttara Kannada (8 acres, Afforestation)
    f3_id = client.post(
        "/api/v1/farmers",
        json={
            "name": "Hegde",
            "district": "Uttara Kannada",
            "state": "Karnataka",
            "consent_given": True,
        },
        headers=officer_headers,
    ).json()["id"]
    p3_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": f3_id, "area_acres": 8.0},
        headers=officer_headers,
    ).json()["id"]
    e3_id = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": proj2_id,
            "parcel_id": p3_id,
            "farmer_id": f3_id,
            "status": "active",
        },
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
    client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": e3_id},
        headers=verifier_headers,
    )

    # -------------------------------------------------------------
    # 5. Verify Portfolio-Wide Analytics (GET /api/v1/analytics/summary)
    # -------------------------------------------------------------
    summary_res = client.get("/api/v1/analytics/summary", headers=officer_headers)
    assert summary_res.status_code == status.HTTP_200_OK
    summary = summary_res.json()

    assert summary["total_farmers"] == 3
    assert summary["total_acres"] == pytest.approx(23.0, abs=1e-4)  # 10 + 5 + 8
    expected_total_credits = 133.191468 + 32.95905
    assert summary["total_net_credits"] == pytest.approx(
        expected_total_credits, abs=1e-3
    )

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
    p1_res = client.get(
        f"/api/v1/analytics/projects/{proj1_id}", headers=officer_headers
    )
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

    p2_res = client.get(
        f"/api/v1/analytics/projects/{proj2_id}", headers=officer_headers
    )
    assert p2_res.status_code == status.HTTP_200_OK
    p2_data = p2_res.json()
    assert p2_data["total_farmers"] == 1
    assert p2_data["total_acres"] == pytest.approx(8.0, abs=1e-4)
    assert p2_data["total_net_credits"] == pytest.approx(32.95905, abs=1e-3)


def test_soft_deleted_farmers_excluded_from_analytics(client: TestClient) -> None:
    """Verify that soft-deleted farmers are excluded from analytics aggregates."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.ana2@carbontrack.org", UserRole.FIELD_OFFICER
    )

    proj_id = client.post(
        "/api/v1/projects",
        json={
            "name": "Soft Delete Project",
            "type": "regen_ag",
            "start_date": "2025-01-01",
        },
        headers=admin_headers,
    ).json()["id"]

    farmer_id = client.post(
        "/api/v1/farmers",
        json={
            "name": "Gowdappa",
            "district": "Mysuru",
            "state": "Karnataka",
            "consent_given": True,
        },
        headers=officer_headers,
    ).json()["id"]

    parcel_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 25.0},
        headers=officer_headers,
    ).json()["id"]

    client.post(
        "/api/v1/enrollments",
        json={
            "project_id": proj_id,
            "parcel_id": parcel_id,
            "farmer_id": farmer_id,
            "status": "active",
        },
        headers=officer_headers,
    )

    # 1. Active: 1 farmer, 25 acres
    active_res = client.get("/api/v1/analytics/summary", headers=officer_headers).json()
    assert active_res["total_farmers"] >= 1

    # 2. Soft-delete farmer
    client.delete(f"/api/v1/farmers/{farmer_id}", headers=admin_headers)

    # 3. Post-delete: farmer and acreage must be excluded
    post_res = client.get(
        f"/api/v1/analytics/projects/{proj_id}", headers=officer_headers
    ).json()
    assert post_res["total_farmers"] == 0
    assert post_res["total_acres"] == 0.0


def test_analytics_project_not_found_404(client: TestClient) -> None:
    """Verify 404 Not Found when querying non-existent project ID."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    res = client.get("/api/v1/analytics/projects/999999", headers=admin_headers)
    assert res.status_code == status.HTTP_404_NOT_FOUND


def test_analytics_role_permissions(client: TestClient) -> None:
    """Verify unauthenticated requests return 401, authenticated roles return 200."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )

    # 1. Unauthenticated -> 401
    unauth = client.get("/api/v1/analytics/summary")
    assert unauth.status_code == status.HTTP_401_UNAUTHORIZED

    # 2. Authenticated -> 200
    auth_res = client.get("/api/v1/analytics/summary", headers=admin_headers)
    assert auth_res.status_code == status.HTTP_200_OK


def test_carbon_timeseries_window_function_and_csv_export(
    client: TestClient, db_session: Session
) -> None:
    """Verify SQL window function running cumulative sums and CSV audit export."""
    import csv
    import io

    seed_default_methodologies(db_session)
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.ts@carbontrack.org", UserRole.FIELD_OFFICER
    )
    verifier_headers = _create_user_and_login(
        client, "verifier.ts@carbontrack.org", UserRole.VERIFIER
    )

    # 1. Create two projects
    p1 = client.post(
        "/api/v1/projects",
        json={
            "name": "Tumkur Agroforestry",
            "type": "afforestation",
            "start_date": "2025-01-01",
        },
        headers=admin_headers,
    ).json()
    p1_id = p1["id"]

    p2 = client.post(
        "/api/v1/projects",
        json={
            "name": "Hassan Soil Initiative",
            "type": "regen_ag",
            "start_date": "2025-01-01",
        },
        headers=admin_headers,
    ).json()
    p2_id = p2["id"]

    # 2. Setup Farmer and 2 Enrollments in Project 1
    f1_id = client.post(
        "/api/v1/farmers",
        json={
            "name": "Ramegowda",
            "district": "Tumkur",
            "state": "Karnataka",
            "consent_given": True,
        },
        headers=officer_headers,
    ).json()["id"]

    par1_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": f1_id, "area_acres": 12.0},
        headers=officer_headers,
    ).json()["id"]

    par2_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": f1_id, "area_acres": 6.0},
        headers=officer_headers,
    ).json()["id"]

    e1_id = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": p1_id,
            "parcel_id": par1_id,
            "farmer_id": f1_id,
            "status": "active",
        },
        headers=officer_headers,
    ).json()["id"]

    e2_id = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": p1_id,
            "parcel_id": par2_id,
            "farmer_id": f1_id,
            "status": "active",
        },
        headers=officer_headers,
    ).json()["id"]

    # Observations & Estimate for E1 (Afforestation)
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": e1_id,
            "type": "tree_count",
            "values": {"count": 100, "avg_height_m": 1.0},
            "observed_at": "2025-01-01T10:00:00Z",
            "is_baseline": True,
        },
        headers=officer_headers,
    )
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": e1_id,
            "type": "tree_count",
            "values": {"count": 400, "avg_height_m": 2.0},
            "observed_at": "2025-06-01T10:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    )
    est1 = client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": e1_id},
        headers=verifier_headers,
    ).json()

    # Observations & Estimate for E2 (Afforestation)
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": e2_id,
            "type": "tree_count",
            "values": {"count": 50, "avg_height_m": 1.0},
            "observed_at": "2025-01-01T10:00:00Z",
            "is_baseline": True,
        },
        headers=officer_headers,
    )
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": e2_id,
            "type": "tree_count",
            "values": {"count": 250, "avg_height_m": 2.0},
            "observed_at": "2025-06-01T10:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    )
    est2 = client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": e2_id},
        headers=verifier_headers,
    ).json()

    # 3. Setup Farmer and 1 Enrollment in Project 2 (Soil Carbon)
    f2_id = client.post(
        "/api/v1/farmers",
        json={
            "name": "Ningamma",
            "district": "Hassan",
            "state": "Karnataka",
            "consent_given": True,
        },
        headers=officer_headers,
    ).json()["id"]

    par3_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": f2_id, "area_acres": 8.0},
        headers=officer_headers,
    ).json()["id"]

    e3_id = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": p2_id,
            "parcel_id": par3_id,
            "farmer_id": f2_id,
            "status": "active",
        },
        headers=officer_headers,
    ).json()["id"]

    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": e3_id,
            "type": "soil",
            "values": {"soc_percent": 1.0, "bulk_density": 1.30, "depth_cm": 30.0},
            "observed_at": "2025-01-01T10:00:00Z",
            "is_baseline": True,
        },
        headers=officer_headers,
    )
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": e3_id,
            "type": "soil",
            "values": {"soc_percent": 1.5, "bulk_density": 1.25, "depth_cm": 30.0},
            "observed_at": "2025-06-01T10:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    )
    est3 = client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": e3_id},
        headers=verifier_headers,
    ).json()

    # -------------------------------------------------------------
    # 4. Test Time Series Window Function (Portfolio-Wide)
    # -------------------------------------------------------------
    ts_res = client.get("/api/v1/analytics/timeseries", headers=officer_headers)
    assert ts_res.status_code == status.HTTP_200_OK
    ts_data = ts_res.json()
    assert ts_data["total_points"] == 3
    points = ts_data["points"]

    # Verify cumulative totals match running sum calculated via SQL window function
    running_co2e = 0.0
    running_credits = 0.0
    for pt in points:
        running_co2e += pt["co2e_tonnes"]
        running_credits += pt["net_credits"]
        assert pt["cumulative_co2e"] == pytest.approx(running_co2e, abs=1e-3)
        assert pt["cumulative_net_credits"] == pytest.approx(running_credits, abs=1e-3)

    # -------------------------------------------------------------
    # 5. Test Time Series Scoped to Project 1
    # -------------------------------------------------------------
    p1_ts_res = client.get(
        f"/api/v1/analytics/timeseries?project_id={p1_id}", headers=officer_headers
    )
    assert p1_ts_res.status_code == status.HTTP_200_OK
    p1_ts = p1_ts_res.json()
    assert p1_ts["project_id"] == p1_id
    assert p1_ts["total_points"] == 2
    for pt in p1_ts["points"]:
        assert pt["enrollment_id"] in [e1_id, e2_id]

    # -------------------------------------------------------------
    # 6. Test CSV Export (Portfolio-wide)
    # -------------------------------------------------------------
    csv_res = client.get("/api/v1/analytics/export/csv", headers=verifier_headers)
    assert csv_res.status_code == status.HTTP_200_OK
    assert "text/csv" in csv_res.headers["content-type"]
    assert (
        'attachment; filename="carbon_estimates_portfolio.csv"'
        in csv_res.headers["content-disposition"]
    )

    reader = list(csv.reader(io.StringIO(csv_res.text)))
    assert len(reader) == 4  # Header + 3 data rows
    headers = reader[0]
    assert headers[0] == "Estimate ID"
    assert "Gross CO2e (Tonnes)" in headers
    assert "Net Credits (Tonnes CO2e)" in headers
    assert "Methodology" in headers

    # -------------------------------------------------------------
    # 7. Test CSV Export Scoped to Project 2
    # -------------------------------------------------------------
    p2_csv_res = client.get(
        f"/api/v1/analytics/export/csv?project_id={p2_id}", headers=verifier_headers
    )
    assert p2_csv_res.status_code == status.HTTP_200_OK
    assert (
        f'attachment; filename="carbon_estimates_project_{p2_id}.csv"'
        in p2_csv_res.headers["content-disposition"]
    )
    p2_reader = list(csv.reader(io.StringIO(p2_csv_res.text)))
    assert len(p2_reader) == 2  # Header + 1 row
    assert p2_reader[1][2] == str(p2_id)  # Project ID column


def test_timeseries_and_csv_project_not_found_404(client: TestClient) -> None:
    """Verify 404 response when querying timeseries or CSV for non-existent project."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )

    ts_res = client.get(
        "/api/v1/analytics/timeseries?project_id=999999", headers=admin_headers
    )
    assert ts_res.status_code == status.HTTP_404_NOT_FOUND

    csv_res = client.get(
        "/api/v1/analytics/export/csv?project_id=999999", headers=admin_headers
    )
    assert csv_res.status_code == status.HTTP_404_NOT_FOUND
