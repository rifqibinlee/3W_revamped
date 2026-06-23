import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.capex_solver import DEFAULT_PRICING
from app.pricing.models import CapexPricingItem

VALID_CATEGORIES = ("EQ", "ES")

# Real negotiated price + range data, prepared outside the repo's tracked
# scripts_example/ folder (legacy reference scripts only, normally no real
# data). Optional — falls back to DEFAULT_PRICING with a zero-width range
# when absent, e.g. in production where this file is never deployed.
_REAL_PRICING_SEED_PATH = Path(__file__).resolve().parents[3] / "scripts_example" / "capex_pricing.json"


def _load_real_pricing_seed() -> dict[str, dict[str, dict[str, float]]] | None:
    if not _REAL_PRICING_SEED_PATH.exists():
        return None
    try:
        return json.loads(_REAL_PRICING_SEED_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


class InvalidCategoryError(Exception):
    pass


def get_pricing(db: Session) -> dict[str, dict[str, float]]:
    """Returns the same {"EQ": {...}, "ES": {...}} shape capex_solver
    consumes — falls back to DEFAULT_PRICING wholesale if the table is
    empty (fresh install, nobody's configured anything yet). Always the
    exact price: this is for internal calculation (capex_solver, the
    agent), not for the user-facing API — that goes through
    `get_pricing_detailed` + `redact_for_role` instead."""
    rows = list(db.scalars(select(CapexPricingItem)))
    if not rows:
        return DEFAULT_PRICING

    pricing: dict[str, dict[str, float]] = {"EQ": {}, "ES": {}}
    for row in rows:
        pricing[row.category][row.item_name] = row.price
    return pricing


def get_pricing_detailed(db: Session) -> dict[str, dict[str, dict[str, float]]]:
    """Admin-facing shape: each item carries both the exact price and its
    range. Falls back to DEFAULT_PRICING with a zero-width range when the
    table is empty."""
    rows = list(db.scalars(select(CapexPricingItem)))
    if not rows:
        return {
            category: {
                item_name: {"price": price, "price_min": price, "price_max": price}
                for item_name, price in items.items()
            }
            for category, items in DEFAULT_PRICING.items()
        }

    detailed: dict[str, dict[str, dict[str, float]]] = {"EQ": {}, "ES": {}}
    for row in rows:
        detailed[row.category][row.item_name] = {
            "price": row.price,
            "price_min": row.price_min if row.price_min is not None else row.price,
            "price_max": row.price_max if row.price_max is not None else row.price,
        }
    return detailed


def redact_for_role(detailed: dict[str, dict[str, dict[str, float]]], is_admin: bool) -> dict:
    """Non-admins get only the range — the exact negotiated price is
    admin-eyes-only."""
    if is_admin:
        return detailed
    return {
        category: {item_name: {"price_min": v["price_min"], "price_max": v["price_max"]} for item_name, v in items.items()}
        for category, items in detailed.items()
    }


def upsert_price(
    db: Session,
    category: str,
    item_name: str,
    price: float,
    updated_by_id: str | None,
    price_min: float | None = None,
    price_max: float | None = None,
) -> CapexPricingItem:
    if category not in VALID_CATEGORIES:
        raise InvalidCategoryError(f"category must be one of {VALID_CATEGORIES}, got {category!r}")

    existing = db.scalar(
        select(CapexPricingItem).where(
            CapexPricingItem.category == category, CapexPricingItem.item_name == item_name
        )
    )
    if existing:
        existing.price = price
        existing.price_min = price_min
        existing.price_max = price_max
        existing.updated_by_id = updated_by_id
        db.commit()
        db.refresh(existing)
        return existing

    item = CapexPricingItem(
        category=category, item_name=item_name, price=price,
        price_min=price_min, price_max=price_max, updated_by_id=updated_by_id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def seed_defaults_if_empty(db: Session) -> None:
    """One-time seed so the editable table starts from a real baseline
    rather than an admin having to re-type every price before changing
    one of them. Prefers the real price+range seed file when present
    (see _load_real_pricing_seed); falls back to capex_solver's flat
    DEFAULT_PRICING with a zero-width range otherwise."""
    if db.scalar(select(CapexPricingItem).limit(1)):
        return

    real_seed = _load_real_pricing_seed()
    if real_seed:
        for category, items in real_seed.items():
            for item_name, item in items.items():
                db.add(CapexPricingItem(
                    category=category, item_name=item_name, price=item["price"],
                    price_min=item.get("min"), price_max=item.get("max"),
                ))
    else:
        for category, items in DEFAULT_PRICING.items():
            for item_name, price in items.items():
                db.add(CapexPricingItem(category=category, item_name=item_name, price=price))
    db.commit()
