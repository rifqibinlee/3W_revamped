"""Backend for the legacy split-screen feature (index.html's
toggleSplitScreen/_loadForecastMarkers): left pane shows current
congestion status, right pane shows forecast status for a selectable
quarter/year. Both endpoints join site coordinates so the frontend can
plot markers without a second round trip — matching what `siteDataCache`
+ `/api/forecast_data` did together in the legacy app.

Reads straight from the Parquet files Phase 1's ETL stages already
produce (congestion_analysis, forecast_results, site_coordinates) via
DuckDB — no separate analytics database, consistent with the rest of
this rebuild.
"""

from pathlib import Path

from app.analytics.db import get_connection
from app.core.config import settings


def _parquet_path(name: str) -> Path:
    return Path(settings.parquet_dir) / f"{name}.parquet"


def current_status() -> list[dict]:
    """Latest week's congestion status per site, joined with coordinates."""
    congestion_path = _parquet_path("congestion_analysis")
    sites_path = _parquet_path("site_coordinates")
    if not congestion_path.exists() or not sites_path.exists():
        return []

    con = get_connection()
    try:
        rows = con.execute(f"""
            WITH latest AS (
                SELECT *, row_number() OVER (
                    PARTITION BY zoom_sector_id ORDER BY year DESC, week DESC
                ) AS rn
                FROM read_parquet('{congestion_path}')
            )
            SELECT
                c.site_id, c.zoom_sector_id, c.region, c.congested,
                s.latitude, s.longitude
            FROM latest c
            LEFT JOIN read_parquet('{sites_path}') s ON c.site_id = s.site_id
            WHERE c.rn = 1
        """).fetchdf()
        return rows.to_dict("records")
    finally:
        con.close()


def forecast_status(year: int, week: int) -> list[dict]:
    """Forecast congestion status for a specific year/quarter-week (the
    legacy UI offers W13/W26/W39/W52), joined with coordinates."""
    forecast_path = _parquet_path("forecast_results")
    sites_path = _parquet_path("site_coordinates")
    if not forecast_path.exists() or not sites_path.exists():
        return []

    con = get_connection()
    try:
        rows = con.execute(f"""
            SELECT
                f.zoom_sector_id, f.congested, f.region,
                s.site_id, s.latitude, s.longitude
            FROM read_parquet('{forecast_path}') f
            LEFT JOIN read_parquet('{sites_path}') s
                ON split_part(f.zoom_sector_id, '_', 1) = s.site_id
            WHERE f.year = {year} AND f.week = {week}
        """).fetchdf()
        return rows.to_dict("records")
    finally:
        con.close()
