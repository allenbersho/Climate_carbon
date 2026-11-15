"""Integration tests for Project management, lifecycle status transitions, and RBAC."""

from fastapi import status
from fastapi.testclient import TestClient

from app.models.project import ProjectStatus, ProjectType
from app.models.user import UserRole


def _create_user_and_login(
    client: TestClient, email: str, role: UserRole
) -> dict[str, str]:
    """Helper to register and login a user with a specific role, returning auth headers."""
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


def test_create_project_success(client: TestClient) -> None:
    """Verify administrator can initialize a project in DRAFT status."""
    admin_headers = _create_user_and_login(
        client, "admin1@carbontrack.org", UserRole.ADMIN
    )

    payload = {
        "name": "Cauvery Delta Afforestation",
        "type": ProjectType.AFFORESTATION.value,
        "start_date": "2026-06-01",
    }
    response = client.post("/api/v1/projects", json=payload, headers=admin_headers)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["name"] == "Cauvery Delta Afforestation"
    assert data["type"] == ProjectType.AFFORESTATION.value
    assert data["status"] == ProjectStatus.DRAFT.value
    assert data["id"] is not None


def test_get_project_by_id(client: TestClient) -> None:
    """Verify fetching an existing project by ID returns 200 OK."""
    admin_headers = _create_user_and_login(
        client, "admin2@carbontrack.org", UserRole.ADMIN
    )

    create_res = client.post(
        "/api/v1/projects",
        json={"name": "Punjab Soil Carbon", "type": ProjectType.REGEN_AG.value},
        headers=admin_headers,
    )
    project_id = create_res.json()["id"]

    get_res = client.get(f"/api/v1/projects/{project_id}", headers=admin_headers)
    assert get_res.status_code == status.HTTP_200_OK
    assert get_res.json()["name"] == "Punjab Soil Carbon"


def test_get_project_not_found(client: TestClient) -> None:
    """Verify requesting a non-existent project returns 404 Not Found."""
    admin_headers = _create_user_and_login(
        client, "admin3@carbontrack.org", UserRole.ADMIN
    )
    response = client.get("/api/v1/projects/88888", headers=admin_headers)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_list_projects_pagination_and_filters(client: TestClient) -> None:
    """Verify project list pagination, status/type filtering, and substring search."""
    admin_headers = _create_user_and_login(
        client, "admin4@carbontrack.org", UserRole.ADMIN
    )

    # Seed 3 projects
    client.post(
        "/api/v1/projects",
        json={
            "name": "Western Ghats Rewilding",
            "type": ProjectType.AFFORESTATION.value,
        },
        headers=admin_headers,
    )
    p2 = client.post(
        "/api/v1/projects",
        json={"name": "Deccan Regen Agriculture", "type": ProjectType.REGEN_AG.value},
        headers=admin_headers,
    )
    client.patch(
        f"/api/v1/projects/{p2.json()['id']}",
        json={"status": ProjectStatus.ACTIVE.value},
        headers=admin_headers,
    )
    client.post(
        "/api/v1/projects",
        json={"name": "Gujarat Agroforestry", "type": ProjectType.AFFORESTATION.value},
        headers=admin_headers,
    )

    # Test pagination
    paged_res = client.get("/api/v1/projects?page=1&page_size=2", headers=admin_headers)
    assert paged_res.status_code == status.HTTP_200_OK
    assert paged_res.json()["total"] == 3
    assert len(paged_res.json()["items"]) == 2

    # Filter by type="afforestation"
    type_res = client.get("/api/v1/projects?type=afforestation", headers=admin_headers)
    assert type_res.status_code == status.HTTP_200_OK
    assert type_res.json()["total"] == 2

    # Filter by status="active"
    status_res = client.get("/api/v1/projects?status=active", headers=admin_headers)
    assert status_res.status_code == status.HTTP_200_OK
    assert status_res.json()["total"] == 1
    assert status_res.json()["items"][0]["name"] == "Deccan Regen Agriculture"

    # Search by substring "ghats"
    search_res = client.get("/api/v1/projects?search=ghats", headers=admin_headers)
    assert search_res.status_code == status.HTTP_200_OK
    assert search_res.json()["total"] == 1


def test_status_lifecycle_transitions(client: TestClient) -> None:
    """Verify the valid status sequence: draft -> active -> closed."""
    admin_headers = _create_user_and_login(
        client, "admin5@carbontrack.org", UserRole.ADMIN
    )

    create_res = client.post(
        "/api/v1/projects",
        json={"name": "Lifecycle Test Project", "type": ProjectType.BIOCHAR.value},
        headers=admin_headers,
    )
    project_id = create_res.json()["id"]
    assert create_res.json()["status"] == ProjectStatus.DRAFT.value

    # 1. Valid: draft -> active
    to_active_res = client.patch(
        f"/api/v1/projects/{project_id}",
        json={"status": ProjectStatus.ACTIVE.value},
        headers=admin_headers,
    )
    assert to_active_res.status_code == status.HTTP_200_OK
    assert to_active_res.json()["status"] == ProjectStatus.ACTIVE.value

    # 2. Valid: active -> closed
    to_closed_res = client.patch(
        f"/api/v1/projects/{project_id}",
        json={"status": ProjectStatus.CLOSED.value},
        headers=admin_headers,
    )
    assert to_closed_res.status_code == status.HTTP_200_OK
    assert to_closed_res.json()["status"] == ProjectStatus.CLOSED.value


def test_invalid_status_transitions_rejected(client: TestClient) -> None:
    """Verify that skipping forward or skipping back is strictly rejected with 400 Bad Request."""
    admin_headers = _create_user_and_login(
        client, "admin6@carbontrack.org", UserRole.ADMIN
    )

    # 1. Rejection: Skipping directly from draft -> closed
    p1 = client.post(
        "/api/v1/projects",
        json={"name": "Skip Forward Test", "type": ProjectType.AFFORESTATION.value},
        headers=admin_headers,
    ).json()

    skip_forward_res = client.patch(
        f"/api/v1/projects/{p1['id']}",
        json={"status": ProjectStatus.CLOSED.value},
        headers=admin_headers,
    )
    assert skip_forward_res.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        "Invalid project status transition"
        in skip_forward_res.json()["error"]["message"]
    )

    # 2. Advance p1 to active
    client.patch(
        f"/api/v1/projects/{p1['id']}",
        json={"status": ProjectStatus.ACTIVE.value},
        headers=admin_headers,
    )

    # 3. Rejection: Reverting from active -> draft
    skip_back_res = client.patch(
        f"/api/v1/projects/{p1['id']}",
        json={"status": ProjectStatus.DRAFT.value},
        headers=admin_headers,
    )
    assert skip_back_res.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        "Invalid project status transition" in skip_back_res.json()["error"]["message"]
    )

    # 4. Advance to closed
    client.patch(
        f"/api/v1/projects/{p1['id']}",
        json={"status": ProjectStatus.CLOSED.value},
        headers=admin_headers,
    )

    # 5. Rejection: Reopening from closed -> active or closed -> draft
    reopen_res = client.patch(
        f"/api/v1/projects/{p1['id']}",
        json={"status": ProjectStatus.ACTIVE.value},
        headers=admin_headers,
    )
    assert reopen_res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid project status transition" in reopen_res.json()["error"]["message"]


def test_project_role_permissions(client: TestClient) -> None:
    """Verify RBAC: Only admins can create/update projects; Officers and Verifiers can read."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.proj@carbontrack.org", UserRole.FIELD_OFFICER
    )
    verifier_headers = _create_user_and_login(
        client, "verifier.proj@carbontrack.org", UserRole.VERIFIER
    )

    # 1. Admin creates project (201)
    create_res = client.post(
        "/api/v1/projects",
        json={"name": "RBAC Project", "type": ProjectType.AFFORESTATION.value},
        headers=admin_headers,
    )
    assert create_res.status_code == status.HTTP_201_CREATED
    project_id = create_res.json()["id"]

    # 2. Field officer CANNOT create project (403 Forbidden)
    officer_create = client.post(
        "/api/v1/projects",
        json={"name": "Officer Project", "type": ProjectType.REGEN_AG.value},
        headers=officer_headers,
    )
    assert officer_create.status_code == status.HTTP_403_FORBIDDEN

    # 3. Verifier CANNOT create project (403 Forbidden)
    verifier_create = client.post(
        "/api/v1/projects",
        json={"name": "Verifier Project", "type": ProjectType.BIOCHAR.value},
        headers=verifier_headers,
    )
    assert verifier_create.status_code == status.HTTP_403_FORBIDDEN

    # 4. Both Field Officer and Verifier CAN read projects (200 OK)
    assert (
        client.get(
            f"/api/v1/projects/{project_id}", headers=officer_headers
        ).status_code
        == status.HTTP_200_OK
    )
    assert (
        client.get(
            f"/api/v1/projects/{project_id}", headers=verifier_headers
        ).status_code
        == status.HTTP_200_OK
    )
    assert (
        client.get("/api/v1/projects", headers=verifier_headers).status_code
        == status.HTTP_200_OK
    )

    # 5. Field Officer CANNOT update project (403 Forbidden)
    officer_update = client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "Officer Renames"},
        headers=officer_headers,
    )
    assert officer_update.status_code == status.HTTP_403_FORBIDDEN

    # 6. Unauthenticated request gets 401
    assert client.get("/api/v1/projects").status_code == status.HTTP_401_UNAUTHORIZED
