"""Methodology domain services, calculation parameters management, and default seeds."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.methodology import Methodology
from app.schemas.methodology import MethodologyCreate, MethodologyUpdate


class MethodologyNotFoundError(ValueError):
    """Exception raised when a methodology record is not found."""


class MethodologyAlreadyExistsError(ValueError):
    """Exception raised when creating a methodology with an existing name and version."""


# Default seed methodologies per PROJECT_SPEC.md Section 7
# Every parameter is documented with its scientific source or ASSUMPTION label.
DEFAULT_METHODOLOGIES: list[dict[str, Any]] = [
    {
        "name": "Afforestation",
        "version": "v1",
        "is_active": True,
        "parameters": {
            # ASSUMPTION: IPCC 2006 Guidelines default average carbon fraction of dry wood biomass.
            "carbon_fraction": 0.47,
            # Stoichiometric conversion ratio: 44 (molecular weight of CO2) / 12 (atomic weight of Carbon).
            "co2_to_c_ratio": 3.6667,
            # ASSUMPTION: Placeholder average dry woody biomass per tree in kg across mixed agroforestry plantings.
            "default_biomass_per_tree_kg": 50.0,
            # ASSUMPTION: 10% sampling uncertainty deduction applied to gross removals.
            "default_uncertainty_pct": 0.10,
            # ASSUMPTION: 15% permanence buffer pool withholding against biotic or wildfire reversals.
            "default_buffer_pct": 0.15,
        },
    },
    {
        "name": "Soil Carbon",
        "version": "v1",
        "is_active": True,
        "parameters": {
            # Stoichiometric conversion ratio: 44 (molecular weight of CO2) / 12 (atomic weight of Carbon).
            "co2_to_c_ratio": 3.6667,
            # Exact metric conversion: 1 international acre = 0.40468564224 hectares.
            "acres_to_hectares": 0.404686,
            # ASSUMPTION: Standard topsoil core sampling depth in cm for regenerative agriculture MRV protocols.
            "depth_cm": 30.0,
            # ASSUMPTION: 15% deduction reflecting high spatial soil variance and core sampling uncertainty.
            "default_uncertainty_pct": 0.15,
            # ASSUMPTION: 20% permanence buffer pool withholding against soil tillage reversals.
            "default_buffer_pct": 0.20,
        },
    },
]


def create_methodology(
    db: Session,
    methodology_in: MethodologyCreate,
) -> Methodology:
    """Register a new methodology version.

    Why: PROJECT_SPEC.md Section 7 requires all carbon calculation parameters
    to live in the methodologies table and be versioned.
    Inputs: db (Session), methodology_in (MethodologyCreate schema)
    Outputs: Newly persisted Methodology entity.
    Raises: MethodologyAlreadyExistsError if (name, version) already exists.
    """
    existing = get_methodology_by_name_and_version(
        db,
        name=methodology_in.name,
        version=methodology_in.version,
    )
    if existing:
        raise MethodologyAlreadyExistsError(
            f"Methodology '{methodology_in.name}' with version '{methodology_in.version}' already exists."
        )

    methodology = Methodology(
        name=methodology_in.name,
        version=methodology_in.version,
        parameters=methodology_in.parameters,
        is_active=methodology_in.is_active,
    )
    db.add(methodology)
    db.commit()
    db.refresh(methodology)
    return methodology


def get_methodology_by_id(db: Session, methodology_id: int) -> Methodology | None:
    """Fetch a methodology by primary key ID.

    Why: Allows calculators and auditors to inspect the exact parameters used.
    Inputs: db (Session), methodology_id (int)
    Outputs: Methodology entity if found, None otherwise.
    """
    return db.get(Methodology, methodology_id)


def get_methodology_by_name_and_version(
    db: Session,
    name: str,
    version: str,
) -> Methodology | None:
    """Look up a methodology by unique composite key (name, version).

    Why: Guarantees reproducible carbon estimates by pinning calculations to exact methodology versions.
    Inputs: db (Session), name (str), version (str)
    Outputs: Methodology entity if found, None otherwise.
    """
    stmt = select(Methodology).where(
        Methodology.name == name,
        Methodology.version == version,
    )
    return db.execute(stmt).scalars().first()


def list_methodologies(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    is_active: bool | None = None,
) -> tuple[list[Methodology], int]:
    """List methodologies with pagination and optional active filter.

    Why: Allows selecting active methodologies for new projects while preserving deprecated versions.
    Inputs: db (Session), page (int), page_size (int), is_active (bool | None)
    Outputs: Tuple of (list of Methodology items, total count).
    """
    base_query = select(Methodology)
    if is_active is not None:
        base_query = base_query.where(Methodology.is_active == is_active)

    count_stmt = select(func.count()).select_from(base_query.subquery())
    total = db.execute(count_stmt).scalar_one() or 0

    offset = (page - 1) * page_size
    paged_query = (
        base_query.order_by(Methodology.name.asc(), Methodology.version.asc())
        .offset(offset)
        .limit(page_size)
    )
    items = list(db.execute(paged_query).scalars().all())
    return items, total


def update_methodology(
    db: Session,
    methodology_id: int,
    update_in: MethodologyUpdate,
) -> Methodology:
    """Update methodology parameters or active status.

    Why: Allows deactivating deprecated methodology versions without altering historical calculations.
    Inputs: db (Session), methodology_id (int), update_in (MethodologyUpdate)
    Outputs: Updated Methodology instance.
    Raises: MethodologyNotFoundError if methodology_id does not exist.
    """
    methodology = get_methodology_by_id(db, methodology_id)
    if not methodology:
        raise MethodologyNotFoundError(
            f"Methodology with ID {methodology_id} not found."
        )

    if update_in.parameters is not None:
        methodology.parameters = update_in.parameters
    if update_in.is_active is not None:
        methodology.is_active = update_in.is_active

    db.add(methodology)
    db.commit()
    db.refresh(methodology)
    return methodology


def seed_default_methodologies(db: Session) -> list[Methodology]:
    """Idempotently seed standard default methodologies (Afforestation v1 and Soil Carbon v1).

    Why: Ensures the carbon engine has calibrated parameters ready for calculations immediately.
    Inputs: db (Session)
    Outputs: List of seeded Methodology entities.
    """
    seeded: list[Methodology] = []
    for item in DEFAULT_METHODOLOGIES:
        existing = get_methodology_by_name_and_version(
            db, name=item["name"], version=item["version"]
        )
        if not existing:
            created = Methodology(
                name=item["name"],
                version=item["version"],
                is_active=item["is_active"],
                parameters=item["parameters"],
            )
            db.add(created)
            seeded.append(created)
        else:
            seeded.append(existing)

    db.commit()
    for m in seeded:
        db.refresh(m)
    return seeded
