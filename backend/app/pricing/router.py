from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.auth.models import Role, User
from app.core.db import get_db
from app.pricing import service
from app.pricing.schemas import PriceUpsertRequest

router = APIRouter(prefix="/capex-pricing", tags=["pricing"])


@router.get("")
def get_pricing(db: Session = Depends(get_db)) -> dict[str, dict[str, float]]:
    return service.get_pricing(db)


@router.put("/{category}/{item_name}")
def upsert_price(
    category: str,
    item_name: str,
    payload: PriceUpsertRequest,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict[str, dict[str, float]]:
    try:
        service.upsert_price(db, category, item_name, payload.price, user.id)
    except service.InvalidCategoryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return service.get_pricing(db)
