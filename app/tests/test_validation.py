"""Unit tests for every validation rule and integration tests for the validation pipeline."""

from datetime import datetime, timedelta, timezone
from fastapi import status
from fastapi.testclient import TestClient

from app.models.land_parcel import LandParcel
from app.models.observation import Observation, ObservationType
from app.models.project import ProjectType
from app.models.user import UserRole
from app.models.validation_issue import ValidationSeverity
from app.schemas.validation import ValidationIssueItem
from app.services import validation
from app.services.validation import (
    ValidationContext,
    check_future_date,
    check_implausible_trees_per_acre,
    check_missing_baseline,
    check_soc_range,
    check_tree_count_drop,
    get_registered_rules,
    register_rule,
    reset_rules_to_default,
)


def _make_dummy_observation(
    obs_type: ObservationType,
    values: dict,
    observed_at: datetime | None = None,
    is_baseline: bool = False,
) -> Observation:
    """Create an in-memory Observation instance without database persistence."""
    return Observation(
        id=1,
        enrollment_id=1,
        type=obs_type,
        values=values,
        observed_at=observed_at or datetime.now(timezone.utc),
        observer_id=1,
        is_baseline=is_baseline,
        superseded_by=None,
    )


# =====================================================================
# Unit Tests for Every Individual Rule (Strategies)
# =====================================================================

def test_rule_soc_range() -> None:
    """Unit test for check_soc_range rule."""
    # 1. Valid SOC (1.5%) -> 0 issues
    valid_obs = _make_dummy_observation(ObservationType.SOIL, {"soc_percent": 1.5, "bulk_density": 1.2, "depth_cm": 30.0})
    ctx_valid = ValidationContext(observation=valid_obs)
    assert check_soc_range(ctx_valid) == []

    # 2. Below 0.1% -> 1 error issue
    low_obs = _make_dummy_observation(ObservationType.SOIL, {"soc_percent": 0.05, "bulk_density": 1.2, "depth_cm": 30.0})
    ctx_low = ValidationContext(observation=low_obs)
    low_issues = check_soc_range(ctx_low)
    assert len(low_issues) == 1
    assert low_issues[0].rule == "soc_range_check"
    assert low_issues[0].severity == ValidationSeverity.ERROR
    assert "0.05%" in low_issues[0].message

    # 3. Above 10.0% -> 1 error issue
    high_obs = _make_dummy_observation(ObservationType.SOIL, {"soc_percent": 14.2, "bulk_density": 1.2, "depth_cm": 30.0})
    ctx_high = ValidationContext(observation=high_obs)
    high_issues = check_soc_range(ctx_high)
    assert len(high_issues) == 1
    assert high_issues[0].rule == "soc_range_check"
    assert high_issues[0].severity == ValidationSeverity.ERROR

    # 4. Irrelevant observation type (tree_count) -> 0 issues
    tree_obs = _make_dummy_observation(ObservationType.TREE_COUNT, {"count": 200, "avg_height_m": 2.0})
    assert check_soc_range(ValidationContext(observation=tree_obs)) == []


def test_rule_tree_count_drop() -> None:
    """Unit test for check_tree_count_drop rule."""
    now = datetime.now(timezone.utc)
    prior_obs = _make_dummy_observation(
        ObservationType.TREE_COUNT,
        {"count": 500, "avg_height_m": 2.0},
        observed_at=now - timedelta(days=180),
    )

    # 1. Normal change (500 -> 450 = 10% drop, <= 30%) -> 0 issues
    current_ok = _make_dummy_observation(ObservationType.TREE_COUNT, {"count": 450, "avg_height_m": 2.5}, observed_at=now)
    ctx_ok = ValidationContext(observation=current_ok, prior_observations=[prior_obs])
    assert check_tree_count_drop(ctx_ok) == []

    # 2. Tree count increased (500 -> 600) -> 0 issues
    current_increase = _make_dummy_observation(ObservationType.TREE_COUNT, {"count": 600, "avg_height_m": 2.8}, observed_at=now)
    ctx_increase = ValidationContext(observation=current_increase, prior_observations=[prior_obs])
    assert check_tree_count_drop(ctx_increase) == []

    # 3. Critical drop (500 -> 250 = 50% drop, > 30%) -> 1 warning issue
    current_drop = _make_dummy_observation(ObservationType.TREE_COUNT, {"count": 250, "avg_height_m": 2.5}, observed_at=now)
    ctx_drop = ValidationContext(observation=current_drop, prior_observations=[prior_obs])
    drop_issues = check_tree_count_drop(ctx_drop)
    assert len(drop_issues) == 1
    assert drop_issues[0].rule == "tree_count_drop_check"
    assert drop_issues[0].severity == ValidationSeverity.WARNING
    assert "50.0%" in drop_issues[0].message

    # 4. No prior observation (first tree count recorded) -> 0 issues
    ctx_first = ValidationContext(observation=current_drop, prior_observations=[])
    assert check_tree_count_drop(ctx_first) == []


def test_rule_missing_baseline() -> None:
    """Unit test for check_missing_baseline rule."""
    baseline_obs = _make_dummy_observation(ObservationType.SOIL, {"soc_percent": 1.2, "bulk_density": 1.3, "depth_cm": 30.0}, is_baseline=True)

    # 1. Baseline observation itself -> 0 issues (even if active_baseline is None in context)
    ctx_baseline = ValidationContext(observation=baseline_obs, active_baseline=None)
    assert check_missing_baseline(ctx_baseline) == []

    # 2. Monitoring observation with active baseline present -> 0 issues
    monitoring_obs = _make_dummy_observation(ObservationType.SOIL, {"soc_percent": 1.4, "bulk_density": 1.3, "depth_cm": 30.0}, is_baseline=False)
    ctx_with_base = ValidationContext(observation=monitoring_obs, active_baseline=baseline_obs)
    assert check_missing_baseline(ctx_with_base) == []

    # 3. Monitoring observation with NO active baseline -> 1 error issue
    ctx_no_base = ValidationContext(observation=monitoring_obs, active_baseline=None)
    missing_issues = check_missing_baseline(ctx_no_base)
    assert len(missing_issues) == 1
    assert missing_issues[0].rule == "missing_baseline_check"
    assert missing_issues[0].severity == ValidationSeverity.ERROR


def test_rule_future_date() -> None:
    """Unit test for check_future_date rule."""
    # 1. Past date -> 0 issues
    past_obs = _make_dummy_observation(
        ObservationType.SOIL,
        {"soc_percent": 1.2, "bulk_density": 1.3, "depth_cm": 30.0},
        observed_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    assert check_future_date(ValidationContext(observation=past_obs)) == []

    # 2. Future date -> 1 error issue
    future_obs = _make_dummy_observation(
        ObservationType.SOIL,
        {"soc_percent": 1.2, "bulk_density": 1.3, "depth_cm": 30.0},
        observed_at=datetime.now(timezone.utc) + timedelta(days=5),
    )
    future_issues = check_future_date(ValidationContext(observation=future_obs))
    assert len(future_issues) == 1
    assert future_issues[0].rule == "future_date_check"
    assert future_issues[0].severity == ValidationSeverity.ERROR


def test_rule_implausible_trees_per_acre() -> None:
    """Unit test for check_implausible_trees_per_acre rule."""
    parcel_10_acres = LandParcel(id=1, farmer_id=1, area_acres=10.0)
    parcel_1_acre = LandParcel(id=2, farmer_id=1, area_acres=1.0)

    # 1. Normal density: 10 acres, 4,000 trees = 400 trees/acre (<= 2500) -> 0 issues
    obs_normal = _make_dummy_observation(ObservationType.TREE_COUNT, {"count": 4000, "avg_height_m": 3.0})
    ctx_normal = ValidationContext(observation=obs_normal, parcel=parcel_10_acres)
    assert check_implausible_trees_per_acre(ctx_normal) == []

    # 2. Implausible density: 1 acre, 5,000 trees = 5000 trees/acre (> 2500) -> 1 error issue
    obs_implausible = _make_dummy_observation(ObservationType.TREE_COUNT, {"count": 5000, "avg_height_m": 3.0})
    ctx_implausible = ValidationContext(observation=obs_implausible, parcel=parcel_1_acre)
    density_issues = check_implausible_trees_per_acre(ctx_implausible)
    assert len(density_issues) == 1
    assert density_issues[0].rule == "implausible_trees_per_acre_check"
    assert density_issues[0].severity == ValidationSeverity.ERROR
    assert "5000.0 trees/acre" in density_issues[0].message


# =====================================================================
# Unit Test for the Pluggable Registry / Strategy Pattern
# =====================================================================

def test_pluggable_registry_pattern() -> None:
    """Verify that custom validation rules can be registered dynamically."""
    try:
        # Define a custom domain rule strategy
        def custom_odd_tree_count_rule(context: ValidationContext) -> list[ValidationIssueItem]:
            if context.observation.type == ObservationType.TREE_COUNT:
                count = context.observation.values.get("count", 0)
                if count % 2 != 0:
                    return [
                        ValidationIssueItem(
                            rule="odd_tree_count_warning",
                            severity=ValidationSeverity.INFO,
                            message=f"Tree count {count} is an odd number (custom audit rule).",
                        )
                    ]
            return []

        # Register the new strategy
        register_rule(custom_odd_tree_count_rule)
        assert custom_odd_tree_count_rule in get_registered_rules()

        # Run context on odd tree count
        odd_obs = _make_dummy_observation(ObservationType.TREE_COUNT, {"count": 301, "avg_height_m": 2.0})
        ctx = ValidationContext(observation=odd_obs)

        # Check issues from all registered rules
        issues = []
        for r in get_registered_rules():
            issues.extend(r(ctx))

        assert any(i.rule == "odd_tree_count_warning" for i in issues)
    finally:
        reset_rules_to_default()


# =====================================================================
# Integration Tests with Database Persistence & API Endpoints
# =====================================================================

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


def test_validation_pipeline_database_persistence_and_summary(client: TestClient) -> None:
    """Verify validation runs and persists issues to validation_issues table with summary."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.val1@carbontrack.org", UserRole.FIELD_OFFICER)

    # 1. Setup entities: Farmer -> Parcel (2 acres) -> Project -> Enrollment
    farmer_res = client.post(
        "/api/v1/farmers",
        json={"name": "Mahadevappa", "district": "Mysuru", "state": "Karnataka", "consent_given": True},
        headers=officer_headers,
    )
    farmer_id = farmer_res.json()["id"]

    parcel_res = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 2.0, "soil_type": "red_loam"},
        headers=officer_headers,
    )
    parcel_id = parcel_res.json()["id"]

    project_res = client.post(
        "/api/v1/projects",
        json={"name": "Mysuru Afforestation", "type": ProjectType.AFFORESTATION.value, "start_date": "2025-01-01"},
        headers=admin_headers,
    )
    project_id = project_res.json()["id"]

    enrollment_res = client.post(
        "/api/v1/enrollments",
        json={"project_id": project_id, "parcel_id": parcel_id, "farmer_id": farmer_id, "status": "active"},
        headers=officer_headers,
    )
    enrollment_id = enrollment_res.json()["id"]

    # 2. Create an observation with 2 violations:
    # - is_baseline=False without prior baseline (missing_baseline_check)
    # - 10,000 trees on 2 acres = 5,000 trees/acre (implausible_trees_per_acre_check)
    obs_res = client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 10000, "avg_height_m": 3.0},
            "observed_at": "2026-01-15T10:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    )
    assert obs_res.status_code == status.HTTP_201_CREATED
    obs_id = obs_res.json()["id"]

    # 3. Query GET /api/v1/observations/{id}/issues
    issues_res = client.get(f"/api/v1/observations/{obs_id}/issues", headers=officer_headers)
    assert issues_res.status_code == status.HTTP_200_OK
    summary = issues_res.json()
    assert summary["observation_id"] == obs_id
    assert summary["is_valid"] is False  # Because error_count > 0
    assert summary["error_count"] >= 2
    rule_names = [i["rule"] for i in summary["issues"]]
    assert "missing_baseline_check" in rule_names
    assert "implausible_trees_per_acre_check" in rule_names

    # 4. Trigger explicit POST /api/v1/observations/{id}/validate
    validate_res = client.post(f"/api/v1/observations/{obs_id}/validate", headers=officer_headers)
    assert validate_res.status_code == status.HTTP_200_OK
    assert validate_res.json()["is_valid"] is False


def test_clean_observation_has_zero_issues(client: TestClient) -> None:
    """Verify clean observation reports is_valid=True and 0 errors."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.val2@carbontrack.org", UserRole.FIELD_OFFICER)

    # Setup entities
    farmer_id = client.post(
        "/api/v1/farmers",
        json={"name": "Siddappa", "district": "Mandya", "state": "Karnataka", "consent_given": True},
        headers=officer_headers,
    ).json()["id"]

    parcel_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 10.0},
        headers=officer_headers,
    ).json()["id"]

    project_id = client.post(
        "/api/v1/projects",
        json={"name": "Mandya Soil Carbon", "type": "regen_ag", "start_date": "2025-01-01"},
        headers=admin_headers,
    ).json()["id"]

    enrollment_id = client.post(
        "/api/v1/enrollments",
        json={"project_id": project_id, "parcel_id": parcel_id, "farmer_id": farmer_id, "status": "active"},
        headers=officer_headers,
    ).json()["id"]

    # Baseline soil observation with valid SOC (1.5%)
    obs_res = client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "soil",
            "values": {"soc_percent": 1.5, "bulk_density": 1.25, "depth_cm": 30.0},
            "observed_at": "2025-01-10T10:00:00Z",
            "is_baseline": True,
        },
        headers=officer_headers,
    )
    obs_id = obs_res.json()["id"]

    # Check issues
    summary_res = client.get(f"/api/v1/observations/{obs_id}/issues", headers=officer_headers)
    assert summary_res.status_code == status.HTTP_200_OK
    summary = summary_res.json()
    assert summary["is_valid"] is True
    assert summary["excluded_from_estimation"] is False
    assert summary["error_count"] == 0
    assert summary["issues"] == []


def test_create_observation_returns_issues_and_exclusion_flag(client: TestClient) -> None:
    """Task 5.2: Verify observation submission automatically runs validation, returns issues,

    and flags error-severity observations as excluded_from_estimation=True.
    """
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.auto1@carbontrack.org", UserRole.FIELD_OFFICER)

    farmer_id = client.post(
        "/api/v1/farmers",
        json={"name": "Kallappa", "district": "Belagavi", "state": "Karnataka", "consent_given": True},
        headers=officer_headers,
    ).json()["id"]

    parcel_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 5.0},
        headers=officer_headers,
    ).json()["id"]

    project_id = client.post(
        "/api/v1/projects",
        json={"name": "Belagavi Agroforestry", "type": "afforestation", "start_date": "2025-01-01"},
        headers=admin_headers,
    ).json()["id"]

    enrollment_id = client.post(
        "/api/v1/enrollments",
        json={"project_id": project_id, "parcel_id": parcel_id, "farmer_id": farmer_id, "status": "active"},
        headers=officer_headers,
    ).json()["id"]

    # Submit observation with implausible tree count (30,000 trees on 5 acres = 6,000 trees/acre > 2,500 max)
    # and no baseline exists yet -> triggers both missing_baseline_check AND implausible_trees_per_acre_check
    res = client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 30000, "avg_height_m": 2.5},
            "observed_at": "2025-06-01T10:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()

    # Verify Task 5.2 requirements:
    # 1. Issues are returned directly in the creation response
    assert "issues" in data
    assert isinstance(data["issues"], list)
    assert len(data["issues"]) >= 2

    # 2. Error-severity observations are flagged as excluded from estimation
    assert data["is_valid"] is False
    assert data["excluded_from_estimation"] is True

    rule_names = [issue["rule"] for issue in data["issues"]]
    assert "missing_baseline_check" in rule_names
    assert "implausible_trees_per_acre_check" in rule_names
    assert all(issue["severity"] == "error" for issue in data["issues"])


def test_create_clean_observation_not_excluded_from_estimation(client: TestClient) -> None:
    """Task 5.2: Verify clean observation returns is_valid=True and excluded_from_estimation=False."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.auto2@carbontrack.org", UserRole.FIELD_OFFICER)

    farmer_id = client.post(
        "/api/v1/farmers",
        json={"name": "Basavaraj", "district": "Dharwad", "state": "Karnataka", "consent_given": True},
        headers=officer_headers,
    ).json()["id"]

    parcel_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 12.0},
        headers=officer_headers,
    ).json()["id"]

    project_id = client.post(
        "/api/v1/projects",
        json={"name": "Dharwad Soil Carbon", "type": "regen_ag", "start_date": "2025-01-01"},
        headers=admin_headers,
    ).json()["id"]

    enrollment_id = client.post(
        "/api/v1/enrollments",
        json={"project_id": project_id, "parcel_id": parcel_id, "farmer_id": farmer_id, "status": "active"},
        headers=officer_headers,
    ).json()["id"]

    # Submit valid baseline observation
    res = client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "soil",
            "values": {"soc_percent": 1.8, "bulk_density": 1.2, "depth_cm": 30.0},
            "observed_at": "2025-02-01T10:00:00Z",
            "is_baseline": True,
        },
        headers=officer_headers,
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()

    assert data["is_valid"] is True
    assert data["excluded_from_estimation"] is False
    assert data["issues"] == []


def test_supersede_observation_runs_validation_and_returns_issues(client: TestClient) -> None:
    """Task 5.2: Verify append-only corrections via supersede automatically validate and return issues."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.auto3@carbontrack.org", UserRole.FIELD_OFFICER)

    farmer_id = client.post(
        "/api/v1/farmers",
        json={"name": "Ningappa", "district": "Haveri", "state": "Karnataka", "consent_given": True},
        headers=officer_headers,
    ).json()["id"]

    parcel_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 8.0},
        headers=officer_headers,
    ).json()["id"]

    project_id = client.post(
        "/api/v1/projects",
        json={"name": "Haveri Agroforestry", "type": "afforestation", "start_date": "2025-01-01"},
        headers=admin_headers,
    ).json()["id"]

    enrollment_id = client.post(
        "/api/v1/enrollments",
        json={"project_id": project_id, "parcel_id": parcel_id, "farmer_id": farmer_id, "status": "active"},
        headers=officer_headers,
    ).json()["id"]

    # 1. Baseline observation
    base_res = client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 1000, "avg_height_m": 2.0},
            "observed_at": "2025-01-10T10:00:00Z",
            "is_baseline": True,
        },
        headers=officer_headers,
    )
    assert base_res.json()["excluded_from_estimation"] is False

    # 2. Subsequent observation with invalid tree drop: from 1000 down to 500 (50% drop > 30% threshold -> warning)
    obs_res = client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 500, "avg_height_m": 2.5},
            "observed_at": "2025-04-10T10:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    )
    obs_id = obs_res.json()["id"]
    # Tree drop is a warning, so is_valid remains True and excluded_from_estimation is False
    assert obs_res.json()["is_valid"] is True
    assert obs_res.json()["excluded_from_estimation"] is False
    assert len(obs_res.json()["issues"]) == 1
    assert obs_res.json()["issues"][0]["severity"] == "warning"

    # 3. Supersede with corrected values: now count is 950 (5% drop, fully plausible)
    sup_res = client.post(
        "/api/v1/observations/{}/supersede".format(obs_id),
        json={
            "values": {"count": 950, "avg_height_m": 2.6},
            "observed_at": "2025-04-10T10:00:00Z",
        },
        headers=officer_headers,
    )
    assert sup_res.status_code == status.HTTP_201_CREATED
    sup_data = sup_res.json()
    assert sup_data["is_valid"] is True
    assert sup_data["excluded_from_estimation"] is False
    assert sup_data["issues"] == []


def test_get_observation_issues_endpoint_severity_filter(client: TestClient) -> None:
    """Task 5.2: Verify GET /api/v1/observations/{id}/issues and severity query filtering."""
    admin_headers = _create_user_and_login(client, "super.admin@carbontrack.org", UserRole.ADMIN)
    officer_headers = _create_user_and_login(client, "officer.auto4@carbontrack.org", UserRole.FIELD_OFFICER)

    farmer_id = client.post(
        "/api/v1/farmers",
        json={"name": "Mallikarjun", "district": "Bagalkot", "state": "Karnataka", "consent_given": True},
        headers=officer_headers,
    ).json()["id"]

    parcel_id = client.post(
        "/api/v1/parcels",
        json={"farmer_id": farmer_id, "area_acres": 5.0},
        headers=officer_headers,
    ).json()["id"]

    project_id = client.post(
        "/api/v1/projects",
        json={"name": "Bagalkot Trees", "type": "afforestation", "start_date": "2025-01-01"},
        headers=admin_headers,
    ).json()["id"]

    enrollment_id = client.post(
        "/api/v1/enrollments",
        json={"project_id": project_id, "parcel_id": parcel_id, "farmer_id": farmer_id, "status": "active"},
        headers=officer_headers,
    ).json()["id"]

    # Baseline with 1000 trees
    client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 1000, "avg_height_m": 2.0},
            "observed_at": "2025-01-01T10:00:00Z",
            "is_baseline": True,
        },
        headers=officer_headers,
    )

    # Observation with 50% drop (warning: 1000 -> 500)
    obs = client.post(
        "/api/v1/observations",
        json={
            "enrollment_id": enrollment_id,
            "type": "tree_count",
            "values": {"count": 500, "avg_height_m": 2.2},
            "observed_at": "2025-03-01T10:00:00Z",
            "is_baseline": False,
        },
        headers=officer_headers,
    ).json()
    obs_id = obs["id"]

    # 1. GET issues without filter
    all_issues_res = client.get(f"/api/v1/observations/{obs_id}/issues", headers=officer_headers)
    assert all_issues_res.status_code == status.HTTP_200_OK
    summary = all_issues_res.json()
    assert summary["observation_id"] == obs_id
    assert summary["is_valid"] is True
    assert summary["excluded_from_estimation"] is False
    assert summary["warning_count"] == 1
    assert len(summary["issues"]) == 1

    # 2. GET issues with severity=warning filter
    warn_res = client.get(f"/api/v1/observations/{obs_id}/issues?severity=warning", headers=officer_headers)
    assert warn_res.status_code == status.HTTP_200_OK
    assert len(warn_res.json()["issues"]) == 1
    assert warn_res.json()["issues"][0]["severity"] == "warning"

    # 3. GET issues with severity=error filter
    err_res = client.get(f"/api/v1/observations/{obs_id}/issues?severity=error", headers=officer_headers)
    assert err_res.status_code == status.HTTP_200_OK
    assert len(err_res.json()["issues"]) == 0
