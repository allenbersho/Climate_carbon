"""Pydantic schemas for Audit Log entities."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditLogBase(BaseModel):
    """Shared baseline properties for an audit log entry."""

    action: str = Field(..., description="Action performed (CREATE, UPDATE, STATE_CHANGE, SOFT_DELETE)")
    entity_type: str = Field(..., description="Type of entity modified (project, enrollment, farmer, methodology, etc.)")
    entity_id: int = Field(..., description="ID of the entity modified")
    before_state: dict[str, Any] | None = Field(default=None, description="Snapshot of fields before modification")
    after_state: dict[str, Any] | None = Field(default=None, description="Snapshot of fields after modification")


class AuditLogRead(AuditLogBase):
    """Read representation of an audit log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Unique audit log ID")
    user_id: int | None = Field(default=None, description="ID of the user who performed the action")
    user_email: str | None = Field(default=None, description="Email of the user who performed the action")
    ip_address: str | None = Field(default=None, description="IP address of the client request")
    created_at: datetime = Field(..., description="UTC timestamp when the modification was logged")


class AuditLogListResponse(BaseModel):
    """Paginated response format for audit log queries."""

    items: list[AuditLogRead]
    total: int
    page: int
    page_size: int
