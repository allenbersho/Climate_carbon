"""Audit domain service for recording immutable change logs and querying the audit trail."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User


def record_audit_event(
    db: Session,
    user: User | None,
    action: str,
    entity_type: str,
    entity_id: int,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    ip_address: str | None = None,
    commit: bool = True,
) -> AuditLog:
    """Record an audit trail event capturing who changed what and the before/after state.

    Why: Task 9.1 requires regulatory traceability for create/update/state-change actions.
    Inputs: db, acting user (optional), action verb, entity type, entity ID, before/after states, client IP.
    Outputs: Newly created AuditLog record.
    """
    user_id = user.id if user else None
    user_email = user.email if user else None

    entry = AuditLog(
        user_id=user_id,
        user_email=user_email,
        action=action.upper(),
        entity_type=entity_type.lower(),
        entity_id=entity_id,
        before_state=before_state,
        after_state=after_state,
        ip_address=ip_address,
    )
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    return entry


def get_audit_log_by_id(db: Session, log_id: int) -> AuditLog | None:
    """Retrieve a single audit log entry by ID."""
    return db.get(AuditLog, log_id)


def list_audit_logs(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    entity_type: str | None = None,
    entity_id: int | None = None,
    user_id: int | None = None,
    action: str | None = None,
) -> tuple[list[AuditLog], int]:
    """Retrieve paginated audit logs with optional filtering by entity, user, or action.

    Why: Enables compliance audits and administrative investigations.
    """
    query = select(AuditLog)

    if entity_type and entity_type.strip():
        query = query.where(
            func.lower(AuditLog.entity_type) == entity_type.strip().lower()
        )
    if entity_id is not None:
        query = query.where(AuditLog.entity_id == entity_id)
    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)
    if action and action.strip():
        query = query.where(AuditLog.action == action.strip().upper())

    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar_one() or 0

    offset = (page - 1) * page_size
    paged_query = (
        query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = list(db.execute(paged_query).scalars().all())

    return items, total
