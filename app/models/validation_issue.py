"""Validation issue database model storing rule violations and audit flags."""

from datetime import datetime
import enum
from typing import TYPE_CHECKING

from sqlalchemy import (
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
    from app.models.observation import Observation


class ValidationSeverity(str, enum.Enum):
    """Severity classification for validation rule violations."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ValidationIssue(Base):
    """Validation issue entity flagged by the automated validation pipeline.

    Observations with 'error'-severity validation issues are excluded from
    carbon credit calculations per PROJECT_SPEC.md Section 6 Rule 4.
    """

    __tablename__ = "validation_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    observation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("observations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    severity: Mapped[ValidationSeverity] = mapped_column(
        Enum(
            ValidationSeverity,
            name="validation_severity",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        index=True,
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationship to the monitored observation
    observation: Mapped["Observation"] = relationship("Observation")

    def __repr__(self) -> str:
        return (
            f"<ValidationIssue id={self.id} observation_id={self.observation_id} "
            f"rule={self.rule!r} severity={self.severity.value!r}>"
        )
