"""Integration tests for Carbon Estimation pipeline, validation exclusion, role permissions,

and calculation reproducibility.
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


def _setup_afforestation_enrollment(
    client: TestClient,
    officer_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> tuple[int, int]:
    """Bootstrap Farmer, Parcel, Afforestation Project, and Enrollment, returning (enrollment_id, parcel_id)."""
    farmer_id = client.post(
        "/api/v1/farmers",
        json={
            "name": "Channappa",
            "district": "Uttara Kannada",
            "state": "Karnataka",
            "consent_given": True,
        },
        headers=officer_headers,
    ).json()["id"]

    parcel_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 5.0},
        headers=officer_headers,
    ).json()["id"]

    project_id = client.post(
        "/api/v1/projects",
        json={
            "name": "Western Ghats Afforestation",
            "type": "afforestation",
            "start_date": "2025-01-01",
        },
        headers=admin_headers,
    ).json()["id"]

    enrollment_id = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": project_id,
            "parcel_id": parcel_id,
            "farmer_id": farmer_id,
            "status": "active",
        },
        headers=officer_headers,
    ).json()["id"]

    return enrollment_id, parcel_id


def _setup_soil_carbon_enrollment(
    client: TestClient,
    officer_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> tuple[int, int]:
    """Bootstrap Farmer, Parcel, Regen Ag Project, and Enrollment, returning (enrollment_id, parcel_id)."""
    farmer_id = client.post(
        "/api/v1/farmers",
        json={
            "name": "Mahadevappa",
            "district": "Haveri",
            "state": "Karnataka",
            "consent_given": True,
        },
        headers=officer_headers,
    ).json()["id"]

    parcel_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 10.0},
        headers=officer_headers,
    ).json()["id"]

    project_id = client.post(
        "/api/v1/projects",
        json={
            "name": "Haveri Regen Soil Project",
            "type": "regen_ag",
            "start_date": "2025-01-01",
        },
        headers=admin_headers,
    ).json()["id"]

    enrollment_id = client.post(
        "/api/v1/enrollments",
        json={
            "project_id": project_id,
            "parcel_id": parcel_id,
            "farmer_id": farmer_id,
            "status": "active",
        },
        headers=officer_headers,
    ).json()["id"]

    return enrollment_id, parcel_id


# =====================================================================
# Tests: Calculation Execution & Endpoints
# =====================================================================


def test_estimate_afforestation_carbon_success(
    client: TestClient, db_session: Session
) -> None:
    """Verify Afforestation carbon credit estimation matches hand calculation."""
    seed_default_methodologies(db_session)
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.est1@carbontrack.org", UserRole.FIELD_OFFICER
    )
    verifier_headers = _create_user_and_login(
        client, "verifier.est1@carbontrack.org", UserRole.VERIFIER
    )

    enrollment_id, _parcel_id = _setup_afforestation_enrollment(
        client, officer_headers, admin_headers
    )

    # 1. Baseline observation: 100 trees on 2025-01-01
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 100, "avg_height_m": 1.5},
            "observed_at": "2025-01-01T10:00:00Z",
            "is_baseline": True,
        },
        headers=officer_headers,
    )

    # 2. Later monitoring observation: 500 trees on 2025-06-01
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 500, "avg_height_m": 2.5},
            "observed_at": "2025-06-01T10:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    )

    # 3. Verifier runs POST /api/v1/carbon/estimate
    res = client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": enrollment_id},
        headers=verifier_headers,
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()

    assert data["enrollment_id"] == enrollment_id
    assert data["methodology_version"] == "v1"
    assert data["status"] == "draft"
    # Matches calculation using seeded co2_to_c_ratio = 3.6667:
    # 11.75 t C * 3.6667 = 43.083725 tonnes gross, net = 43.083725 * 0.90 * 0.85 = 32.95905 tonnes
    assert data["co2e_tonnes"] == pytest.approx(43.083725, abs=1e-4)
    assert data["uncertainty_pct"] == 0.10
    assert data["buffer_pct"] == 0.15
    assert data["net_credits"] == pytest.approx(32.95905, abs=1e-4)

    # Verify inputs_snapshot audit compliance
    snapshot = data["inputs_snapshot"]
    assert "inputs" in snapshot
    assert "parameters" in snapshot
    assert "meta" in snapshot
    assert snapshot["inputs"]["trees"] == 500.0


def test_estimate_soil_carbon_success(client: TestClient, db_session: Session) -> None:
    """Verify Soil Carbon credit estimation matches hand calculation."""
    seed_default_methodologies(db_session)
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.est2@carbontrack.org", UserRole.FIELD_OFFICER
    )
    verifier_headers = _create_user_and_login(
        client, "verifier.est2@carbontrack.org", UserRole.VERIFIER
    )

    enrollment_id, _parcel_id = _setup_soil_carbon_enrollment(
        client, officer_headers, admin_headers
    )

    # 1. Baseline: SOC% 1.2, BD 1.30, Depth 30cm on 2025-01-01
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "soil",
            "values": {"soc_percent": 1.2, "bulk_density": 1.30, "depth_cm": 30.0},
            "observed_at": "2025-01-01T10:00:00Z",
            "is_baseline": True,
        },
        headers=officer_headers,
    )

    # 2. Later: SOC% 1.6, BD 1.25, Depth 30cm on 2025-07-01
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "soil",
            "values": {"soc_percent": 1.6, "bulk_density": 1.25, "depth_cm": 30.0},
            "observed_at": "2025-07-01T10:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    )

    # 3. Trigger estimation
    res = client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": enrollment_id},
        headers=verifier_headers,
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()

    # Matches calculation using seeded co2_to_c_ratio = 3.6667:
    # 53.418552 t C * 3.6667 = 195.869806 tonnes gross, net = 195.869806 * 0.85 * 0.80 = 133.191468 tonnes
    assert data["co2e_tonnes"] == pytest.approx(195.869806, abs=1e-4)
    assert data["net_credits"] == pytest.approx(133.191468, abs=1e-4)
    assert data["uncertainty_pct"] == 0.15
    assert data["buffer_pct"] == 0.20

    # 4. GET /api/v1/carbon/estimates/{enrollment_id}
    list_res = client.get(
        f"/api/v1/carbon/estimates/{enrollment_id}", headers=officer_headers
    )
    assert list_res.status_code == status.HTTP_200_OK
    assert list_res.json()["total"] >= 1
    assert list_res.json()["items"][0]["id"] == data["id"]


# =====================================================================
# Tests: Reproducibility & Methodology Version Immunity
# =====================================================================


def test_estimate_reproducibility_same_inputs_same_results(
    client: TestClient, db_session: Session
) -> None:
    """Verify mathematical reproducibility: running estimation with identical inputs

    produces exact identical results and snapshots.
    """
    seed_default_methodologies(db_session)
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.repro@carbontrack.org", UserRole.FIELD_OFFICER
    )

    enrollment_id, _parcel_id = _setup_afforestation_enrollment(
        client, officer_headers, admin_headers
    )

    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
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
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 400, "avg_height_m": 2.2},
            "observed_at": "2025-05-01T10:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    )

    # Estimate 1
    est1 = client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": enrollment_id},
        headers=admin_headers,
    ).json()
    # Estimate 2
    est2 = client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": enrollment_id},
        headers=admin_headers,
    ).json()

    assert est1["co2e_tonnes"] == est2["co2e_tonnes"]
    assert est1["net_credits"] == est2["net_credits"]
    assert est1["inputs_snapshot"]["inputs"] == est2["inputs_snapshot"]["inputs"]
    assert (
        est1["inputs_snapshot"]["parameters"] == est2["inputs_snapshot"]["parameters"]
    )


def test_methodology_mutation_does_not_alter_stored_estimates(
    client: TestClient, db_session: Session
) -> None:
    """Verify that updating a methodology row's parameters never alters historical stored estimates."""
    seed_default_methodologies(db_session)
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.mut@carbontrack.org", UserRole.FIELD_OFFICER
    )

    enrollment_id, _parcel_id = _setup_afforestation_enrollment(
        client, officer_headers, admin_headers
    )

    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
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
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 500, "avg_height_m": 2.5},
            "observed_at": "2025-06-01T10:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    )

    # Run original estimate under Afforestation v1 (net = 32.95905)
    orig_res = client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": enrollment_id},
        headers=admin_headers,
    )
    orig_data = orig_res.json()
    orig_id = orig_data["id"]
    orig_net = orig_data["net_credits"]
    assert orig_net == pytest.approx(32.95905, abs=1e-4)

    # Now Admin mutates Afforestation methodology parameters in the DB (e.g. changing buffer from 15% to 50%)
    meth_res = client.get("/api/v1/methodologies", headers=admin_headers)
    aff_meth = next(m for m in meth_res.json()["items"] if m["name"] == "Afforestation")
    client.patch(
        f"/api/v1/methodologies/{aff_meth['id']}",
        json={"parameters": {"carbon_fraction": 0.20, "default_buffer_pct": 0.50}},
        headers=admin_headers,
    )

    # Re-fetch the historical estimate via GET /api/v1/carbon/estimates/{id}
    hist_res = client.get(
        f"/api/v1/carbon/estimates/{enrollment_id}", headers=officer_headers
    )
    stored_est = next(
        item for item in hist_res.json()["items"] if item["id"] == orig_id
    )

    # Historical estimate MUST be 100% immune to methodology mutations!
    assert stored_est["net_credits"] == orig_net
    assert stored_est["inputs_snapshot"]["parameters"]["carbon_fraction"] == 0.47


# =====================================================================
# Tests: Validation Error Exclusion & Rule 3 Requirements
# =====================================================================


def test_error_flagged_observations_excluded_from_estimation(
    client: TestClient, db_session: Session
) -> None:
    """Verify Rule 4: Observations with error-severity issues are excluded from estimation."""
    seed_default_methodologies(db_session)
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.excl@carbontrack.org", UserRole.FIELD_OFFICER
    )

    enrollment_id, _parcel_id = _setup_afforestation_enrollment(
        client, officer_headers, admin_headers
    )

    # 1. Baseline observation (valid)
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 100, "avg_height_m": 1.5},
            "observed_at": "2025-01-01T10:00:00Z",
            "is_baseline": True,
        },
        headers=officer_headers,
    )

    # 2. Later observation with ERROR severity: 50,000 trees on 5 acres = 10,000 trees/acre (> 2500 max)
    # This observation has excluded_from_estimation = True
    bad_obs = client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 50000, "avg_height_m": 2.0},
            "observed_at": "2025-04-01T10:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    ).json()
    assert bad_obs["excluded_from_estimation"] is True

    # 3. Attempting estimation now must fail because the bad observation is excluded,
    # leaving zero valid subsequent observations (violating Rule 3) -> HTTP 422
    fail_res = client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": enrollment_id},
        headers=admin_headers,
    )
    assert fail_res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # 4. Now record a clean valid subsequent observation (300 trees)
    good_obs = client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 300, "avg_height_m": 2.2},
            "observed_at": "2025-06-01T10:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    ).json()
    assert good_obs["excluded_from_estimation"] is False

    # 5. Now estimation succeeds using the valid observation (300 trees), ignoring the 50,000 tree record
    success_res = client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": enrollment_id},
        headers=admin_headers,
    )
    assert success_res.status_code == status.HTTP_201_CREATED
    assert success_res.json()["inputs_snapshot"]["inputs"]["trees"] == 300.0


def test_insufficient_observations_rejected_422(
    client: TestClient, db_session: Session
) -> None:
    """Verify Rule 3: Missing baseline or missing later observation raises 422."""
    seed_default_methodologies(db_session)
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.insuf@carbontrack.org", UserRole.FIELD_OFFICER
    )

    enrollment_id, _parcel_id = _setup_afforestation_enrollment(
        client, officer_headers, admin_headers
    )

    # 1. Zero observations -> 422
    res1 = client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": enrollment_id},
        headers=admin_headers,
    )
    assert res1.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # 2. Baseline only (no subsequent observation) -> 422
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 100, "avg_height_m": 1.5},
            "observed_at": "2025-01-01T10:00:00Z",
            "is_baseline": True,
        },
        headers=officer_headers,
    )
    res2 = client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": enrollment_id},
        headers=admin_headers,
    )
    assert res2.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_role_permissions_for_carbon_estimates(
    client: TestClient, db_session: Session
) -> None:
    """Verify RBAC: Admin and Verifier can run estimate, Field Officer 403, Unauthenticated 401."""
    seed_default_methodologies(db_session)
    admin_headers = _create_user_and_login(
        client, "super.admin@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.role@carbontrack.org", UserRole.FIELD_OFFICER
    )
    verifier_headers = _create_user_and_login(
        client, "verifier.role@carbontrack.org", UserRole.VERIFIER
    )

    enrollment_id, _parcel_id = _setup_afforestation_enrollment(
        client, officer_headers, admin_headers
    )

    # 1. Unauthenticated -> 401
    unauth = client.post(
        "/api/v1/carbon/estimate", json={"enrollment_id": enrollment_id}
    )
    assert unauth.status_code == status.HTTP_401_UNAUTHORIZED

    # 2. Field Officer -> 403 Forbidden
    officer_res = client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": enrollment_id},
        headers=officer_headers,
    )
    assert officer_res.status_code == status.HTTP_403_FORBIDDEN

    # 3. Verifier -> allowed (returns 422 because observations aren't added yet, proving auth succeeded!)
    verifier_res = client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": enrollment_id},
        headers=verifier_headers,
    )
    assert verifier_res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_carbon_estimate_error_branches_and_not_found(
    client: TestClient, db_session: Session
) -> None:
    """Verify 404 on nonexistent enrollment/methodology and get_estimate_by_id helper."""
    seed_default_methodologies(db_session)
    admin_headers = _create_user_and_login(
        client, "admin.carb_err@carbontrack.org", UserRole.ADMIN
    )
    officer_headers = _create_user_and_login(
        client, "officer.carb_err@carbontrack.org", UserRole.FIELD_OFFICER
    )
    enrollment_id, _parcel_id = _setup_afforestation_enrollment(
        client, officer_headers, admin_headers
    )

    # 1. Nonexistent enrollment -> 404
    res_no_enrollment = client.post(
        "/api/v1/carbon/estimate", json={"enrollment_id": 99999}, headers=admin_headers
    )
    assert res_no_enrollment.status_code == status.HTTP_404_NOT_FOUND

    # Add valid observations to enrollment
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
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
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 150, "avg_height_m": 2.0},
            "observed_at": "2026-01-01T10:00:00Z",
        },
        headers=officer_headers,
    )

    # 2. Nonexistent methodology -> 400 Bad Request
    res_bad_methodology = client.post(
        "/api/v1/carbon/estimate",
        json={"enrollment_id": enrollment_id, "methodology_id": 99999},
        headers=admin_headers,
    )
    assert res_bad_methodology.status_code == status.HTTP_400_BAD_REQUEST

    # 3. Get history for nonexistent enrollment -> 404
    hist_404 = client.get("/api/v1/carbon/estimates/99999", headers=admin_headers)
    assert hist_404.status_code == status.HTTP_404_NOT_FOUND

    # 4. Direct call to get_estimate_by_id with nonexistent ID returns None
    from app.services.carbon_service import get_estimate_by_id

    assert get_estimate_by_id(db_session, estimate_id=99999) is None
