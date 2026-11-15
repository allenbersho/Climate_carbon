"""Audit log API routes for inspecting historical system change events."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUserDep, SessionDep, require_roles
from app.models.user import UserRole
from app.schemas.audit_log import AuditLogListResponse, AuditLogRead
from app.services import audit_service

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])

# Verifiers and Admins have access to the regulatory audit trail
CanViewAuditLogs = Annotated[
    CurrentUserDep,
    Depends(require_roles(UserRole.ADMIN, UserRole.VERIFIER)),
]


@router.get(
    "",
    response_model=AuditLogListResponse,
    summary="List audit logs",
    description="Retrieve a paginated list of audit events. Accessible by Admin and Verifier roles.",
)
def list_audit_logs(
    db: SessionDep,
    _current_user: CanViewAuditLogs,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    entity_type: str | None = Query(
        default=None,
        description="Filter by entity type (project, farmer, enrollment, etc.)",
    ),
    entity_id: int | None = Query(default=None, description="Filter by entity ID"),
    user_id: int | None = Query(default=None, description="Filter by user ID"),
    action: str | None = Query(
        default=None,
        description="Filter by action (CREATE, UPDATE, STATE_CHANGE, SOFT_DELETE)",
    ),
) -> AuditLogListResponse:
    """Query historical audit events with optional entity and action filters."""
    items, total = audit_service.list_audit_logs(
        db=db,
        page=page,
        page_size=page_size,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        action=action,
    )
    return AuditLogListResponse(
        items=[AuditLogRead.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{log_id}",
    response_model=AuditLogRead,
    summary="Get audit log by ID",
    description="Retrieve a specific audit log record. Accessible by Admin and Verifier roles.",
)
def get_audit_log(
    log_id: int,
    db: SessionDep,
    _current_user: CanViewAuditLogs,
) -> AuditLogRead:
    """Fetch details of a single audit event."""
    log_entry = audit_service.get_audit_log_by_id(db, log_id=log_id)
    if not log_entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit log with ID {log_id} not found.",
        )
    return AuditLogRead.model_validate(log_entry)
