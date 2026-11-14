"""Enrollment database model linking Projects, LandParcels, and Farmers."""

from datetime import date, datetime
import enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.farmer import Farmer
    from app.models.land_parcel import LandParcel
    from app.models.project import Project


class EnrollmentStatus(str, enum.Enum):
    """Lifecycle statuses for a parcel's project enrollment."""

    ACTIVE = "active"
    PENDING = "pending"
    COMPLETED = "completed"
    TERMINATED = "terminated"


class Enrollment(Base):
    """Enrollment entity mapping a parcel to a carbon project with baseline data."""

    __tablename__ = "enrollments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    parcel_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("land_parcels.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    farmer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("farmers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    baseline_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[EnrollmentStatus] = mapped_column(
        Enum(
            EnrollmentStatus,
            name="enrollment_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=EnrollmentStatus.ACTIVE,
        index=True,
    )
    additionality_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project")
    parcel: Mapped["LandParcel"] = relationship("LandParcel")
    farmer: Mapped["Farmer"] = relationship("Farmer")

    def __repr__(self) -> str:
        return f"<Enrollment id={self.id} project_id={self.project_id} parcel_id={self.parcel_id} status={self.status.value!r}>"
