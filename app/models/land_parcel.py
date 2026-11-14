"""Land parcel database model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.models.farmer import Farmer


class LandParcel(Base):
    """Land parcel entity representing distinct agricultural/forested land units."""

    __tablename__ = "land_parcels"
    __table_args__ = (
        CheckConstraint("area_acres > 0", name="check_positive_area_acres"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    farmer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("farmers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,  # Foreign key index for high-speed join queries
    )
    area_acres: Mapped[float] = mapped_column(Float, nullable=False)
    soil_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    crop: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    farmer: Mapped["Farmer"] = relationship("Farmer", back_populates="parcels")

    def __repr__(self) -> str:
        return f"<LandParcel id={self.id} farmer_id={self.farmer_id} area_acres={self.area_acres}>"
