"""Project domain services, business logic, and lifecycle state machine."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.project import Project, ProjectStatus, ProjectType
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.services.audit_service import record_audit_event


class InvalidStatusTransitionError(ValueError):
    """Exception raised when an unauthorized project status transition is attempted."""


# Finite State Machine transitions: draft -> active -> closed only (no skipping back)
ALLOWED_STATUS_TRANSITIONS: dict[ProjectStatus, set[ProjectStatus]] = {
    ProjectStatus.DRAFT: {ProjectStatus.DRAFT, ProjectStatus.ACTIVE},
    ProjectStatus.ACTIVE: {ProjectStatus.ACTIVE, ProjectStatus.CLOSED},
    ProjectStatus.CLOSED: {ProjectStatus.CLOSED},
}


def create_project(
    db: Session,
    project_in: ProjectCreate,
    user: User | None = None,
) -> Project:
    """Create a new carbon project in DRAFT status.

    Why: Every carbon project starts in DRAFT while baseline studies and methodologies are assembled.
    Inputs: db (SQLAlchemy session), project_in (validated ProjectCreate schema), user (optional acting User)
    Outputs: Newly persisted Project model instance.
    """
    project = Project(
        name=project_in.name.strip(),
        type=project_in.type,
        status=project_in.status,
        methodology_id=project_in.methodology_id,
        start_date=project_in.start_date,
    )
    db.add(project)
    db.flush()
    record_audit_event(
        db,
        user=user,
        action="CREATE",
        entity_type="project",
        entity_id=project.id,
        before_state=None,
        after_state={
            "name": project.name,
            "type": project.type.value if hasattr(project.type, "value") else str(project.type),
            "status": project.status.value if hasattr(project.status, "value") else str(project.status),
        },
        commit=False,
    )
    db.commit()
    db.refresh(project)
    return project


def get_project_by_id(db: Session, project_id: int) -> Project | None:
    """Fetch a single project by primary key ID.

    Why: Standard lookup for project verification and enrollment.
    Inputs: db (Session), project_id (int)
    Outputs: Project instance if found, None otherwise.
    """
    return db.get(Project, project_id)


def list_projects(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    status: ProjectStatus | None = None,
    type: ProjectType | None = None,
    search: str | None = None,
) -> tuple[list[Project], int]:
    """Retrieve a paginated slice of projects filtered by status, type, and name search.

    Why: Supports project registry exploration, filtering, and verifier audits.
    Inputs: db (Session), page (int), page_size (int), status (ProjectStatus), type (ProjectType), search (str)
    Outputs: Tuple of (list of Project objects, total integer count).
    """
    base_query = select(Project)

    if status:
        base_query = base_query.where(Project.status == status)

    if type:
        base_query = base_query.where(Project.type == type)

    if search and search.strip():
        base_query = base_query.where(Project.name.ilike(f"%{search.strip()}%"))

    # Compute total count matching filters
    count_statement = select(func.count()).select_from(base_query.subquery())
    total = db.execute(count_statement).scalar_one() or 0

    # Paginate
    offset = (page - 1) * page_size
    paged_query = (
        base_query.order_by(Project.created_at.desc(), Project.id.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = list(db.execute(paged_query).scalars().all())

    return items, total


def update_project(
    db: Session,
    project: Project,
    update_in: ProjectUpdate,
    user: User | None = None,
) -> Project:
    """Update project attributes and enforce unidirectional lifecycle transitions.

    Why: Enforces business rule: draft -> active -> closed only (no skipping back).
    Inputs: db (Session), project (existing Project instance), update_in (ProjectUpdate schema), user (acting User)
    Outputs: Updated Project instance.
    Raises: InvalidStatusTransitionError if illegal status change attempted.
    """
    before_state = {
        "name": project.name,
        "status": project.status.value if hasattr(project.status, "value") else str(project.status),
        "type": project.type.value if hasattr(project.type, "value") else str(project.type),
    }

    update_data = update_in.model_dump(exclude_unset=True)

    # Validate state machine transition if status is being updated
    if "status" in update_data and update_data["status"] is not None:
        target_status: ProjectStatus = update_data["status"]
        current_status: ProjectStatus = project.status
        allowed = ALLOWED_STATUS_TRANSITIONS.get(current_status, set())

        if target_status not in allowed:
            raise InvalidStatusTransitionError(
                f"Invalid project status transition from '{current_status.value}' to '{target_status.value}'. "
                f"Allowed progression is strictly draft -> active -> closed."
            )

    for field, value in update_data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(project, field, value)

    after_state = {
        "name": project.name,
        "status": project.status.value if hasattr(project.status, "value") else str(project.status),
        "type": project.type.value if hasattr(project.type, "value") else str(project.type),
    }

    action = "STATE_CHANGE" if before_state["status"] != after_state["status"] else "UPDATE"
    record_audit_event(
        db,
        user=user,
        action=action,
        entity_type="project",
        entity_id=project.id,
        before_state=before_state,
        after_state=after_state,
        commit=False,
    )

    db.add(project)
    db.commit()
    db.refresh(project)
    return project
