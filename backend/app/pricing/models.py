import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CapexPricingItem(Base):
    """Mirrors the shape `capex_solver.DEFAULT_PRICING` already expects:
    two categories (EQ/ES), each a flat name -> price map. This table is
    the editable source of truth; capex_solver falls back to its
    hardcoded defaults only when this table is empty (e.g. fresh install
    before an admin has configured anything)."""

    __tablename__ = "capex_pricing_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    category: Mapped[str] = mapped_column(String(10))  # "EQ" or "ES"
    item_name: Mapped[str] = mapped_column(String(100))
    price: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    updated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
