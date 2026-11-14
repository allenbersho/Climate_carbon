"""Carbon estimate database model storing calculated removals and audit snapshots."""

from datetime import datetime
import enum
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.enrollment import Enrollment
    from app.models.methodology import Methodology


class EstimateStatus(str, enum.Enum):
    """Lifecycle statuses for a carbon credit estimate."""

    DRAFT = "draft"
    VERIFIED = "verified"
    ISSUED = "issued"


class CarbonEstimate(Base):
    """Carbon estimate entity recording verified emission removals.

    Per PROJECT_SPEC.md Section 6 Rule 5: Every estimate stores inputs_snapshot
    and methodology_version so it can be reproduced exactly by third-party auditors.
    """

    __tablename__ = "carbon_estimates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    enrollment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("enrollments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    methodology_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("methodologies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    methodology_version: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )
    inputs_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    co2e_tonnes: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    uncertainty_pct: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    buffer_pct: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    net_credits: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    status: Mapped[EstimateStatus] = mapped_column(
        Enum(
            EstimateStatus,
            name="estimate_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=EstimateStatus.DRAFT,
        nullable=False,
        index=True,
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    # Relationships
    enrollment: Mapped["Enrollment"] = relationship("Enrollment")
    methodology: Mapped["Methodology"] = relationship("Methodology")

    def __repr__(self) -> str:
        return (
            f"<CarbonEstimate id={self.id} enrollment_id={self.enrollment_id} "
            f"version={self.methodology_version!r} net_credits={self.net_credits} status={self.status.value!r}>"
        )
