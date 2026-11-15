"""Seed script generating 500 realistic demo farmers with parcels, projects, enrollments, activities, and observations.

Why: Phase 10 Task 10.3 requires realistic demo data to stress-test queries,
populate analytics dashboards, and support investor/interviewer demonstrations.
"""

import random
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Ensure repository root is on sys.path for direct CLI execution
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.activity import Activity, ActivityType
from app.models.carbon_estimate import CarbonEstimate, EstimateStatus
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.farmer import Farmer
from app.models.land_parcel import LandParcel
from app.models.methodology import Methodology
from app.models.observation import Observation, ObservationType
from app.models.project import Project, ProjectStatus, ProjectType
from app.models.user import User, UserRole
from app.services.carbon.afforestation import AfforestationCalculator
from app.services.carbon.soil_carbon import SoilCarbonCalculator
from app.services.methodology_service import seed_default_methodologies
from app.services.validation import validate_observation
from scripts.seed_admin import seed_admin

# Realistic domain data constants
FIRST_NAMES = [
    "Ramesh",
    "Suresh",
    "Ningappa",
    "Mallikarjun",
    "Basavaraj",
    "Shanthappa",
    "Laxmi",
    "Parvati",
    "Manjula",
    "Anand",
    "Venkatesh",
    "Ganesh",
    "Ravi",
    "Savitha",
    "Geetha",
    "Channappa",
    "Devendra",
    "Prakash",
    "Sunil",
    "Kavitha",
    "Girish",
    "Mahantesh",
    "Deepa",
    "Shankar",
    "Nagappa",
    "Renuka",
    "Shivaji",
]

LAST_NAMES = [
    "Gowda",
    "Patil",
    "Kumar",
    "Naik",
    "Hegde",
    "Shettar",
    "Devi",
    "Nayak",
    "Rathod",
    "Reddy",
    "Kulkarni",
    "Deshmukh",
    "Chavan",
    "Jadhav",
    "Bhat",
]

VILLAGES = [
    "Honnali",
    "Sagar",
    "Soraba",
    "Shikaripura",
    "Bhadravati",
    "Holenarasipura",
    "Arasikere",
    "Channagiri",
    "Harihara",
    "Ranebennur",
    "Byadgi",
    "Hirekerur",
    "Saundatti",
    "Ramdurg",
    "Bailhongal",
    "Gokak",
    "Chikodi",
    "Mudhol",
    "Bilgi",
]

DISTRICTS_AND_STATES = [
    ("Shivamogga", "Karnataka"),
    ("Mandya", "Karnataka"),
    ("Hassan", "Karnataka"),
    ("Haveri", "Karnataka"),
    ("Dharwad", "Karnataka"),
    ("Belagavi", "Karnataka"),
    ("Bellary", "Karnataka"),
    ("Bagalkot", "Karnataka"),
    ("Mysuru", "Karnataka"),
    ("Tumkur", "Karnataka"),
]

SOIL_TYPES = [
    "Red Sandy Loam",
    "Black Cotton Soil",
    "Alluvial",
    "Clay Loam",
    "Laterite Soil",
]

CROPS_AFFORESTATION = [
    "Teak & Rosewood",
    "Bamboo & Melia Dubia",
    "Agroforestry Timber",
    "Fruit Orchards",
]
CROPS_REGEN_AG = [
    "Finger Millet (Ragi)",
    "Sorghum (Jowar)",
    "Pulses & Legumes",
    "Cotton & Intercrops",
]


def seed_demo_data(
    db: Session, target_farmer_count: int = 500, random_seed: int = 42
) -> dict[str, int]:
    """Populate database with realistic demo farmers, parcels, enrollments, observations, and carbon estimates.

    Inputs:
        db: SQLAlchemy session
        target_farmer_count: Number of farmers to generate (default 500)
        random_seed: Seed for reproducible generation
    Outputs:
        Dictionary summarizing created entity counts.
    """
    random.seed(random_seed)

    print("[Demo Seed] Ensuring administrative user and default methodologies exist...")
    seed_admin(db)
    seed_default_methodologies(db)

    admin_user = db.query(User).filter(User.role == UserRole.ADMIN).first()
    observer_id = admin_user.id if admin_user else 1

    afforest_methodology = (
        db.query(Methodology)
        .filter(Methodology.name == "Afforestation", Methodology.version == "v1")
        .first()
    )
    soil_methodology = (
        db.query(Methodology)
        .filter(Methodology.name == "Soil Carbon", Methodology.version == "v1")
        .first()
    )

    # 1. Seed or retrieve anchor projects
    projects_data = [
        {
            "name": "Karnataka Agroforestry Carbon Initiative",
            "type": ProjectType.AFFORESTATION,
            "methodology_id": afforest_methodology.id if afforest_methodology else None,
            "start_date": date(2024, 1, 1),
        },
        {
            "name": "Deccan Soil Regeneration Program",
            "type": ProjectType.REGEN_AG,
            "methodology_id": soil_methodology.id if soil_methodology else None,
            "start_date": date(2024, 1, 1),
        },
        {
            "name": "Western Ghats Community Afforestation",
            "type": ProjectType.AFFORESTATION,
            "methodology_id": afforest_methodology.id if afforest_methodology else None,
            "start_date": date(2024, 6, 1),
        },
        {
            "name": "Cauvery Basin Soil Health Initiative",
            "type": ProjectType.REGEN_AG,
            "methodology_id": soil_methodology.id if soil_methodology else None,
            "start_date": date(2024, 6, 1),
        },
    ]

    created_projects: list[Project] = []
    for p_info in projects_data:
        existing = db.query(Project).filter(Project.name == p_info["name"]).first()
        if not existing:
            proj = Project(
                name=p_info["name"],
                type=p_info["type"],
                status=ProjectStatus.ACTIVE,
                start_date=p_info["start_date"],
                methodology_id=p_info["methodology_id"],
            )
            db.add(proj)
            db.flush()
            created_projects.append(proj)
        else:
            created_projects.append(existing)

    afforest_projects = [
        p for p in created_projects if p.type == ProjectType.AFFORESTATION
    ]
    regen_projects = [p for p in created_projects if p.type == ProjectType.REGEN_AG]

    # Check how many farmers already exist
    existing_farmer_count = db.query(Farmer).filter(Farmer.is_deleted == False).count()  # noqa: E712
    farmers_needed = max(0, target_farmer_count - existing_farmer_count)

    print(
        f"[Demo Seed] Current farmers in DB: {existing_farmer_count}. Generating {farmers_needed} new farmers..."
    )

    stats = {
        "farmers": 0,
        "parcels": 0,
        "enrollments": 0,
        "activities": 0,
        "observations": 0,
        "estimates": 0,
    }

    if farmers_needed <= 0:
        print("[Demo Seed] Database already contains desired farmer count.")
        return stats

    # Generate farmers in batches of 100
    batch_size = 100
    base_phone = 9845000000 + existing_farmer_count

    for b in range(0, farmers_needed, batch_size):
        current_batch_limit = min(batch_size, farmers_needed - b)
        print(
            f"[Demo Seed] Processing batch {b // batch_size + 1} ({current_batch_limit} farmers)..."
        )

        for i in range(current_batch_limit):
            f_idx = existing_farmer_count + b + i
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            name = f"{first} {last}"
            phone = f"{base_phone + b + i}"
            village = random.choice(VILLAGES)
            district, state = random.choice(DISTRICTS_AND_STATES)

            farmer = Farmer(
                name=name,
                phone=phone,
                village=village,
                district=district,
                state=state,
                consent_given=True,
                is_deleted=False,
            )
            db.add(farmer)
            db.flush()
            stats["farmers"] += 1

            # Each farmer owns 1 to 2 land parcels
            num_parcels = 1 if random.random() < 0.65 else 2
            for p_idx in range(num_parcels):
                area_acres = round(random.uniform(1.5, 12.0), 2)
                soil_type = random.choice(SOIL_TYPES)

                # Alternate parcel project assignment: 50% Agroforestry, 50% Soil Regen
                is_afforest = (f_idx + p_idx) % 2 == 0
                crop = random.choice(
                    CROPS_AFFORESTATION if is_afforest else CROPS_REGEN_AG
                )

                parcel = LandParcel(
                    farmer_id=farmer.id,
                    area_acres=area_acres,
                    soil_type=soil_type,
                    crop=crop,
                )
                db.add(parcel)
                db.flush()
                stats["parcels"] += 1

                # Enroll parcel in the appropriate project
                target_project = random.choice(
                    afforest_projects if is_afforest else regen_projects
                )
                enrollment_date = datetime(2024, 2, 1, 9, 0, tzinfo=UTC) + timedelta(
                    days=random.randint(0, 60)
                )

                enrollment = Enrollment(
                    project_id=target_project.id,
                    parcel_id=parcel.id,
                    farmer_id=farmer.id,
                    status=EnrollmentStatus.ACTIVE,
                    baseline_date=enrollment_date.date(),
                )
                db.add(enrollment)
                db.flush()
                stats["enrollments"] += 1

                # 1. Activities for this parcel
                act_date_1 = enrollment_date.date() + timedelta(
                    days=random.randint(5, 20)
                )
                act_type_1 = (
                    ActivityType.PLANTING
                    if is_afforest
                    else ActivityType.COVER_CROPPING
                )
                act_details_1 = (
                    {
                        "species": ["Teak", "Rosewood"],
                        "seedlings_count": int(area_acres * 150),
                    }
                    if is_afforest
                    else {"cover_crop": "Sunn hemp", "seed_rate_kg_per_acre": 15.0}
                )
                activity1 = Activity(
                    enrollment_id=enrollment.id,
                    type=act_type_1,
                    activity_date=act_date_1,
                    details=act_details_1,
                )
                db.add(activity1)

                act_date_2 = act_date_1 + timedelta(days=random.randint(30, 90))
                act_type_2 = (
                    ActivityType.MULCHING if is_afforest else ActivityType.COMPOSTING
                )
                act_details_2 = (
                    {"material": "Straw", "layer_depth_cm": 5}
                    if is_afforest
                    else {"compost_tonnes": round(area_acres * 1.5, 2)}
                )
                activity2 = Activity(
                    enrollment_id=enrollment.id,
                    type=act_type_2,
                    activity_date=act_date_2,
                    details=act_details_2,
                )
                db.add(activity2)
                stats["activities"] += 2

                # 2. Baseline Observation (at enrollment)
                base_time = enrollment_date + timedelta(days=random.randint(1, 10))
                if is_afforest:
                    base_trees = int(area_acres * random.randint(40, 80))
                    base_obs = Observation(
                        enrollment_id=enrollment.id,
                        type=ObservationType.TREE_COUNT,
                        values={"count": base_trees, "avg_height_m": 1.2},
                        observed_at=base_time,
                        is_baseline=True,
                        observer_id=observer_id,
                    )
                else:
                    base_soc = round(random.uniform(0.70, 1.10), 2)
                    base_obs = Observation(
                        enrollment_id=enrollment.id,
                        type=ObservationType.SOIL,
                        values={
                            "soc_percent": base_soc,
                            "bulk_density": 1.30,
                            "depth_cm": 30.0,
                        },
                        observed_at=base_time,
                        is_baseline=True,
                        observer_id=observer_id,
                    )
                db.add(base_obs)
                db.flush()
                validate_observation(db, base_obs.id, persist=True)
                stats["observations"] += 1

                # 3. Monitoring Observation (9 to 12 months later)
                mon_time = base_time + timedelta(days=random.randint(240, 360))
                if is_afforest:
                    mon_trees = base_trees + int(area_acres * random.randint(60, 120))
                    mon_obs = Observation(
                        enrollment_id=enrollment.id,
                        type=ObservationType.TREE_COUNT,
                        values={"count": mon_trees, "avg_height_m": 2.8},
                        observed_at=mon_time,
                        is_baseline=False,
                        observer_id=observer_id,
                    )
                else:
                    mon_soc = round(base_soc + random.uniform(0.35, 0.70), 2)
                    mon_obs = Observation(
                        enrollment_id=enrollment.id,
                        type=ObservationType.SOIL,
                        values={
                            "soc_percent": mon_soc,
                            "bulk_density": 1.22,
                            "depth_cm": 30.0,
                        },
                        observed_at=mon_time,
                        is_baseline=False,
                        observer_id=observer_id,
                    )
                db.add(mon_obs)
                db.flush()
                validate_observation(db, mon_obs.id, persist=True)
                stats["observations"] += 1

                # 4. Carbon Estimate calculation for completed cycles
                if is_afforest and afforest_methodology:
                    calc = AfforestationCalculator()
                    calc_res = calc.calculate(
                        inputs={
                            "tree_count": mon_trees,
                            "baseline_tree_count": base_trees,
                        },
                        parameters=afforest_methodology.parameters,
                    )
                    snapshot = {
                        "inputs": {
                            "tree_count": mon_trees,
                            "baseline_tree_count": base_trees,
                        },
                        "parameters": afforest_methodology.parameters,
                        "observation_ids": [base_obs.id, mon_obs.id],
                    }
                    est = CarbonEstimate(
                        enrollment_id=enrollment.id,
                        methodology_id=afforest_methodology.id,
                        methodology_version=afforest_methodology.version,
                        inputs_snapshot=snapshot,
                        co2e_tonnes=calc_res.co2e_gross_tonnes,
                        uncertainty_pct=calc_res.uncertainty_pct,
                        buffer_pct=calc_res.buffer_pct,
                        net_credits=calc_res.net_credits,
                        status=EstimateStatus.VERIFIED
                        if random.random() < 0.8
                        else EstimateStatus.DRAFT,
                    )
                    db.add(est)
                    stats["estimates"] += 1
                elif not is_afforest and soil_methodology:
                    calc = SoilCarbonCalculator()
                    calc_res = calc.calculate(
                        inputs={
                            "area_acres": area_acres,
                            "baseline_soc_percent": base_soc,
                            "baseline_bulk_density": 1.30,
                            "baseline_depth_cm": 30.0,
                            "current_soc_percent": mon_soc,
                            "current_bulk_density": 1.22,
                            "current_depth_cm": 30.0,
                        },
                        parameters=soil_methodology.parameters,
                    )
                    snapshot = {
                        "inputs": {
                            "area_acres": area_acres,
                            "baseline_soc_percent": base_soc,
                            "baseline_bulk_density": 1.30,
                            "baseline_depth_cm": 30.0,
                            "current_soc_percent": mon_soc,
                            "current_bulk_density": 1.22,
                            "current_depth_cm": 30.0,
                        },
                        "parameters": soil_methodology.parameters,
                        "observation_ids": [base_obs.id, mon_obs.id],
                    }
                    est = CarbonEstimate(
                        enrollment_id=enrollment.id,
                        methodology_id=soil_methodology.id,
                        methodology_version=soil_methodology.version,
                        inputs_snapshot=snapshot,
                        co2e_tonnes=calc_res.co2e_gross_tonnes,
                        uncertainty_pct=calc_res.uncertainty_pct,
                        buffer_pct=calc_res.buffer_pct,
                        net_credits=calc_res.net_credits,
                        status=EstimateStatus.VERIFIED
                        if random.random() < 0.8
                        else EstimateStatus.DRAFT,
                    )
                    db.add(est)
                    stats["estimates"] += 1

        db.commit()

    print("[Demo Seed] Generation complete!")
    print(
        f"Summary: {stats['farmers']} farmers, {stats['parcels']} parcels, "
        f"{stats['enrollments']} enrollments, {stats['activities']} activities, "
        f"{stats['observations']} observations, {stats['estimates']} carbon estimates."
    )
    return stats


def main() -> None:
    """CLI entrypoint for running the demo data seeder."""
    with SessionLocal() as db:
        seed_demo_data(db, target_farmer_count=500)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[Demo Seed Error] {exc}", file=sys.stderr)
        sys.exit(1)
