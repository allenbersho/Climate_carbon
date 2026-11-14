"""Observation database model recording field measurements and monitoring data."""

from datetime import datetime
import enum
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    func,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.validation_issue import ValidationSeverity

if TYPE_CHECKING:
    from app.models.enrollment import Enrollment
    from app.models.user import User
    from app.models.validation_issue import ValidationIssue


class ObservationType(str, enum.Enum):
    """Categorization of monitoring measurements."""

    SOIL = "soil"
    TREE_COUNT = "tree_count"
    BIOMASS = "biomass"


class Observation(Base):
    """Append-only monitoring observation entity.

    Observations are never mutated or deleted; corrections create a new row
    and populate superseded_by on the prior row.
    """

    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    enrollment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("enrollments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    type: Mapped[ObservationType] = mapped_column(
        Enum(
            ObservationType,
            name="observation_type",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        index=True,
    )
    values: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    observer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_baseline: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    superseded_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("observations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    enrollment: Mapped["Enrollment"] = relationship("Enrollment")
    observer: Mapped["User"] = relationship("User")
    superseding_observation: Mapped["Observation | None"] = relationship(
        "Observation",
        remote_side=[id],
        foreign_keys=[superseded_by],
    )
    validation_issues: Mapped[list["ValidationIssue"]] = relationship(
        "ValidationIssue",
        back_populates="observation",
        cascade="all, delete-orphan",
        order_by="ValidationIssue.id.asc()",
    )

    @hybrid_property
    def excluded_from_estimation(self) -> bool:
        """True if any error-severity validation issue excludes this observation from carbon estimation."""
        return any(issue.severity == ValidationSeverity.ERROR for issue in self.validation_issues)

    @excluded_from_estimation.expression
    def excluded_from_estimation(cls):
        from app.models.validation_issue import ValidationIssue

        return cls.validation_issues.any(ValidationIssue.severity == ValidationSeverity.ERROR)

    @hybrid_property
    def is_valid(self) -> bool:
        """True if the observation has zero error-severity validation issues."""
        return not self.excluded_from_estimation

    @is_valid.expression
    def is_valid(cls):
        return ~cls.excluded_from_estimation

    @property
    def issues(self) -> list["ValidationIssue"]:
        """Alias returning the list of validation issues."""
        return self.validation_issues

    def __repr__(self) -> str:
        return (
            f"<Observation id={self.id} enrollment_id={self.enrollment_id} "
            f"type={self.type.value!r} baseline={self.is_baseline} superseded_by={self.superseded_by}>"
        )
