"""Activity database model recording field interventions linked to enrollments."""

from datetime import date, datetime
import enum
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.enrollment import Enrollment


class ActivityType(str, enum.Enum):
    """Supported carbon removal or agricultural management activity types."""

    PLANTING = "planting"
    COVER_CROPPING = "cover_cropping"
    MULCHING = "mulching"
    COMPOSTING = "composting"


class Activity(Base):
    """Activity entity recording a dated management event on an enrolled parcel."""

    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    enrollment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("enrollments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    type: Mapped[ActivityType] = mapped_column(
        Enum(
            ActivityType,
            name="activity_type",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        index=True,
    )
    activity_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationship to parent enrollment
    enrollment: Mapped["Enrollment"] = relationship("Enrollment")

    def __repr__(self) -> str:
        return f"<Activity id={self.id} enrollment_id={self.enrollment_id} type={self.type.value!r} date={self.activity_date}>"
