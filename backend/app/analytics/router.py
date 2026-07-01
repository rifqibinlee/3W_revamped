from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.analytics import service
from app.core.config import settings

router = APIRouter(prefix="/analytics", tags=["analytics"])

# The three downloadable reports the legacy app served from S3 presigned
# URLs (/download/cd_file, /download/sector, /download/congested) — the
# cd_combined_result ETL stage already writes these CSVs straight into
# parquet_dir as one of its three outputs, so this just serves the file
# that's already sitting there instead of needing S3 at all.
_DOWNLOADABLE_REPORTS = {
    "cd-combined": "CD_Combined_Results.csv",
    "sector-metrics": "Sector_Metrics.csv",
    "congested-sectors": "Congested_Sectors.csv",
}


@router.get("/download/{report}")
def download_report(report: str) -> FileResponse:
    filename = _DOWNLOADABLE_REPORTS.get(report)
    if filename is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown report '{report}'")
    path = Path(settings.parquet_dir) / filename
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{filename} hasn't been generated yet — run the ETL pipeline first")
    return FileResponse(path, filename=filename, media_type="text/csv")


@router.get("/available-weeks")
def available_weeks() -> list[dict]:
    """Distinct (year, week) pairs present in congestion_analysis, newest first."""
    return service.available_weeks()


@router.get("/current-status")
def current_status(year: int | None = None, week: int | None = None) -> list[dict]:
    return service.current_status(year, week)


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


@router.get("/geoserver-layers")
def geoserver_layers() -> list[dict]:
    return service.geoserver_layers()


@router.get("/geoserver-fixed-layers")
def geoserver_fixed_layers() -> dict:
    """The fixed substations/buildings layer names the Genset and
    Bitcoin-mining tools always query — not user-selectable, see
    Settings.geoserver_substations_layer/geoserver_buildings_layer."""
    return {"substations_layer": settings.geoserver_substations_layer, "buildings_layer": settings.geoserver_buildings_layer}


@router.get("/nearby-geoserver-features")
def nearby_geoserver_features(layer: str, lat: float, lng: float, radius_m: float = 2500) -> list[dict]:
    return service.nearby_geoserver_features(layer, lat, lng, radius_m)


@router.get("/site-coverage")
def site_coverage(south: float, west: float, north: float, east: float) -> list[dict]:
    return service.site_coverage(south, west, north, east)


@router.get("/coverage-holes-by-band")
def coverage_holes_by_band(
    south: float, west: float, north: float, east: float,
    band: str = Query(..., description="One of: high (-100 to -120 dBm), mid (-121 to -130), low (<-130)"),
) -> list[dict]:
    try:
        return service.coverage_holes_by_band(south, west, north, east, band)
    except service.InvalidMetricError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/site-forecast/{site_id}")
def site_forecast(
    site_id: str,
    metric: str = "eric_prb_util_rate",
    horizon_weeks: int = Query(8, ge=1, le=52),
) -> dict:
    try:
        return service.site_forecast(site_id, metric, horizon_weeks)
    except service.InvalidMetricError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _filters(
    region: str | None = None,
    year: int | None = None,
    week: int | None = None,
    operator: str | None = None,
    cluster: str | None = None,
    search: str | None = None,
) -> service.Filters:
    return service.Filters(region=region, year=year, week=week, operator=operator, cluster=cluster, search=search)


@router.get("/filter-options")
def filter_options() -> dict:
    return service.filter_options()


@router.get("/summary")
def summary(filters: service.Filters = Depends(_filters)) -> dict:
    return service.summary_stats(filters)


@router.get("/capex-summary")
def capex_summary(region: str | None = None, search: str | None = None) -> dict:
    return service.capex_summary(region=region, search=search)


@router.get("/sector-metrics")
def sector_metrics(
    filters: service.Filters = Depends(_filters), limit: int = 100, offset: int = 0
) -> dict:
    return service.sector_metrics(filters, limit, offset)


@router.get("/congested-sectors")
def congested_sectors(
    filters: service.Filters = Depends(_filters), limit: int = 100, offset: int = 0
) -> dict:
    return service.congested_sectors(filters, limit, offset)


@router.get("/forecast-table")
def forecast_table(
    filters: service.Filters = Depends(_filters), limit: int = 100, offset: int = 0
) -> dict:
    return service.forecast_table(filters, limit, offset)
