"""Integration tests for monitoring timeline analytics, change from baseline, date filters, and RBAC."""

from datetime import datetime, timezone
from fastapi import status
from fastapi.testclient import TestClient

from app.models.observation import ObservationType
from app.models.project import ProjectType
from app.models.user import UserRole


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


def _setup_enrollment_with_observations(
    client: TestClient,
    officer_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> int:
    """Helper to set up an enrollment with at least 5 observations (baseline + 4 monitoring)."""
    # 1. Farmer & Parcel
    farmer_res = client.post(
        "/api/v1/farmers",
        json={"name": "Kariyappa", "district": "Chikkamagaluru", "state": "Karnataka", "consent_given": True},
        headers=officer_headers,
    )
    farmer_id = farmer_res.json()["id"]

    parcel_res = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 12.0, "soil_type": "red_laterite", "crop": "Coffee"},
        headers=officer_headers,
    )
    parcel_id = parcel_res.json()["id"]

    # 2. Project & Enrollment
    project_res = client.post(
        "/api/v1/projects",
        json={
            "name": "Bhadra Shade Coffee Carbon",
            "type": ProjectType.REGEN_AG.value,
            "start_date": "2025-01-01",
        },
        headers=admin_headers,
    )
    project_id = project_res.json()["id"]

    enrollment_res = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": project_id,
            "parcel_id": parcel_id,
            "farmer_id": farmer_id,
            "baseline_date": "2025-01-15",
            "status": "active",
        },
        headers=officer_headers,
    )
    enrollment_id = enrollment_res.json()["id"]

    # 3. Create 5 chronological observations across 2 types (soil and tree_count)
    # Obs 1: Soil Baseline (Jan 2025)
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "soil",
            "values": {"soc_percent": 1.20, "bulk_density": 1.30, "depth_cm": 30.0},
            "observed_at": "2025-01-15T09:00:00Z",
            "is_baseline": True,
        },
        headers=officer_headers,
    )

    # Obs 2: Tree Count Baseline (Jan 2025)
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 100, "avg_height_m": 1.5},
            "observed_at": "2025-01-15T10:00:00Z",
            "is_baseline": True,
        },
        headers=officer_headers,
    )

    # Obs 3: Soil Month 6 (July 2025)
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "soil",
            "values": {"soc_percent": 1.40, "bulk_density": 1.28, "depth_cm": 30.0},
            "observed_at": "2025-07-15T09:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    )

    # Obs 4: Soil Month 12 (Jan 2026)
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "soil",
            "values": {"soc_percent": 1.55, "bulk_density": 1.26, "depth_cm": 30.0},
            "observed_at": "2026-01-15T09:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    )

    # Obs 5: Tree Count Month 12 (Jan 2026)
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 380, "avg_height_m": 3.2},
            "observed_at": "2026-01-15T11:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    )

    return enrollment_id


def test_monitoring_timeline_change_from_baseline(client: TestClient) -> None:
    """Verify GET /api/v1/monitoring/{id}/timeline returns ordered observations with delta from baseline."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.mon1@carbontrack.org", UserRole.FIELD_OFFICER)
    enrollment_id = _setup_enrollment_with_observations(client, officer_headers, admin_headers)

    response = client.get(f"/api/v1/monitoring/{enrollment_id}/timeline", headers=officer_headers)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert data["enrollment_id"] == enrollment_id
    assert data["total_observations"] == 5
    assert len(data["timeline"]) == 5
    assert "soil" in data["baseline_observations"]
    assert "tree_count" in data["baseline_observations"]

    # 1. Check chronological ordering
    timeline = data["timeline"]
    timestamps = [item["observed_at"] for item in timeline]
    assert timestamps == sorted(timestamps)

    # 2. Check Baseline Soil observation (Item 0)
    item0 = timeline[0]
    assert item0["type"] == "soil"
    assert item0["is_baseline"] is True
    assert item0["change_from_baseline"]["soc_percent"] == 0.0
    assert item0["change_from_baseline"]["bulk_density"] == 0.0

    # 3. Check Baseline Tree Count observation (Item 1)
    item1 = timeline[1]
    assert item1["type"] == "tree_count"
    assert item1["is_baseline"] is True
    assert item1["change_from_baseline"]["count"] == 0.0
    assert item1["change_from_baseline"]["avg_height_m"] == 0.0

    # 4. Check Month 6 Soil (Item 2: soc went 1.20 -> 1.40 (+0.20), bulk_density 1.30 -> 1.28 (-0.02))
    item2 = timeline[2]
    assert item2["type"] == "soil"
    assert item2["is_baseline"] is False
    assert round(item2["change_from_baseline"]["soc_percent"], 2) == 0.20
    assert round(item2["change_from_baseline"]["bulk_density"], 2) == -0.02
    assert item2["change_from_baseline"]["depth_cm"] == 0.0

    # 5. Check Month 12 Soil (Item 3: soc went 1.20 -> 1.55 (+0.35), bulk_density 1.30 -> 1.26 (-0.04))
    item3 = timeline[3]
    assert item3["type"] == "soil"
    assert round(item3["change_from_baseline"]["soc_percent"], 2) == 0.35
    assert round(item3["change_from_baseline"]["bulk_density"], 2) == -0.04

    # 6. Check Month 12 Tree Count (Item 4: count went 100 -> 380 (+280), height 1.5 -> 3.2 (+1.7))
    item4 = timeline[4]
    assert item4["type"] == "tree_count"
    assert item4["change_from_baseline"]["count"] == 280.0
    assert round(item4["change_from_baseline"]["avg_height_m"], 2) == 1.70


def test_monitoring_timeline_date_range_filter(client: TestClient) -> None:
    """Verify date-range filtering works while retaining delta calculation against the baseline."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.mon2@carbontrack.org", UserRole.FIELD_OFFICER)
    enrollment_id = _setup_enrollment_with_observations(client, officer_headers, admin_headers)

    # Filter strictly for July 2025 (excludes January 2025 baseline and January 2026 follow-ups)
    url = f"/api/v1/monitoring/{enrollment_id}/timeline?from_date=2025-07-01T00:00:00Z&to_date=2025-07-31T23:59:59Z"
    response = client.get(url, headers=officer_headers)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    # Only 1 observation falls in July 2025
    assert data["total_observations"] == 1
    assert len(data["timeline"]) == 1
    item = data["timeline"][0]
    assert item["type"] == "soil"
    assert "2025-07-15" in item["observed_at"]

    # Even though baseline is outside the date range, delta is still computed correctly!
    assert round(item["change_from_baseline"]["soc_percent"], 2) == 0.20
    assert round(item["change_from_baseline"]["bulk_density"], 2) == -0.02


def test_monitoring_timeline_type_filter(client: TestClient) -> None:
    """Verify filtering timeline by observation type (e.g. type=tree_count)."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.mon3@carbontrack.org", UserRole.FIELD_OFFICER)
    enrollment_id = _setup_enrollment_with_observations(client, officer_headers, admin_headers)

    url = f"/api/v1/monitoring/{enrollment_id}/timeline?type=tree_count"
    response = client.get(url, headers=officer_headers)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert data["total_observations"] == 2
    assert all(item["type"] == "tree_count" for item in data["timeline"])
    assert data["timeline"][0]["is_baseline"] is True
    assert data["timeline"][1]["is_baseline"] is False
    assert data["timeline"][1]["change_from_baseline"]["count"] == 280.0


def test_monitoring_timeline_superseded_observation_handling(client: TestClient) -> None:
    """Verify that by default superseded observations are excluded, and active replacement is used for delta."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.mon4@carbontrack.org", UserRole.FIELD_OFFICER)
    enrollment_id = _setup_enrollment_with_observations(client, officer_headers, admin_headers)

    # 1. Fetch initial timeline to get the Month 6 observation ID
    init_res = client.get(f"/api/v1/monitoring/{enrollment_id}/timeline", headers=officer_headers)
    month6_obs_id = init_res.json()["timeline"][2]["id"]

    # 2. Supersede Month 6 observation with corrected SOC (1.45 instead of 1.40)
    correction_payload = {
        "values": {"soc_percent": 1.45, "bulk_density": 1.28, "depth_cm": 30.0},
        "observed_at": "2025-07-15T09:00:00Z",
    }
    client.post(
        f"/api/v1/observations/{month6_obs_id}/supersede",
        json=correction_payload,
        headers=officer_headers,
    )

    # 3. Default timeline (include_superseded=False) contains only active rows (total remains 5)
    active_res = client.get(f"/api/v1/monitoring/{enrollment_id}/timeline", headers=officer_headers)
    assert active_res.status_code == status.HTTP_200_OK
    active_data = active_res.json()
    assert active_data["total_observations"] == 5
    # The active July observation has the corrected SOC and delta +0.25 (1.45 - 1.20)
    item2 = active_data["timeline"][2]
    assert item2["values"]["soc_percent"] == 1.45
    assert round(item2["change_from_baseline"]["soc_percent"], 2) == 0.25
    assert item2["is_superseded"] is False

    # 4. include_superseded=True shows 6 items (including the old row with is_superseded=True)
    full_res = client.get(f"/api/v1/monitoring/{enrollment_id}/timeline?include_superseded=true", headers=officer_headers)
    assert full_res.status_code == status.HTTP_200_OK
    full_data = full_res.json()
    assert full_data["total_observations"] == 6
    superseded_items = [i for i in full_data["timeline"] if i["is_superseded"]]
    assert len(superseded_items) == 1
    assert superseded_items[0]["id"] == month6_obs_id


def test_monitoring_timeline_nonexistent_enrollment_404(client: TestClient) -> None:
    """Verify requesting timeline for nonexistent enrollment returns 404."""
    officer_headers = _create_user_and_login(client, "officer.mon5@carbontrack.org", UserRole.FIELD_OFFICER)
    response = client.get("/api/v1/monitoring/99999/timeline", headers=officer_headers)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_monitoring_timeline_role_permissions(client: TestClient) -> None:
    """Verify RBAC: Admin, Officer, and Verifier can all view timeline; Unauthenticated gets 401."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.rbac_mon@carbontrack.org", UserRole.FIELD_OFFICER)
    verifier_headers = _create_user_and_login(client, "verifier.rbac_mon@carbontrack.org", UserRole.VERIFIER)
    enrollment_id = _setup_enrollment_with_observations(client, officer_headers, admin_headers)

    url = f"/api/v1/monitoring/{enrollment_id}/timeline"

    # Admin: 200
    assert client.get(url, headers=admin_headers).status_code == status.HTTP_200_OK
    # Officer: 200
    assert client.get(url, headers=officer_headers).status_code == status.HTTP_200_OK
    # Verifier: 200
    assert client.get(url, headers=verifier_headers).status_code == status.HTTP_200_OK
    # Unauthenticated: 401
    assert client.get(url).status_code == status.HTTP_401_UNAUTHORIZED
