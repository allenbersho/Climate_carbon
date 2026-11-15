"""Project database model and status enumeration."""

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ProjectType(str, enum.Enum):
    """Types of carbon removal projects per PROJECT_SPEC.md."""

    AFFORESTATION = "afforestation"
    REGEN_AG = "regen_ag"
    BIOCHAR = "biochar"


class ProjectStatus(str, enum.Enum):
    """Project lifecycle statuses (draft -> active -> closed)."""

    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class Project(Base):
    """Carbon project entity representing an MRV initiative."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    type: Mapped[ProjectType] = mapped_column(
        Enum(
            ProjectType,
            name="project_type",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        index=True,
    )
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(
            ProjectStatus,
            name="project_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=ProjectStatus.DRAFT,
        index=True,
    )
    methodology_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} name={self.name!r} type={self.type.value!r} status={self.status.value!r}>"
