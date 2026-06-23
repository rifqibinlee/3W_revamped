from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_roles
from app.auth.models import Role, User
from app.core.db import get_db
from app.pricing import service
from app.pricing.schemas import PriceUpsertRequest

router = APIRouter(prefix="/capex-pricing", tags=["pricing"])


@router.get("")
def get_pricing(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    detailed = service.get_pricing_detailed(db)
    return service.redact_for_role(detailed, is_admin=user.role == Role.ADMIN)


@router.put("/{category}/{item_name}")
def upsert_price(
    category: str,
    item_name: str,
    payload: PriceUpsertRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    try:
        service.upsert_price(
            db, category, item_name, payload.price, user.id,
            price_min=payload.price_min, price_max=payload.price_max,
        )
    except service.InvalidCategoryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return service.get_pricing_detailed(db)
