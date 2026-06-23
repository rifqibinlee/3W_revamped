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
    before an admin has configured anything).

    Two pricing tiers: `price` is the exact, admin-only-visible figure
    used for real capex calculations (capex_solver, the agent). `price_min`/
    `price_max` is the range non-admin users see instead — staff doing
    budget estimates don't need (or get to see) the exact negotiated
    vendor price. Both are admin-editable; the range defaults to the
    exact price (a zero-width range) if the admin doesn't set one."""

    __tablename__ = "capex_pricing_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    category: Mapped[str] = mapped_column(String(10))  # "EQ" or "ES"
    item_name: Mapped[str] = mapped_column(String(100))
    price: Mapped[float] = mapped_column(Float)
    price_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    updated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
