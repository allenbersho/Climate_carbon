"""Methodology database model storing calculation parameters and versioning."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Methodology(Base):
    """Methodology entity defining calculation formulas and parameters.

    Per PROJECT_SPEC.md Section 7, all calculation parameters live in the
    methodologies table (versioned) and are never hard-coded in calculators.
    """

    __tablename__ = "methodologies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_methodology_name_version"),
    )

    def __repr__(self) -> str:
        return f"<Methodology id={self.id} name={self.name!r} version={self.version!r} active={self.is_active}>"
