"""Farmer database model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.land_parcel import LandParcel


class Farmer(Base):
    """Farmer model representing agricultural landholders in carbon projects."""

    __tablename__ = "farmers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    village: Mapped[str | None] = mapped_column(String(255), nullable=True)
    district: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    state: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships (lazy="select" avoids loading child parcels when only querying farmers)
    parcels: Mapped[list["LandParcel"]] = relationship(
        "LandParcel",
        back_populates="farmer",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Farmer id={self.id} name={self.name!r} district={self.district!r} state={self.state!r}>"
