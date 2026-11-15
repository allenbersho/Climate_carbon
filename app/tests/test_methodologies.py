"""Integration tests for Methodology models, parameter seeds, and REST API endpoints."""

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import UserRole
from app.schemas.methodology import MethodologyCreate
from app.services import methodology_service
from app.services.methodology_service import (
    MethodologyAlreadyExistsError,
    seed_default_methodologies,
)


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


def test_seed_default_methodologies_idempotency(db_session: Session) -> None:
    """Verify default methodologies are seeded with required parameters and idempotently."""
    # Run seed initial time
    seeded_1 = seed_default_methodologies(db_session)
    assert len(seeded_1) >= 2

    afforestation = next(
        (m for m in seeded_1 if m.name == "Afforestation" and m.version == "v1"), None
    )
    assert afforestation is not None
    assert afforestation.is_active is True
    assert afforestation.parameters["carbon_fraction"] == 0.47
    assert afforestation.parameters["co2_to_c_ratio"] == 3.6667
    assert afforestation.parameters["default_biomass_per_tree_kg"] == 50.0
    assert afforestation.parameters["default_uncertainty_pct"] == 0.10
    assert afforestation.parameters["default_buffer_pct"] == 0.15

    soil_carbon = next(
        (m for m in seeded_1 if m.name == "Soil Carbon" and m.version == "v1"), None
    )
    assert soil_carbon is not None
    assert soil_carbon.is_active is True
    assert soil_carbon.parameters["co2_to_c_ratio"] == 3.6667
    assert soil_carbon.parameters["acres_to_hectares"] == 0.404686
    assert soil_carbon.parameters["depth_cm"] == 30.0
    assert soil_carbon.parameters["default_uncertainty_pct"] == 0.15
    assert soil_carbon.parameters["default_buffer_pct"] == 0.20

    # Run seed second time to confirm idempotency (no duplicate rows created)
    seeded_2 = seed_default_methodologies(db_session)
    assert len(seeded_2) == len(seeded_1)
    assert {m.id for m in seeded_2} == {m.id for m in seeded_1}


def test_methodology_unique_constraint(db_session: Session) -> None:
    """Verify creating a duplicate (name, version) raises MethodologyAlreadyExistsError."""
    seed_default_methodologies(db_session)

    with pytest.raises(MethodologyAlreadyExistsError):
        methodology_service.create_methodology(
            db_session,
            MethodologyCreate(
                name="Afforestation",
                version="v1",
                parameters={"some_key": 123},
            ),
        )


def test_create_methodology_endpoint_admin_only(client: TestClient) -> None:
    """Verify only admin can create new methodologies (401 unauthenticated, 403 field officer)."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.meth@carbontrack.org", UserRole.FIELD_OFFICER
    )

    payload = {
        "name": "Biochar",
        "version": "v1",
        "parameters": {
            "pyrolysis_temp_c": 550,
            "carbon_stability_factor": 0.80,
            "default_buffer_pct": 0.05,
        },
        "is_active": True,
    }

    # 1. Unauthenticated -> 401
    unauth_res = client.post("/api/v1/methodologies", json=payload)
    assert unauth_res.status_code == status.HTTP_401_UNAUTHORIZED

    # 2. Field Officer -> 403
    officer_res = client.post(
        "/api/v1/methodologies", json=payload, headers=officer_headers
    )
    assert officer_res.status_code == status.HTTP_403_FORBIDDEN

    # 3. Admin -> 201 Created
    admin_res = client.post(
        "/api/v1/methodologies", json=payload, headers=admin_headers
    )
    assert admin_res.status_code == status.HTTP_201_CREATED
    data = admin_res.json()
    assert data["name"] == "Biochar"
    assert data["version"] == "v1"
    assert data["parameters"]["pyrolysis_temp_c"] == 550
    assert data["is_active"] is True
    assert data["id"] is not None


def test_create_duplicate_methodology_endpoint_returns_409(client: TestClient) -> None:
    """Verify registering an existing methodology version returns 409 Conflict."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )

    payload = {
        "name": "Afforestation",
        "version": "v1.1",
        "parameters": {"carbon_fraction": 0.48},
        "is_active": True,
    }
    first_res = client.post(
        "/api/v1/methodologies", json=payload, headers=admin_headers
    )
    assert first_res.status_code == status.HTTP_201_CREATED

    dup_res = client.post("/api/v1/methodologies", json=payload, headers=admin_headers)
    assert dup_res.status_code == status.HTTP_409_CONFLICT


def test_list_methodologies_pagination_and_active_filter(client: TestClient) -> None:
    """Verify paginated listing of methodologies with active filter."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )

    # Seed default methodologies
    client.post(
        "/api/v1/methodologies",
        json={
            "name": "Afforestation",
            "version": "v1",
            "parameters": {"carbon_fraction": 0.47},
            "is_active": True,
        },
        headers=admin_headers,
    )
    client.post(
        "/api/v1/methodologies",
        json={
            "name": "Legacy Afforestation",
            "version": "v0.9",
            "parameters": {},
            "is_active": False,
        },
        headers=admin_headers,
    )

    # 1. List all
    res = client.get("/api/v1/methodologies", headers=admin_headers)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 2

    # 2. Filter active_only
    active_res = client.get(
        "/api/v1/methodologies?is_active=true", headers=admin_headers
    )
    assert active_res.status_code == status.HTTP_200_OK
    active_data = active_res.json()
    assert all(item["is_active"] is True for item in active_data["items"])

    # 3. Filter inactive
    inactive_res = client.get(
        "/api/v1/methodologies?is_active=false", headers=admin_headers
    )
    assert inactive_res.status_code == status.HTTP_200_OK
    inactive_data = inactive_res.json()
    assert all(item["is_active"] is False for item in inactive_data["items"])


def test_get_methodology_by_id_and_patch(client: TestClient) -> None:
    """Verify fetching methodology by ID and deactivating it via PATCH."""
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )

    create_res = client.post(
        "/api/v1/methodologies",
        json={
            "name": "Experimental Method",
            "version": "v1",
            "parameters": {"factor": 1.5},
            "is_active": True,
        },
        headers=admin_headers,
    )
    meth_id = create_res.json()["id"]

    # 1. GET by id
    get_res = client.get(f"/api/v1/methodologies/{meth_id}", headers=admin_headers)
    assert get_res.status_code == status.HTTP_200_OK
    assert get_res.json()["parameters"]["factor"] == 1.5

    # 2. GET non-existent
    not_found = client.get("/api/v1/methodologies/99999", headers=admin_headers)
    assert not_found.status_code == status.HTTP_404_NOT_FOUND

    # 3. PATCH deactivation
    patch_res = client.patch(
        f"/api/v1/methodologies/{meth_id}",
        json={"is_active": False},
        headers=admin_headers,
    )
    assert patch_res.status_code == status.HTTP_200_OK
    assert patch_res.json()["is_active"] is False
