"""Integration tests for Activity creation, future-date rejection, JSON details, and date-range filters."""

from datetime import date, timedelta

from fastapi import status
from fastapi.testclient import TestClient

from app.models.activity import ActivityType
from app.models.project import ProjectType
from app.models.user import UserRole


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


def _setup_enrollment(
    client: TestClient,
    officer_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> int:
    """Helper to bootstrap Farmer, Parcel, Project, and an active Enrollment, returning enrollment_id."""
    # 1. Farmer
    farmer_res = client.post(
        "/api/v1/farmers",
        json={
            "name": "Basavaraju",
            "district": "Hassan",
            "state": "Karnataka",
            "consent_given": True,
        },
        headers=officer_headers,
    )
    farmer_id = farmer_res.json()["id"]

    # 2. Parcel
    parcel_res = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 8.0, "crop": "Cardamom"},
        headers=officer_headers,
    )
    parcel_id = parcel_res.json()["id"]

    # 3. Project (Admin only)
    project_res = client.post(
        "/api/v1/projects",
        json={
            "name": "Western Ghats Agroforestry",
            "type": ProjectType.AFFORESTATION.value,
            "start_date": "2025-01-01",
        },
        headers=admin_headers,
    )
    project_id = project_res.json()["id"]

    # 4. Enrollment
    enrollment_res = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": project_id,
            "parcel_id": parcel_id,
            "farmer_id": farmer_id,
            "baseline_date": "2025-02-01",
            "status": "active",
        },
        headers=officer_headers,
    )
    return enrollment_res.json()["id"]


def test_create_activity_success(client: TestClient) -> None:
    """Verify field officer can record a planting activity with JSON details."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.act1@carbontrack.org", UserRole.FIELD_OFFICER
    )
    enrollment_id = _setup_enrollment(client, officer_headers, admin_headers)

    payload = {
        "enrollment_id": enrollment_id,
        "type": "planting",
        "activity_date": "2026-01-15",
        "details": {
            "species": ["Teak", "Rosewood"],
            "seedlings_count": 450,
            "spacing_meters": 3.0,
            "organic_fertilizer_kg": 120.5,
        },
    }
    response = client.post("/api/v1/activities", json=payload, headers=officer_headers)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["enrollment_id"] == enrollment_id
    assert data["type"] == "planting"
    assert data["activity_date"] == "2026-01-15"
    assert data["details"]["seedlings_count"] == 450
    assert "Teak" in data["details"]["species"]
    assert data["id"] is not None


def test_reject_future_activity_date_422(client: TestClient) -> None:
    """Verify activities with future dates are rejected with 422."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.act2@carbontrack.org", UserRole.FIELD_OFFICER
    )
    enrollment_id = _setup_enrollment(client, officer_headers, admin_headers)

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    payload = {
        "enrollment_id": enrollment_id,
        "type": "composting",
        "activity_date": tomorrow,
        "details": {"compost_tonnes": 5.0},
    }
    response = client.post("/api/v1/activities", json=payload, headers=officer_headers)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    error_msg = response.text
    assert (
        "cannot be in the future" in error_msg.lower() or "future" in error_msg.lower()
    )


def test_create_activity_nonexistent_enrollment_404(client: TestClient) -> None:
    """Verify recording an activity for a nonexistent enrollment returns 404."""
    officer_headers = _create_user_and_login(
        client, "officer.act3@carbontrack.org", UserRole.FIELD_OFFICER
    )

    payload = {
        "enrollment_id": 99999,
        "type": "mulching",
        "activity_date": "2026-01-10",
        "details": {"depth_cm": 4.0},
    }
    response = client.post("/api/v1/activities", json=payload, headers=officer_headers)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_activity_json_details_flexibility(client: TestClient) -> None:
    """Verify storing different schema details for different activity types in JSON column."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.act4@carbontrack.org", UserRole.FIELD_OFFICER
    )
    enrollment_id = _setup_enrollment(client, officer_headers, admin_headers)

    # 1. Cover cropping with seed rate details
    res_cover = client.post(
        "/api/v1/activities",
        json={
            "enrollment_id": enrollment_id,
            "type": "cover_cropping",
            "activity_date": "2026-01-20",
            "details": {
                "cover_crop": "Sunn hemp",
                "seed_rate_kg_per_acre": 15.0,
                "intercropped": True,
            },
        },
        headers=officer_headers,
    )
    assert res_cover.status_code == status.HTTP_201_CREATED
    act_id = res_cover.json()["id"]

    # 2. Get by ID and verify exact JSON fidelity
    get_res = client.get(f"/api/v1/activities/{act_id}", headers=officer_headers)
    assert get_res.status_code == status.HTTP_200_OK
    data = get_res.json()
    assert data["details"]["cover_crop"] == "Sunn hemp"
    assert data["details"]["seed_rate_kg_per_acre"] == 15.0
    assert data["details"]["intercropped"] is True


def test_list_activities_by_enrollment_and_type(client: TestClient) -> None:
    """Verify listing activities filtered by enrollment_id and activity type."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.act5@carbontrack.org", UserRole.FIELD_OFFICER
    )
    enrollment1_id = _setup_enrollment(client, officer_headers, admin_headers)
    enrollment2_id = _setup_enrollment(client, officer_headers, admin_headers)

    # Enrollment 1 activities
    client.post(
        "/api/v1/activities",
        json={
            "enrollment_id": enrollment1_id,
            "type": "planting",
            "activity_date": "2026-01-10",
            "details": {},
        },
        headers=officer_headers,
    )
    client.post(
        "/api/v1/activities",
        json={
            "enrollment_id": enrollment1_id,
            "type": "mulching",
            "activity_date": "2026-01-12",
            "details": {},
        },
        headers=officer_headers,
    )

    # Enrollment 2 activity
    client.post(
        "/api/v1/activities",
        json={
            "enrollment_id": enrollment2_id,
            "type": "planting",
            "activity_date": "2026-01-15",
            "details": {},
        },
        headers=officer_headers,
    )

    # Filter by enrollment1_id
    res_e1 = client.get(
        f"/api/v1/activities?enrollment_id={enrollment1_id}", headers=officer_headers
    )
    assert res_e1.status_code == status.HTTP_200_OK
    assert res_e1.json()["total"] == 2
    assert all(a["enrollment_id"] == enrollment1_id for a in res_e1.json()["items"])

    # Filter by type=mulching
    res_mulch = client.get("/api/v1/activities?type=mulching", headers=officer_headers)
    assert res_mulch.status_code == status.HTTP_200_OK
    assert res_mulch.json()["total"] == 1
    assert res_mulch.json()["items"][0]["type"] == "mulching"


def test_list_activities_date_range_filter(client: TestClient) -> None:
    """Verify date-range filtering using from_date and to_date."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.act6@carbontrack.org", UserRole.FIELD_OFFICER
    )
    enrollment_id = _setup_enrollment(client, officer_headers, admin_headers)

    # Create 3 activities across Jan, Feb, Mar
    client.post(
        "/api/v1/activities",
        json={
            "enrollment_id": enrollment_id,
            "type": "planting",
            "activity_date": "2026-01-15",
            "details": {},
        },
        headers=officer_headers,
    )
    client.post(
        "/api/v1/activities",
        json={
            "enrollment_id": enrollment_id,
            "type": "cover_cropping",
            "activity_date": "2026-02-15",
            "details": {},
        },
        headers=officer_headers,
    )
    client.post(
        "/api/v1/activities",
        json={
            "enrollment_id": enrollment_id,
            "type": "composting",
            "activity_date": "2026-03-15",
            "details": {},
        },
        headers=officer_headers,
    )

    # Filter strictly for February
    res_feb = client.get(
        f"/api/v1/activities?enrollment_id={enrollment_id}&from_date=2026-02-01&to_date=2026-02-28",
        headers=officer_headers,
    )
    assert res_feb.status_code == status.HTTP_200_OK
    assert res_feb.json()["total"] == 1
    assert res_feb.json()["items"][0]["activity_date"] == "2026-02-15"
    assert res_feb.json()["items"][0]["type"] == "cover_cropping"


def test_nested_enrollment_activities_endpoint(client: TestClient) -> None:
    """Verify nested route GET /api/v1/enrollments/{id}/activities with date filters."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.act7@carbontrack.org", UserRole.FIELD_OFFICER
    )
    enrollment_id = _setup_enrollment(client, officer_headers, admin_headers)

    client.post(
        "/api/v1/activities",
        json={
            "enrollment_id": enrollment_id,
            "type": "planting",
            "activity_date": "2026-01-05",
            "details": {},
        },
        headers=officer_headers,
    )
    client.post(
        "/api/v1/activities",
        json={
            "enrollment_id": enrollment_id,
            "type": "mulching",
            "activity_date": "2026-02-10",
            "details": {},
        },
        headers=officer_headers,
    )

    # Nested query
    nested_res = client.get(
        f"/api/v1/enrollments/{enrollment_id}/activities", headers=officer_headers
    )
    assert nested_res.status_code == status.HTTP_200_OK
    activities = nested_res.json()
    assert len(activities) == 2

    # Nested query with date filter
    filtered_res = client.get(
        f"/api/v1/enrollments/{enrollment_id}/activities?from_date=2026-02-01",
        headers=officer_headers,
    )
    assert filtered_res.status_code == status.HTTP_200_OK
    filtered_items = filtered_res.json()
    assert len(filtered_items) == 1
    assert filtered_items[0]["type"] == "mulching"

    # Missing enrollment returns 404
    missing_res = client.get(
        "/api/v1/enrollments/99999/activities", headers=officer_headers
    )
    assert missing_res.status_code == status.HTTP_404_NOT_FOUND


def test_activity_role_permissions(client: TestClient) -> None:
    """Verify RBAC: Officer can create, Verifier can read but not write, Unauthenticated gets 401."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.rbac_a@carbontrack.org", UserRole.FIELD_OFFICER
    )
    verifier_headers = _create_user_and_login(
        client, "verifier.rbac_a@carbontrack.org", UserRole.VERIFIER
    )

    enrollment_id = _setup_enrollment(client, officer_headers, admin_headers)

    # 1. Officer creates activity -> 201
    create_res = client.post(
        "/api/v1/activities",
        json={
            "enrollment_id": enrollment_id,
            "type": "composting",
            "activity_date": "2026-01-10",
            "details": {},
        },
        headers=officer_headers,
    )
    assert create_res.status_code == status.HTTP_201_CREATED
    act_id = create_res.json()["id"]

    # 2. Verifier can read -> 200
    assert (
        client.get(f"/api/v1/activities/{act_id}", headers=verifier_headers).status_code
        == status.HTTP_200_OK
    )
    assert (
        client.get(
            f"/api/v1/enrollments/{enrollment_id}/activities", headers=verifier_headers
        ).status_code
        == status.HTTP_200_OK
    )

    # 3. Verifier cannot create activity -> 403 Forbidden
    ver_create = client.post(
        "/api/v1/activities",
        json={
            "enrollment_id": enrollment_id,
            "type": "planting",
            "activity_date": "2026-01-10",
            "details": {},
        },
        headers=verifier_headers,
    )
    assert ver_create.status_code == status.HTTP_403_FORBIDDEN

    # 4. Unauthenticated gets 401
    assert client.get("/api/v1/activities").status_code == status.HTTP_401_UNAUTHORIZED


def test_update_activity_lifecycle_and_error_branches(client: TestClient) -> None:
    """Verify PATCH /api/v1/activities/{id} updates data, rejects future dates (422), and handles 404s."""
    admin_headers = _create_user_and_login(
        client, "admin.act_upd@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.act_upd@carbontrack.org", UserRole.FIELD_OFFICER
    )
    enrollment_id = _setup_enrollment(client, officer_headers, admin_headers)

    # 1. Create activity
    create_res = client.post(
        "/api/v1/activities",
        json={
            "enrollment_id": enrollment_id,
            "type": "mulching",
            "activity_date": "2026-01-10",
            "details": {"mulch_material": "straw"},
        },
        headers=officer_headers,
    )
    assert create_res.status_code == status.HTTP_201_CREATED
    act_id = create_res.json()["id"]

    # 2. Successfully patch details and date
    patch_res = client.patch(
        f"/api/v1/activities/{act_id}",
        json={
            "activity_date": "2026-01-12",
            "details": {"mulch_material": "woodchips", "layer_depth_cm": 5},
        },
        headers=officer_headers,
    )
    assert patch_res.status_code == status.HTTP_200_OK
    data = patch_res.json()
    assert data["activity_date"] == "2026-01-12"
    assert data["details"]["mulch_material"] == "woodchips"
    assert data["details"]["layer_depth_cm"] == 5

    # 3. Patching with future date returns 422
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    fut_res = client.patch(
        f"/api/v1/activities/{act_id}",
        json={"activity_date": tomorrow},
        headers=officer_headers,
    )
    assert fut_res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # 4. Patching nonexistent activity returns 404
    not_found_res = client.patch(
        "/api/v1/activities/99999",
        json={"details": {"notes": "ghost"}},
        headers=officer_headers,
    )
    assert not_found_res.status_code == status.HTTP_404_NOT_FOUND

    # 5. Getting nonexistent activity returns 404
    get_not_found = client.get("/api/v1/activities/99999", headers=officer_headers)
    assert get_not_found.status_code == status.HTTP_404_NOT_FOUND

    # 6. Test nested enrollment activities with to_date filter
    nested_res = client.get(
        f"/api/v1/enrollments/{enrollment_id}/activities?to_date=2026-01-15",
        headers=officer_headers,
    )
    assert nested_res.status_code == status.HTTP_200_OK
    assert len(nested_res.json()) >= 1
