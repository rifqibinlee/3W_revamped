from fastapi import APIRouter, Query

from app.analytics import service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/current-status")
def current_status() -> list[dict]:
    return service.current_status()


@router.get("/forecast-status")
def forecast_status(year: int, week: int = Query(..., description="Quarter week: 13, 26, 39, or 52")) -> list[dict]:
    return service.forecast_status(year, week)
