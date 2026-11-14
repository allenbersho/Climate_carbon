"""Integration tests for Enrollment creation, duplicate active conflict rule (409), and RBAC."""

from fastapi import status
from fastapi.testclient import TestClient

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


def _setup_entities(
    client: TestClient,
    actor_headers: dict[str, str],
    admin_headers: dict[str, str],
    project_type: ProjectType = ProjectType.AFFORESTATION,
) -> tuple[int, int, int]:
    """Helper to create a farmer, parcel, and project, returning (farmer_id, parcel_id, project_id)."""
    # 1. Create Farmer (actor: officer or admin)
    farmer_res = client.post(
        "/api/v1/farmers",
        json={"name": "Ramesh Gowda", "district": "Mandya", "state": "Karnataka", "consent_given": True},
        headers=actor_headers,
    )
    farmer_id = farmer_res.json()["id"]

    # 2. Create Parcel (actor: officer or admin)
    parcel_res = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 15.0, "crop": "Ragi"},
        headers=actor_headers,
    )
    parcel_id = parcel_res.json()["id"]

    # 3. Create Project (requires admin privileges per RBAC)
    project_res = client.post(
        "/api/v1/projects",
        json={
            "name": f"Project {project_type.value.title()}",
            "type": project_type.value,
            "start_date": "2026-01-01",
        },
        headers=admin_headers,
    )
    project_id = project_res.json()["id"]

    return farmer_id, parcel_id, project_id


def test_create_enrollment_success(client: TestClient) -> None:
    """Verify field officer can create an active enrollment linking parcel to project."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.enroll1@carbontrack.org", UserRole.FIELD_OFFICER)
    farmer_id, parcel_id, project_id = _setup_entities(client, officer_headers, admin_headers)

    payload = {
        "project_id": project_id,
        "parcel_id": parcel_id,
        "farmer_id": farmer_id,
        "baseline_date": "2026-03-15",
        "status": "active",
        "additionality_note": "Farmer lacks capital for saplings without carbon finance.",
    }
    response = client.post("/api/v1/enrollments", json=payload, headers=officer_headers)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["project_id"] == project_id
    assert data["parcel_id"] == parcel_id
    assert data["farmer_id"] == farmer_id
    assert data["baseline_date"] == "2026-03-15"
    assert data["status"] == "active"
    assert "saplings" in data["additionality_note"]
    assert data["id"] is not None


def test_duplicate_active_enrollment_same_project_type_rejected_409(client: TestClient) -> None:
    """Verify Rule 2: A parcel cannot be in two ACTIVE enrollments of the same project type (409 Conflict)."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.enroll2@carbontrack.org", UserRole.FIELD_OFFICER)
    farmer_id, parcel_id, project1_id = _setup_entities(
        client, officer_headers, admin_headers, ProjectType.AFFORESTATION
    )

    # Admin creates second afforestation project
    p2_res = client.post(
        "/api/v1/projects",
        json={"name": "Cauvery Afforestation Phase 2", "type": "afforestation", "start_date": "2026-06-01"},
        headers=admin_headers,
    )
    project2_id = p2_res.json()["id"]

    # 1. First active enrollment succeeds
    res1 = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": project1_id,
            "parcel_id": parcel_id,
            "farmer_id": farmer_id,
            "status": "active",
        },
        headers=officer_headers,
    )
    assert res1.status_code == status.HTTP_201_CREATED

    # 2. Second active enrollment for SAME parcel and SAME project type must return 409 CONFLICT
    res2 = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": project2_id,
            "parcel_id": parcel_id,
            "farmer_id": farmer_id,
            "status": "active",
        },
        headers=officer_headers,
    )
    assert res2.status_code == status.HTTP_409_CONFLICT
    error = res2.json()["error"]
    assert error["code"] == "CONFLICT"
    assert "already has an active enrollment" in error["message"]


def test_active_enrollment_different_project_types_allowed(client: TestClient) -> None:
    """Verify a parcel CAN be actively enrolled in two projects if they have DIFFERENT project types."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.enroll3@carbontrack.org", UserRole.FIELD_OFFICER)
    farmer_id, parcel_id, afforestation_project_id = _setup_entities(
        client, officer_headers, admin_headers, ProjectType.AFFORESTATION
    )

    # Admin creates a regenerative agriculture project
    regen_res = client.post(
        "/api/v1/projects",
        json={"name": "Deccan Soil Regeneration", "type": "regen_ag", "start_date": "2026-01-01"},
        headers=admin_headers,
    )
    regen_project_id = regen_res.json()["id"]

    # 1. Active enrollment in Afforestation succeeds
    res1 = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": afforestation_project_id,
            "parcel_id": parcel_id,
            "farmer_id": farmer_id,
            "status": "active",
        },
        headers=officer_headers,
    )
    assert res1.status_code == status.HTTP_201_CREATED

    # 2. Active enrollment in Regen Ag on the SAME parcel ALSO succeeds
    res2 = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": regen_project_id,
            "parcel_id": parcel_id,
            "farmer_id": farmer_id,
            "status": "active",
        },
        headers=officer_headers,
    )
    assert res2.status_code == status.HTTP_201_CREATED
    assert res2.json()["status"] == "active"


def test_enrollment_after_previous_terminated_succeeds(client: TestClient) -> None:
    """Verify a parcel can be enrolled in another project of same type if prior enrollment is terminated."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.enroll4@carbontrack.org", UserRole.FIELD_OFFICER)
    farmer_id, parcel_id, project1_id = _setup_entities(
        client, officer_headers, admin_headers, ProjectType.BIOCHAR
    )

    # Project 2 (also Biochar) created by admin
    p2_res = client.post(
        "/api/v1/projects",
        json={"name": "Biochar Hub South", "type": "biochar", "start_date": "2026-05-01"},
        headers=admin_headers,
    )
    project2_id = p2_res.json()["id"]

    # First enrollment created as active
    res1 = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": project1_id,
            "parcel_id": parcel_id,
            "farmer_id": farmer_id,
            "status": "active",
        },
        headers=officer_headers,
    )
    enrollment1_id = res1.json()["id"]

    # Update first enrollment status to TERMINATED
    client.patch(
        f"/api/v1/enrollments/{enrollment1_id}",
        json={"status": "terminated"},
        headers=officer_headers,
    )

    # Now enrolling in Project 2 (Biochar) must SUCCEED because prior is terminated
    res2 = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": project2_id,
            "parcel_id": parcel_id,
            "farmer_id": farmer_id,
            "status": "active",
        },
        headers=officer_headers,
    )
    assert res2.status_code == status.HTTP_201_CREATED
    assert res2.json()["status"] == "active"


def test_update_pending_enrollment_to_active_conflict_rejected_409(client: TestClient) -> None:
    """Verify updating a pending enrollment to active triggers 409 if active conflict exists."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.enroll5@carbontrack.org", UserRole.FIELD_OFFICER)
    farmer_id, parcel_id, project1_id = _setup_entities(
        client, officer_headers, admin_headers, ProjectType.AFFORESTATION
    )

    # Project 2 of same type created by admin
    p2_res = client.post(
        "/api/v1/projects",
        json={"name": "Afforestation Beta", "type": "afforestation", "start_date": "2026-07-01"},
        headers=admin_headers,
    )
    project2_id = p2_res.json()["id"]

    # Active enrollment in Project 1
    client.post(
        "/api/v1/enrollments",
        json={"project_id": project1_id, "parcel_id": parcel_id, "farmer_id": farmer_id, "status": "active"},
        headers=officer_headers,
    )

    # Pending enrollment in Project 2 (allowed to exist as pending)
    pending_res = client.post(
        "/api/v1/enrollments",
        json={"project_id": project2_id, "parcel_id": parcel_id, "farmer_id": farmer_id, "status": "pending"},
        headers=officer_headers,
    )
    assert pending_res.status_code == status.HTTP_201_CREATED
    enrollment2_id = pending_res.json()["id"]

    # Activating enrollment 2 should fail with 409
    patch_res = client.patch(
        f"/api/v1/enrollments/{enrollment2_id}",
        json={"status": "active"},
        headers=officer_headers,
    )
    assert patch_res.status_code == status.HTTP_409_CONFLICT
    assert patch_res.json()["error"]["code"] == "CONFLICT"


def test_enrollment_validation_parcel_farmer_mismatch_422(client: TestClient) -> None:
    """Verify enrolling a parcel with a mismatched farmer_id is rejected with 422."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.enroll6@carbontrack.org", UserRole.FIELD_OFFICER)
    farmer1_id, parcel1_id, project_id = _setup_entities(client, officer_headers, admin_headers)

    # Create a second farmer
    farmer2_res = client.post(
        "/api/v1/farmers",
        json={"name": "Shantha Kumar", "district": "Shimoga", "state": "Karnataka", "consent_given": True},
        headers=officer_headers,
    )
    farmer2_id = farmer2_res.json()["id"]

    # Parcel 1 belongs to Farmer 1, but we pass farmer2_id
    response = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": project_id,
            "parcel_id": parcel1_id,
            "farmer_id": farmer2_id,
            "status": "active",
        },
        headers=officer_headers,
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "belongs to farmer" in response.json()["error"]["message"]


def test_get_and_list_enrollments(client: TestClient) -> None:
    """Verify get by id, not found, and paginated listing with filters."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.enroll7@carbontrack.org", UserRole.FIELD_OFFICER)
    farmer_id, parcel_id, project_id = _setup_entities(client, officer_headers, admin_headers)

    create_res = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": project_id,
            "parcel_id": parcel_id,
            "farmer_id": farmer_id,
            "status": "active",
            "additionality_note": "Verified baseline survey.",
        },
        headers=officer_headers,
    )
    enrollment_id = create_res.json()["id"]

    # Get by ID
    get_res = client.get(f"/api/v1/enrollments/{enrollment_id}", headers=officer_headers)
    assert get_res.status_code == status.HTTP_200_OK
    assert get_res.json()["id"] == enrollment_id

    # Not found -> 404
    assert client.get("/api/v1/enrollments/99999", headers=officer_headers).status_code == status.HTTP_404_NOT_FOUND

    # List with filters
    list_res = client.get(f"/api/v1/enrollments?project_id={project_id}&status=active", headers=officer_headers)
    assert list_res.status_code == status.HTTP_200_OK
    assert list_res.json()["total"] == 1
    assert list_res.json()["items"][0]["id"] == enrollment_id


def test_enrollment_role_permissions(client: TestClient) -> None:
    """Verify RBAC: Officer can create, Verifier can read but not write, Unauthenticated gets 401."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.rbac_e@carbontrack.org", UserRole.FIELD_OFFICER)
    verifier_headers = _create_user_and_login(client, "verifier.rbac_e@carbontrack.org", UserRole.VERIFIER)

    farmer_id, parcel_id, project_id = _setup_entities(client, admin_headers, admin_headers)

    # 1. Field officer creates enrollment -> 201
    create_res = client.post(
        "/api/v1/enrollments",
        json={"project_id": project_id, "parcel_id": parcel_id, "farmer_id": farmer_id, "status": "active"},
        headers=officer_headers,
    )
    assert create_res.status_code == status.HTTP_201_CREATED
    enrollment_id = create_res.json()["id"]

    # 2. Verifier can read -> 200
    assert client.get(f"/api/v1/enrollments/{enrollment_id}", headers=verifier_headers).status_code == status.HTTP_200_OK

    # 3. Verifier cannot create enrollment -> 403 Forbidden
    ver_create = client.post(
        "/api/v1/enrollments",
        json={"project_id": project_id, "parcel_id": parcel_id, "farmer_id": farmer_id},
        headers=verifier_headers,
    )
    assert ver_create.status_code == status.HTTP_403_FORBIDDEN

    # 4. Verifier cannot update enrollment -> 403 Forbidden
    ver_patch = client.patch(
        f"/api/v1/enrollments/{enrollment_id}",
        json={"status": "completed"},
        headers=verifier_headers,
    )
    assert ver_patch.status_code == status.HTTP_403_FORBIDDEN

    # 5. Unauthenticated request -> 401
    assert client.get("/api/v1/enrollments").status_code == status.HTTP_401_UNAUTHORIZED
