from fastapi import APIRouter, Depends, Query

from app.analytics import service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/current-status")
def current_status() -> list[dict]:
    return service.current_status()


@router.get("/forecast-status")
def forecast_status(year: int, week: int = Query(..., description="Quarter week: 13, 26, 39, or 52")) -> list[dict]:
    return service.forecast_status(year, week)


@router.get("/site-detail/{site_id}")
def site_detail(site_id: str) -> dict:
    return service.site_detail(site_id)


@router.get("/map-stats")
def map_stats(
    south: float, west: float, north: float, east: float,
    year: int | None = None, week: int | None = None,
) -> dict:
    return service.map_stats(south, west, north, east, year, week)


@router.get("/overview-stats")
def overview_stats() -> dict:
    return service.overview_stats()


def _filters(
    region: str | None = None,
    year: int | None = None,
    week: int | None = None,
    operator: str | None = None,
    cluster: str | None = None,
) -> service.Filters:
    return service.Filters(region=region, year=year, week=week, operator=operator, cluster=cluster)


@router.get("/filter-options")
def filter_options() -> dict:
    return service.filter_options()


@router.get("/summary")
def summary(filters: service.Filters = Depends(_filters)) -> dict:
    return service.summary_stats(filters)


@router.get("/sector-metrics")
def sector_metrics(
    filters: service.Filters = Depends(_filters), limit: int = 100, offset: int = 0
) -> list[dict]:
    return service.sector_metrics(filters, limit, offset)


@router.get("/congested-sectors")
def congested_sectors(
    filters: service.Filters = Depends(_filters), limit: int = 100, offset: int = 0
) -> list[dict]:
    return service.congested_sectors(filters, limit, offset)


@router.get("/forecast-table")
def forecast_table(
    filters: service.Filters = Depends(_filters), limit: int = 100, offset: int = 0
) -> list[dict]:
    return service.forecast_table(filters, limit, offset)
