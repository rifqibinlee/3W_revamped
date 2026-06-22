from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.capex_solver import DEFAULT_PRICING
from app.pricing.models import CapexPricingItem

VALID_CATEGORIES = ("EQ", "ES")


class InvalidCategoryError(Exception):
    pass


def get_pricing(db: Session) -> dict[str, dict[str, float]]:
    """Returns the same {"EQ": {...}, "ES": {...}} shape capex_solver
    consumes — falls back to DEFAULT_PRICING wholesale if the table is
    empty (fresh install, nobody's configured anything yet)."""
    rows = list(db.scalars(select(CapexPricingItem)))
    if not rows:
        return DEFAULT_PRICING

    pricing: dict[str, dict[str, float]] = {"EQ": {}, "ES": {}}
    for row in rows:
        pricing[row.category][row.item_name] = row.price
    return pricing


def upsert_price(db: Session, category: str, item_name: str, price: float, updated_by_id: str | None) -> CapexPricingItem:
    if category not in VALID_CATEGORIES:
        raise InvalidCategoryError(f"category must be one of {VALID_CATEGORIES}, got {category!r}")

    existing = db.scalar(
        select(CapexPricingItem).where(
            CapexPricingItem.category == category, CapexPricingItem.item_name == item_name
        )
    )
    if existing:
        existing.price = price
        existing.updated_by_id = updated_by_id
        db.commit()
        db.refresh(existing)
        return existing

    item = CapexPricingItem(category=category, item_name=item_name, price=price, updated_by_id=updated_by_id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def seed_defaults_if_empty(db: Session) -> None:
    """One-time seed so the editable table starts from the same baseline
    capex_solver's hardcoded fallback uses, rather than an admin having to
    re-type every price before changing one of them."""
    if db.scalar(select(CapexPricingItem).limit(1)):
        return
    for category, items in DEFAULT_PRICING.items():
        for item_name, price in items.items():
            db.add(CapexPricingItem(category=category, item_name=item_name, price=price))
    db.commit()
