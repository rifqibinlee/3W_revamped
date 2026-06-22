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


class Filters:
    """Filter bar from the legacy 'RAN Forecast' tab: region/year/week/
    operator/cluster, all optional. Values come from user input via the
    API, so the WHERE clause is built with `?` placeholders and bound
    parameters — never string-interpolated — unlike the ETL stages'
    queries, which only ever touch trusted internal file paths."""

    def __init__(
        self,
        region: str | None = None,
        year: int | None = None,
        week: int | None = None,
        operator: str | None = None,
        cluster: str | None = None,
    ):
        self.region = region
        self.year = year
        self.week = week
        self.operator = operator
        self.cluster = cluster

    def where_clause(self, table_alias: str = "") -> tuple[str, list]:
        prefix = f"{table_alias}." if table_alias else ""
        clauses: list[str] = []
        params: list = []
        if self.region and self.region != "All":
            clauses.append(f"{prefix}region = ?")
            params.append(self.region)
        if self.year is not None:
            clauses.append(f"{prefix}year = ?")
            params.append(self.year)
        if self.week is not None:
            clauses.append(f"{prefix}week = ?")
            params.append(self.week)
        if self.operator and self.operator != "All":
            clauses.append(f"{prefix}operator = ?")
            params.append(self.operator)
        if self.cluster:
            clauses.append(f"{prefix}cluster = ?")
            params.append(self.cluster)
        sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return sql, params


def sector_metrics(filters: Filters, limit: int = 100, offset: int = 0) -> list[dict]:
    """The 'Sector Performance Metrics' table: every sector row from
    congestion_analysis, unfiltered by congestion status (that's the
    separate Congested Sectors table below)."""
    path = _parquet_path("congestion_analysis")
    if not path.exists():
        return []
    con = get_connection()
    try:
        where_sql, params = filters.where_clause()
        rows = con.execute(
            f"SELECT * FROM read_parquet('{path}'){where_sql} ORDER BY year DESC, week DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchdf()
        return rows.to_dict("records")
    finally:
        con.close()


def congested_sectors(filters: Filters, limit: int = 100, offset: int = 0) -> list[dict]:
    """The 'Congested Sectors' table — same source, congested = true only."""
    path = _parquet_path("congestion_analysis")
    if not path.exists():
        return []
    con = get_connection()
    try:
        where_sql, params = filters.where_clause()
        congested_clause = " AND congested = true" if where_sql else " WHERE congested = true"
        rows = con.execute(
            f"SELECT * FROM read_parquet('{path}'){where_sql}{congested_clause} "
            "ORDER BY year DESC, week DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchdf()
        return rows.to_dict("records")
    finally:
        con.close()


def forecast_table(filters: Filters, limit: int = 100, offset: int = 0) -> list[dict]:
    """The 'Future Performance Forecasts' table."""
    path = _parquet_path("forecast_results")
    if not path.exists():
        return []
    con = get_connection()
    try:
        where_sql, params = filters.where_clause()
        rows = con.execute(
            f"SELECT * FROM read_parquet('{path}'){where_sql} ORDER BY year, week LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchdf()
        return rows.to_dict("records")
    finally:
        con.close()


def summary_stats(filters: Filters) -> dict:
    """The three stat tiles above the tables: total sectors, congested
    count, average data volume (GB)."""
    path = _parquet_path("congestion_analysis")
    if not path.exists():
        return {"total_sectors": 0, "congested_count": 0, "avg_volume_gb": 0.0}
    con = get_connection()
    try:
        where_sql, params = filters.where_clause()
        row = con.execute(
            f"""
            SELECT
                count(DISTINCT zoom_sector_id) AS total_sectors,
                count(DISTINCT CASE WHEN congested THEN zoom_sector_id END) AS congested_count,
                avg(eric_data_volume_ul_dl) AS avg_volume_gb
            FROM read_parquet('{path}'){where_sql}
            """,
            params,
        ).fetchone()
        return {
            "total_sectors": row[0] or 0,
            "congested_count": row[1] or 0,
            "avg_volume_gb": round(row[2], 2) if row[2] is not None else 0.0,
        }
    finally:
        con.close()


def filter_options() -> dict:
    """Populates the filter bar's dropdowns from whatever data actually
    exists, rather than a hardcoded list — matches the legacy UI's
    dynamically-populated Region/Year/Week selects."""
    path = _parquet_path("congestion_analysis")
    if not path.exists():
        return {"regions": [], "years": [], "weeks": [], "operators": []}
    con = get_connection()
    try:
        regions = [r[0] for r in con.execute(f"SELECT DISTINCT region FROM read_parquet('{path}') ORDER BY 1").fetchall()]
        years = [r[0] for r in con.execute(f"SELECT DISTINCT year FROM read_parquet('{path}') ORDER BY 1 DESC").fetchall()]
        weeks = [r[0] for r in con.execute(f"SELECT DISTINCT week FROM read_parquet('{path}') ORDER BY 1").fetchall()]
        operators = [r[0] for r in con.execute(f"SELECT DISTINCT operator FROM read_parquet('{path}') ORDER BY 1").fetchall()]
        return {"regions": regions, "years": years, "weeks": weeks, "operators": operators}
    finally:
        con.close()
