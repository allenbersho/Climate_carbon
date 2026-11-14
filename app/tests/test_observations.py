"""Integration tests for Observation models, polymorphic values validation, append-only superseding, and RBAC."""

from datetime import datetime, timedelta, timezone
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


def _setup_enrollment(
    client: TestClient,
    officer_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> int:
    """Helper to bootstrap Farmer, Parcel, Project, and an active Enrollment, returning enrollment_id."""
    farmer_res = client.post(
        "/api/v1/farmers",
        json={"name": "Devendrappa", "district": "Shimoga", "state": "Karnataka", "consent_given": True},
        headers=officer_headers,
    )
    farmer_id = farmer_res.json()["id"]

    parcel_res = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 10.0, "soil_type": "clay_loam", "crop": "Arecanut"},
        headers=officer_headers,
    )
    parcel_id = parcel_res.json()["id"]

    project_res = client.post(
        "/api/v1/projects",
        json={
            "name": "Malnad Regenerative Soil",
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
    return enrollment_res.json()["id"]


def test_create_soil_observation_success(client: TestClient) -> None:
    """Verify field officer can record a valid soil observation."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.obs1@carbontrack.org", UserRole.FIELD_OFFICER)
    enrollment_id = _setup_enrollment(client, officer_headers, admin_headers)

    payload = {
        "enrollment_id": enrollment_id,
        "type": "soil",
        "values": {
            "soc_percent": 1.45,
            "bulk_density": 1.28,
            "depth_cm": 30.0,
        },
        "observed_at": "2026-01-20T10:00:00Z",
        "is_baseline": True,
    }
    response = client.post("/api/v1/observations", json=payload, headers=officer_headers)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["enrollment_id"] == enrollment_id
    assert data["type"] == "soil"
    assert data["values"]["soc_percent"] == 1.45
    assert data["values"]["bulk_density"] == 1.28
    assert data["values"]["depth_cm"] == 30.0
    assert data["is_baseline"] is True
    assert data["superseded_by"] is None
    assert data["id"] is not None


def test_create_tree_count_observation_success(client: TestClient) -> None:
    """Verify field officer can record a valid tree_count observation."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.obs2@carbontrack.org", UserRole.FIELD_OFFICER)
    enrollment_id = _setup_enrollment(client, officer_headers, admin_headers)

    payload = {
        "enrollment_id": enrollment_id,
        "type": "tree_count",
        "values": {
            "count": 420,
            "avg_height_m": 3.75,
        },
        "observed_at": "2026-02-10T14:30:00Z",
        "is_baseline": False,
    }
    response = client.post("/api/v1/observations", json=payload, headers=officer_headers)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["type"] == "tree_count"
    assert data["values"]["count"] == 420
    assert data["values"]["avg_height_m"] == 3.75
    assert data["is_baseline"] is False


def test_reject_invalid_observation_values_shape_422(client: TestClient) -> None:
    """Verify invalid JSON shapes for soil and tree_count types are rejected with 422."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.obs3@carbontrack.org", UserRole.FIELD_OFFICER)
    enrollment_id = _setup_enrollment(client, officer_headers, admin_headers)

    # 1. Soil missing bulk_density
    bad_soil_1 = {
        "enrollment_id": enrollment_id,
        "type": "soil",
        "values": {"soc_percent": 1.2, "depth_cm": 30.0},  # missing bulk_density
        "observed_at": "2026-01-10T10:00:00Z",
    }
    res_b1 = client.post("/api/v1/observations", json=bad_soil_1, headers=officer_headers)
    assert res_b1.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # 2. Soil with negative depth
    bad_soil_2 = {
        "enrollment_id": enrollment_id,
        "type": "soil",
        "values": {"soc_percent": 1.2, "bulk_density": 1.3, "depth_cm": -5.0},
        "observed_at": "2026-01-10T10:00:00Z",
    }
    res_b2 = client.post("/api/v1/observations", json=bad_soil_2, headers=officer_headers)
    assert res_b2.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # 3. Tree count missing avg_height_m
    bad_tree = {
        "enrollment_id": enrollment_id,
        "type": "tree_count",
        "values": {"count": 100},  # missing avg_height_m
        "observed_at": "2026-01-10T10:00:00Z",
    }
    res_b3 = client.post("/api/v1/observations", json=bad_tree, headers=officer_headers)
    assert res_b3.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_reject_future_observed_at_422(client: TestClient) -> None:
    """Verify observations with future timestamps are rejected with 422."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.obs4@carbontrack.org", UserRole.FIELD_OFFICER)
    enrollment_id = _setup_enrollment(client, officer_headers, admin_headers)

    future_time = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    payload = {
        "enrollment_id": enrollment_id,
        "type": "soil",
        "values": {"soc_percent": 1.5, "bulk_density": 1.2, "depth_cm": 20.0},
        "observed_at": future_time,
    }
    response = client.post("/api/v1/observations", json=payload, headers=officer_headers)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "cannot be in the future" in response.text.lower() or "future" in response.text.lower()


def test_observations_cannot_be_updated_or_deleted_405(client: TestClient) -> None:
    """Verify Rule 1: Observations can NEVER be updated or deleted via API (returns 405 Method Not Allowed)."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.obs5@carbontrack.org", UserRole.FIELD_OFFICER)
    enrollment_id = _setup_enrollment(client, officer_headers, admin_headers)

    create_res = client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "soil",
            "values": {"soc_percent": 1.5, "bulk_density": 1.2, "depth_cm": 20.0},
            "observed_at": "2026-01-10T10:00:00Z",
        },
        headers=officer_headers,
    )
    obs_id = create_res.json()["id"]

    # PUT returns 405
    put_res = client.put(f"/api/v1/observations/{obs_id}", json={}, headers=officer_headers)
    assert put_res.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # PATCH returns 405
    patch_res = client.patch(f"/api/v1/observations/{obs_id}", json={}, headers=officer_headers)
    assert patch_res.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # DELETE returns 405
    del_res = client.delete(f"/api/v1/observations/{obs_id}", headers=admin_headers)
    assert del_res.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


def test_supersede_observation_append_only_correction(client: TestClient) -> None:
    """Verify correcting an observation creates a new row and updates superseded_by on the old row."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.obs6@carbontrack.org", UserRole.FIELD_OFFICER)
    enrollment_id = _setup_enrollment(client, officer_headers, admin_headers)

    # 1. Create original observation
    orig_res = client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "soil",
            "values": {"soc_percent": 1.10, "bulk_density": 1.20, "depth_cm": 30.0},
            "observed_at": "2026-01-10T10:00:00Z",
            "is_baseline": True,
        },
        headers=officer_headers,
    )
    orig_id = orig_res.json()["id"]
    assert orig_res.json()["superseded_by"] is None

    # 2. Lab re-test indicates SOC was actually 1.35. Submit correction via /supersede
    correction_payload = {
        "values": {"soc_percent": 1.35, "bulk_density": 1.22, "depth_cm": 30.0},
        "observed_at": "2026-01-10T10:00:00Z",
    }
    supersede_res = client.post(
        f"/api/v1/observations/{orig_id}/supersede",
        json=correction_payload,
        headers=officer_headers,
    )
    assert supersede_res.status_code == status.HTTP_201_CREATED
    new_obs = supersede_res.json()
    new_id = new_obs["id"]
    assert new_id != orig_id
    assert new_obs["values"]["soc_percent"] == 1.35
    assert new_obs["superseded_by"] is None
    assert new_obs["is_baseline"] is True  # inherited from original

    # 3. Verify original observation now records superseded_by pointing to new_id
    orig_updated = client.get(f"/api/v1/observations/{orig_id}", headers=officer_headers).json()
    assert orig_updated["superseded_by"] == new_id

    # 4. Attempting to supersede the original row AGAIN fails with 409 Conflict
    second_supersede = client.post(
        f"/api/v1/observations/{orig_id}/supersede",
        json=correction_payload,
        headers=officer_headers,
    )
    assert second_supersede.status_code == status.HTTP_409_CONFLICT
    assert second_supersede.json()["error"]["code"] == "CONFLICT"


def test_list_observations_active_only_filter(client: TestClient) -> None:
    """Verify active_only=True returns only non-superseded observations, while active_only=False returns full lineage."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.obs7@carbontrack.org", UserRole.FIELD_OFFICER)
    enrollment_id = _setup_enrollment(client, officer_headers, admin_headers)

    # Observation 1: created then superseded
    res1 = client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "soil",
            "values": {"soc_percent": 1.0, "bulk_density": 1.2, "depth_cm": 30.0},
            "observed_at": "2026-01-05T10:00:00Z",
        },
        headers=officer_headers,
    )
    obs1_id = res1.json()["id"]

    # Supersede Observation 1
    client.post(
        f"/api/v1/observations/{obs1_id}/supersede",
        json={
            "values": {"soc_percent": 1.15, "bulk_density": 1.2, "depth_cm": 30.0},
            "observed_at": "2026-01-05T10:00:00Z",
        },
        headers=officer_headers,
    )

    # Observation 2: active, not superseded
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 250, "avg_height_m": 2.5},
            "observed_at": "2026-02-01T10:00:00Z",
        },
        headers=officer_headers,
    )

    # Total rows in DB is 3 (obs1, obs1_replacement, obs2)
    full_list = client.get(f"/api/v1/observations?enrollment_id={enrollment_id}&active_only=false", headers=officer_headers)
    assert full_list.status_code == status.HTTP_200_OK
    assert full_list.json()["total"] == 3

    # active_only=True returns only 2 (obs1_replacement, obs2)
    active_list = client.get(f"/api/v1/observations?enrollment_id={enrollment_id}&active_only=true", headers=officer_headers)
    assert active_list.status_code == status.HTTP_200_OK
    assert active_list.json()["total"] == 2
    assert all(o["superseded_by"] is None for o in active_list.json()["items"])


def test_nested_enrollment_observations_endpoint(client: TestClient) -> None:
    """Verify nested route GET /api/v1/enrollments/{id}/observations."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.obs8@carbontrack.org", UserRole.FIELD_OFFICER)
    enrollment_id = _setup_enrollment(client, officer_headers, admin_headers)

    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "soil",
            "values": {"soc_percent": 1.5, "bulk_density": 1.2, "depth_cm": 30.0},
            "observed_at": "2026-01-10T10:00:00Z",
        },
        headers=officer_headers,
    )

    nested_res = client.get(f"/api/v1/enrollments/{enrollment_id}/observations", headers=officer_headers)
    assert nested_res.status_code == status.HTTP_200_OK
    assert len(nested_res.json()) == 1

    # Missing enrollment returns 404
    missing_res = client.get("/api/v1/enrollments/99999/observations", headers=officer_headers)
    assert missing_res.status_code == status.HTTP_404_NOT_FOUND


def test_observation_role_permissions(client: TestClient) -> None:
    """Verify RBAC: Officer can create and supersede, Verifier can read but not write, Unauthenticated gets 401."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.rbac_obs@carbontrack.org", UserRole.FIELD_OFFICER)
    verifier_headers = _create_user_and_login(client, "verifier.rbac_obs@carbontrack.org", UserRole.VERIFIER)
    enrollment_id = _setup_enrollment(client, officer_headers, admin_headers)

    # 1. Officer creates observation -> 201
    create_res = client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 100, "avg_height_m": 2.0},
            "observed_at": "2026-01-15T10:00:00Z",
        },
        headers=officer_headers,
    )
    assert create_res.status_code == status.HTTP_201_CREATED
    obs_id = create_res.json()["id"]

    # 2. Verifier can read -> 200
    assert client.get(f"/api/v1/observations/{obs_id}", headers=verifier_headers).status_code == status.HTTP_200_OK
    assert client.get(f"/api/v1/enrollments/{enrollment_id}/observations", headers=verifier_headers).status_code == status.HTTP_200_OK

    # 3. Verifier cannot create observation -> 403 Forbidden
    ver_create = client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 100, "avg_height_m": 2.0},
            "observed_at": "2026-01-15T10:00:00Z",
        },
        headers=verifier_headers,
    )
    assert ver_create.status_code == status.HTTP_403_FORBIDDEN

    # 4. Verifier cannot supersede observation -> 403 Forbidden
    ver_supersede = client.post(
        f"/api/v1/observations/{obs_id}/supersede",
        json={"values": {"count": 110, "avg_height_m": 2.1}, "observed_at": "2026-01-15T10:00:00Z"},
        headers=verifier_headers,
    )
    assert ver_supersede.status_code == status.HTTP_403_FORBIDDEN

    # 5. Unauthenticated gets 401
    assert client.get("/api/v1/observations").status_code == status.HTTP_401_UNAUTHORIZED
