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

from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree

import httpx
import numpy as np
from scipy import stats
from sklearn.linear_model import LinearRegression

from app.analytics.db import get_connection
from app.core.config import settings


def _parquet_path(name: str) -> Path:
    return Path(settings.parquet_dir) / f"{name}.parquet"


FORECAST_METRICS = ("eric_data_volume_ul_dl", "eric_prb_util_rate", "eric_dl_user_ip_thpt")

# Metrics that can never go negative or (for a rate) above 100 — the
# legacy /plot endpoint clamps its confidence band to "plausible bounds"
# the same way; without this a wide band on a short history can dip the
# lower bound below zero or push a percentage past 100.
_METRIC_BOUNDS: dict[str, tuple[float, float | None]] = {
    "eric_data_volume_ul_dl": (0.0, None),
    "eric_prb_util_rate": (0.0, 100.0),
    "eric_dl_user_ip_thpt": (0.0, None),
}


class InvalidMetricError(Exception):
    pass


def site_forecast(site_id: str, metric: str, horizon_weeks: int = 8) -> dict:
    """Live linear-regression forecast for one site's weekly metric
    history, with a 95% prediction interval — ports the legacy /plot
    endpoint's method (sklearn LinearRegression over days-since-start,
    scipy.stats.t for the band) rather than reading the separately
    precomputed forecast_results table, which is a different (ML-model)
    forecast already used elsewhere (site-detail, the split-screen map)."""
    if metric not in FORECAST_METRICS:
        raise InvalidMetricError(f"metric must be one of {FORECAST_METRICS}, got {metric!r}")

    path = _parquet_path("congestion_analysis")
    empty = {"site_id": site_id.upper(), "metric": metric, "actual": [], "forecast": []}
    if not path.exists():
        return empty

    con = get_connection()
    try:
        rows = con.execute(
            f"""
            SELECT year, week, avg({metric}) AS value
            FROM read_parquet('{path}')
            WHERE site_id = ?
            GROUP BY year, week
            ORDER BY year, week
            """,
            [site_id.upper()],
        ).fetchall()
    finally:
        con.close()

    if not rows:
        return empty

    dates = [date.fromisocalendar(year, week, 1) for year, week, _ in rows]
    values = [v for _, _, v in rows]
    start = dates[0]
    x = np.array([(d - start).days for d in dates], dtype=float).reshape(-1, 1)
    y = np.array(values, dtype=float)

    actual = [{"date": d.isoformat(), "value": v} for d, v in zip(dates, values)]

    if len(rows) < 2:
        return {"site_id": site_id.upper(), "metric": metric, "actual": actual, "forecast": []}

    model = LinearRegression().fit(x, y)
    residuals = y - model.predict(x)
    dof = max(len(x) - 2, 1)
    residual_std = float(np.sqrt(np.sum(residuals**2) / dof)) if dof > 0 else 0.0
    x_mean = float(x.mean())
    ss_x = float(np.sum((x.flatten() - x_mean) ** 2)) or 1.0
    t_value = float(stats.t.ppf(0.975, df=dof))

    lower_bound, upper_bound = _METRIC_BOUNDS.get(metric, (None, None))

    forecast = []
    last_day = x.flatten()[-1]
    for week_ahead in range(1, horizon_weeks + 1):
        x0 = last_day + week_ahead * 7
        pred = float(model.predict([[x0]])[0])
        se = residual_std * np.sqrt(1 + 1 / len(x) + (x0 - x_mean) ** 2 / ss_x)
        margin = t_value * se
        lo, hi = pred - margin, pred + margin
        if lower_bound is not None:
            lo = max(lo, lower_bound)
            pred = max(pred, lower_bound)
        if upper_bound is not None:
            hi = min(hi, upper_bound)
            pred = min(pred, upper_bound)
        forecast.append({
            "date": (start + timedelta(days=x0)).isoformat(),
            "value": pred,
            "ci_lower": lo,
            "ci_upper": hi,
        })

    return {"site_id": site_id.upper(), "metric": metric, "actual": actual, "forecast": forecast}


def sector_current_status(zoom_sector_id: str) -> dict | None:
    """Latest-week congestion status for one specific SECTOR (not site)
    — used by the agent's tools, which look up a sector by its exact
    zoom_sector_id rather than wanting the per-site rollup current_status()
    returns for the map."""
    congestion_path = _parquet_path("congestion_analysis")
    if not congestion_path.exists():
        return None
    con = get_connection()
    try:
        row = con.execute(
            f"""
            WITH latest AS (
                SELECT *, row_number() OVER (
                    PARTITION BY zoom_sector_id ORDER BY year DESC, week DESC
                ) AS rn FROM read_parquet('{congestion_path}')
            )
            SELECT site_id, zoom_sector_id, region, congested FROM latest WHERE rn = 1 AND zoom_sector_id = ?
            """,
            [zoom_sector_id],
        ).fetchone()
        if not row:
            return None
        return {"site_id": row[0], "zoom_sector_id": row[1], "region": row[2], "congested": row[3]}
    finally:
        con.close()


def sector_forecast_status(zoom_sector_id: str, year: int, week: int) -> dict | None:
    """Forecast status for one specific SECTOR at a year/week — same
    per-sector vs. per-site distinction as sector_current_status()."""
    forecast_path = _parquet_path("forecast_results")
    if not forecast_path.exists():
        return None
    con = get_connection()
    try:
        row = con.execute(
            f"SELECT zoom_sector_id, congested FROM read_parquet('{forecast_path}') WHERE zoom_sector_id = ? AND year = ? AND week = ?",
            [zoom_sector_id, year, week],
        ).fetchone()
        if not row:
            return None
        return {"zoom_sector_id": row[0], "congested": row[1], "year": year, "week": week}
    finally:
        con.close()


def current_status() -> list[dict]:
    """Latest week's congestion status per site, joined with coordinates.

    One row per SITE, not per sector — congestion_analysis has ~2.9
    sectors per site on average (17,650 sectors across 6,024 sites in
    the real dataset), and a naive per-sector query produces several
    markers stacked at the exact same coordinate, wildly inflating the
    map's apparent site/cluster counts versus the "Total sites" stat
    everywhere else on the page. A site counts as congested here if
    any of its sectors are congested in their latest week."""
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
            ),
            per_site AS (
                SELECT site_id, any_value(region) AS region, bool_or(congested) AS congested
                FROM latest WHERE rn = 1
                GROUP BY site_id
            )
            SELECT p.site_id, p.region, p.congested, s.latitude, s.longitude
            FROM per_site p
            LEFT JOIN read_parquet('{sites_path}') s ON p.site_id = s.site_id
        """).fetchdf()
        return rows.to_dict("records")
    finally:
        con.close()


def forecast_status(year: int, week: int) -> list[dict]:
    """Forecast congestion status for a specific year/quarter-week (the
    legacy UI offers W13/W26/W39/W52), joined with coordinates. Region
    comes from the site join — forecast_results itself has no region
    column (it's per-sector, not joined to site data).

    One row per SITE, not per sector — same reasoning as current_status:
    avoids stacking several markers at the same coordinate and keeps
    this in line with the "Total sites" count used everywhere else."""
    forecast_path = _parquet_path("forecast_results")
    sites_path = _parquet_path("site_coordinates")
    if not forecast_path.exists() or not sites_path.exists():
        return []

    con = get_connection()
    try:
        rows = con.execute(
            f"""
            WITH per_site AS (
                SELECT split_part(zoom_sector_id, '_', 1) AS site_id, bool_or(congested) AS congested
                FROM read_parquet('{forecast_path}')
                WHERE year = ? AND week = ?
                GROUP BY site_id
            )
            SELECT p.site_id, p.congested, s.region, s.latitude, s.longitude
            FROM per_site p
            LEFT JOIN read_parquet('{sites_path}') s ON p.site_id = s.site_id
            """,
            [year, week],
        ).fetchdf()
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
        search: str | None = None,
    ):
        self.region = region
        self.year = year
        self.week = week
        self.operator = operator
        self.cluster = cluster
        # Substring match against zoom_sector_id — that column already
        # carries the site_id as its prefix (e.g. "SITE001_Macro_1"), so
        # one search box covers both "find this site" and "find this
        # exact sector" without needing a separate site_id column.
        self.search = search

    def where_clause(self, table_alias: str = "", available_columns: tuple[str, ...] | None = None) -> tuple[str, list]:
        """available_columns restricts which filters apply — forecast_results
        has no region/cluster column (it's per-sector, not joined to site
        data), so passing available_columns=("year","week","operator") there
        avoids a DuckDB BinderException for the columns it doesn't have,
        rather than silently filtering all other tables down to nothing."""
        def _has(col: str) -> bool:
            return available_columns is None or col in available_columns

        prefix = f"{table_alias}." if table_alias else ""
        clauses: list[str] = []
        params: list = []
        if self.region and self.region != "All" and _has("region"):
            clauses.append(f"{prefix}region = ?")
            params.append(self.region)
        if self.year is not None and _has("year"):
            clauses.append(f"{prefix}year = ?")
            params.append(self.year)
        if self.week is not None and _has("week"):
            clauses.append(f"{prefix}week = ?")
            params.append(self.week)
        if self.operator and self.operator != "All" and _has("operator"):
            clauses.append(f"{prefix}operator = ?")
            params.append(self.operator)
        if self.cluster and _has("cluster"):
            clauses.append(f"{prefix}cluster = ?")
            params.append(self.cluster)
        if self.search and _has("zoom_sector_id"):
            clauses.append(f"LOWER({prefix}zoom_sector_id) LIKE LOWER(?)")
            params.append(f"%{self.search}%")
        sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return sql, params


def sector_metrics(filters: Filters, limit: int = 100, offset: int = 0) -> dict:
    """The 'Sector Performance Metrics' table: every sector row from
    congestion_analysis, unfiltered by congestion status (that's the
    separate Congested Sectors table below). Returns the page alongside
    the total matching row count so the frontend can paginate the real
    (often much larger than one page) result set instead of silently
    truncating to whatever `limit` happens to default to."""
    path = _parquet_path("congestion_analysis")
    if not path.exists():
        return {"rows": [], "total": 0}
    con = get_connection()
    try:
        where_sql, params = filters.where_clause()
        total = con.execute(f"SELECT count(*) FROM read_parquet('{path}'){where_sql}", params).fetchone()[0]
        rows = con.execute(
            f"SELECT * FROM read_parquet('{path}'){where_sql} ORDER BY year DESC, week DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchdf()
        return {"rows": rows.to_dict("records"), "total": total}
    finally:
        con.close()


def congested_sectors(filters: Filters, limit: int = 100, offset: int = 0) -> dict:
    """The 'Congested Sectors' table — same source, congested = true only."""
    path = _parquet_path("congestion_analysis")
    if not path.exists():
        return {"rows": [], "total": 0}
    con = get_connection()
    try:
        where_sql, params = filters.where_clause()
        congested_clause = " AND congested = true" if where_sql else " WHERE congested = true"
        total = con.execute(
            f"SELECT count(*) FROM read_parquet('{path}'){where_sql}{congested_clause}", params
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT * FROM read_parquet('{path}'){where_sql}{congested_clause} "
            "ORDER BY year DESC, week DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchdf()
        return {"rows": rows.to_dict("records"), "total": total}
    finally:
        con.close()


def forecast_table(filters: Filters, limit: int = 100, offset: int = 0) -> dict:
    """The 'Future Performance Forecasts' table. forecast_results has no
    region/cluster column (it's per-sector, not joined to site data), so
    only year/week/operator filters apply here."""
    path = _parquet_path("forecast_results")
    if not path.exists():
        return {"rows": [], "total": 0}
    con = get_connection()
    try:
        where_sql, params = filters.where_clause(available_columns=("year", "week", "operator", "zoom_sector_id"))
        total = con.execute(f"SELECT count(*) FROM read_parquet('{path}'){where_sql}", params).fetchone()[0]
        rows = con.execute(
            f"SELECT * FROM read_parquet('{path}'){where_sql} ORDER BY year, week LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchdf()
        return {"rows": rows.to_dict("records"), "total": total}
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


def site_detail(site_id: str) -> dict:
    """Everything the map's site popup needs in one round trip: site info,
    current per-sector KPIs (congested/healthy + the raw network
    parameters), forecast for the same sectors, and a CAPEX upgrade
    recommendation if one was computed for any of them — mirrors the
    legacy popup's KPI tab + CONFIG & UPGRADE tab combined."""
    site_id = site_id.upper()
    sites_path = _parquet_path("site_coordinates")
    congestion_path = _parquet_path("congestion_analysis")
    forecast_path = _parquet_path("forecast_results")
    capex_glob = str(Path(settings.parquet_dir) / "capex_upgrades_*.parquet")
    capex_files = list(Path(settings.parquet_dir).glob("capex_upgrades_*.parquet")) if Path(settings.parquet_dir).exists() else []

    if not sites_path.exists() and not congestion_path.exists() and not forecast_path.exists() and not capex_files:
        return {"site": None, "congested": False, "sectors": [], "forecast": [], "capex_upgrades": []}

    con = get_connection()
    try:
        site_row = None
        if sites_path.exists():
            row = con.execute(
                f"SELECT site_id, region, cluster, latitude, longitude FROM read_parquet('{sites_path}') WHERE site_id = ?",
                [site_id],
            ).fetchone()
            if row:
                site_row = {"site_id": row[0], "region": row[1], "cluster": row[2], "latitude": row[3], "longitude": row[4]}

        sectors: list[dict] = []
        if congestion_path.exists():
            df = con.execute(
                f"""
                WITH latest AS (
                    SELECT *, row_number() OVER (
                        PARTITION BY zoom_sector_id ORDER BY year DESC, week DESC
                    ) AS rn
                    FROM read_parquet('{congestion_path}')
                    WHERE site_id = ?
                )
                SELECT * FROM latest WHERE rn = 1
                """,
                [site_id],
            ).fetchdf()
            sectors = df.drop(columns=["rn"], errors="ignore").to_dict("records")

        forecast: list[dict] = []
        if forecast_path.exists():
            df = con.execute(
                f"""
                SELECT * FROM read_parquet('{forecast_path}')
                WHERE split_part(zoom_sector_id, '_', 1) = ?
                ORDER BY year, week
                """,
                [site_id],
            ).fetchdf()
            forecast = df.to_dict("records")

        capex: list[dict] = []
        if capex_files:
            df = con.execute(
                f"""
                SELECT * FROM read_parquet('{capex_glob}')
                WHERE split_part(zoom_sector_id, '_', 1) = ?
                """,
                [site_id],
            ).fetchdf()
            capex = df.to_dict("records")

        return {
            "site": site_row,
            "congested": any(s.get("congested") for s in sectors),
            "sectors": sectors,
            "forecast": forecast,
            "capex_upgrades": capex,
        }
    finally:
        con.close()


def _capex_glob() -> str:
    return str(Path(settings.parquet_dir) / "capex_upgrades_*.parquet")


def capex_summary(region: str | None = None, search: str | None = None) -> dict:
    """Backs the Dashboard's CAPEX section: headline total (same flat
    sum over every capex_upgrades_*.parquet row already used by
    overview_stats/map_stats — capex_upgrades has ~3 rows per sector
    across the dataset's sample weeks, summed as-is for consistency
    with those existing totals rather than introducing a different,
    non-reconciling number here), a breakdown by suggested upgrade
    case, a breakdown by region, and the sites needing the most CAPEX."""
    capex_files = _capex_files()
    if not capex_files:
        return {"total_capex": 0.0, "by_case": [], "by_region": [], "top_sites": []}

    sites_path = _parquet_path("site_coordinates")
    con = get_connection()
    try:
        join_clause = (
            f"LEFT JOIN read_parquet('{sites_path}') s ON split_part(cu.zoom_sector_id, '_', 1) = s.site_id"
            if sites_path.exists() else ""
        )
        region_col = "s.region" if sites_path.exists() else "NULL"

        clauses: list[str] = []
        params: list = []
        if region and region != "All" and sites_path.exists():
            clauses.append(f"{region_col} = ?")
            params.append(region)
        if search:
            clauses.append("LOWER(cu.zoom_sector_id) LIKE LOWER(?)")
            params.append(f"%{search}%")
        where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        base = f"FROM read_parquet('{_capex_glob()}') cu {join_clause}{where_sql}"

        total_row = con.execute(f"SELECT sum(cu.estimated_total_capex_rm) {base}", params).fetchone()
        total_capex = round(total_row[0], 2) if total_row and total_row[0] is not None else 0.0

        by_case = con.execute(
            f"""
            SELECT COALESCE(cu.suggested_upgrade_case, 'Unknown') AS upgrade_case,
                   count(DISTINCT cu.zoom_sector_id) AS sector_count,
                   sum(cu.estimated_total_capex_rm) AS total_capex_rm
            {base}
            GROUP BY 1 ORDER BY total_capex_rm DESC LIMIT 10
            """,
            params,
        ).fetchdf()

        by_region = (
            con.execute(
                f"""
                SELECT COALESCE({region_col}, 'Unknown') AS region,
                       count(DISTINCT cu.zoom_sector_id) AS sector_count,
                       sum(cu.estimated_total_capex_rm) AS total_capex_rm
                {base}
                GROUP BY 1 ORDER BY total_capex_rm DESC
                """,
                params,
            ).fetchdf()
            if sites_path.exists()
            else None
        )

        top_sites = con.execute(
            f"""
            SELECT split_part(cu.zoom_sector_id, '_', 1) AS site_id, {region_col} AS region,
                   count(DISTINCT cu.zoom_sector_id) AS sector_count,
                   sum(cu.estimated_total_capex_rm) AS total_capex_rm
            {base}
            GROUP BY 1, 2 ORDER BY total_capex_rm DESC LIMIT 15
            """,
            params,
        ).fetchdf()

        return {
            "total_capex": total_capex,
            "by_case": by_case.to_dict("records"),
            "by_region": by_region.to_dict("records") if by_region is not None else [],
            "top_sites": top_sites.to_dict("records"),
        }
    finally:
        con.close()


def _capex_files() -> list[Path]:
    if not Path(settings.parquet_dir).exists():
        return []
    return list(Path(settings.parquet_dir).glob("capex_upgrades_*.parquet"))


_EMPTY_MAP_STATS = {
    "total_sites": 0, "congested_sites": 0, "healthy_sites": 0,
    "coverage_holes": 0, "worst_coverage_hole": None, "total_capex": 0.0,
}


def map_stats(
    south: float, west: float, north: float, east: float,
    year: int | None = None, week: int | None = None,
) -> dict:
    """Stats scoped to the map's current viewport — the bbox the user is
    actually looking at, not the whole network. Forecast mode (year+week
    given) swaps the congestion source to forecast_results, matching the
    split-screen's right pane."""
    sites_path = _parquet_path("site_coordinates")
    congestion_path = _parquet_path("congestion_analysis")
    forecast_path = _parquet_path("forecast_results")
    holes_path = _parquet_path("coverage_holes")
    capex_files = _capex_files()

    if not sites_path.exists():
        return dict(_EMPTY_MAP_STATS)

    con = get_connection()
    try:
        bbox_clause = "s.longitude BETWEEN ? AND ? AND s.latitude BETWEEN ? AND ?"
        bbox_params = [west, east, south, north]

        total_sites = congested_sites = healthy_sites = 0
        if year is not None and week is not None and forecast_path.exists():
            row = con.execute(
                f"""
                WITH per_site AS (
                    SELECT s.site_id, bool_or(f.congested) AS congested
                    FROM read_parquet('{sites_path}') s
                    JOIN read_parquet('{forecast_path}') f
                        ON split_part(f.zoom_sector_id, '_', 1) = s.site_id
                    WHERE f.year = ? AND f.week = ? AND {bbox_clause}
                    GROUP BY s.site_id
                )
                SELECT count(*), count(*) FILTER (WHERE congested) FROM per_site
                """,
                [year, week] + bbox_params,
            ).fetchone()
            total_sites, congested_sites = row[0] or 0, row[1] or 0
        elif congestion_path.exists():
            row = con.execute(
                f"""
                WITH latest AS (
                    SELECT *, row_number() OVER (
                        PARTITION BY zoom_sector_id ORDER BY year DESC, week DESC
                    ) AS rn FROM read_parquet('{congestion_path}')
                ),
                per_site AS (
                    SELECT s.site_id, bool_or(c.congested) AS congested
                    FROM read_parquet('{sites_path}') s
                    JOIN latest c ON c.rn = 1 AND c.site_id = s.site_id
                    WHERE {bbox_clause}
                    GROUP BY s.site_id
                )
                SELECT count(*), count(*) FILTER (WHERE congested) FROM per_site
                """,
                bbox_params,
            ).fetchone()
            total_sites, congested_sites = row[0] or 0, row[1] or 0
        healthy_sites = total_sites - congested_sites

        coverage_holes = 0
        worst_hole = None
        if holes_path.exists():
            top = con.execute(
                f"""
                SELECT cluster_id, data_source, count(*) AS point_count, avg(signal_strength) AS avg_signal
                FROM read_parquet('{holes_path}')
                WHERE cluster_id != -1 AND longitude BETWEEN ? AND ? AND latitude BETWEEN ? AND ?
                GROUP BY cluster_id, data_source
                ORDER BY point_count DESC
                LIMIT 1
                """,
                bbox_params,
            ).fetchone()
            count_row = con.execute(
                f"""
                SELECT count(DISTINCT cluster_id) FROM read_parquet('{holes_path}')
                WHERE cluster_id != -1 AND longitude BETWEEN ? AND ? AND latitude BETWEEN ? AND ?
                """,
                bbox_params,
            ).fetchone()
            coverage_holes = count_row[0] or 0
            if top:
                worst_hole = {
                    "cluster_id": top[0], "data_source": top[1],
                    "point_count": top[2], "avg_signal": round(top[3], 1) if top[3] is not None else None,
                }

        total_capex = 0.0
        if capex_files:
            row = con.execute(
                f"""
                SELECT sum(cu.estimated_total_capex_rm)
                FROM read_parquet('{_capex_glob()}') cu
                JOIN read_parquet('{sites_path}') s ON split_part(cu.zoom_sector_id, '_', 1) = s.site_id
                WHERE {bbox_clause}
                """,
                bbox_params,
            ).fetchone()
            total_capex = round(row[0], 2) if row and row[0] is not None else 0.0

        return {
            "total_sites": total_sites, "congested_sites": congested_sites, "healthy_sites": healthy_sites,
            "coverage_holes": coverage_holes, "worst_coverage_hole": worst_hole, "total_capex": total_capex,
        }
    finally:
        con.close()


# site_coverage_params.technology is messy vendor export data (raw
# values seen in the real dataset_example export include '1', '3',
# '7', '8', '0', 'GSM900', 'DCS1800', 'G1800', 'E-GSM900', 'L9', 'L18',
# 'L21', 'L26', 'L900'..'L2600', 'NBIOT', '2G'/'3G'/'4G' explicit
# strings, 'Unknown', 'nan', and NULL) — there's no documented mapping
# from the numeric codes to a generation, so this only buckets the
# values we can classify with confidence (explicit G-strings, GSM/DCS
# band names = 2G, L-prefixed LTE band numbers = 4G) and drops
# everything else rather than guessing. No 5G site exists in the
# current dataset, so that bucket is wired up but will always be empty.
_TECH_BUCKET_SQL = """
    CASE
        WHEN technology = '5G' THEN '5G'
        WHEN technology = '4G' OR technology LIKE 'L%' OR technology = 'NBIOT' THEN '4G'
        WHEN technology = '3G' THEN '3G'
        WHEN technology = '2G' OR technology LIKE 'GSM%' OR technology LIKE 'DCS%' OR technology LIKE 'G%800%'
             OR technology LIKE 'E-GSM%' THEN '2G'
    END
"""


def site_coverage(south: float, west: float, north: float, east: float) -> list[dict]:
    """Per-cell coverage wedge inputs (site position + azimuth + radius,
    bucketed by technology generation) for the map's coverage-by-tech
    toggle — client draws the actual sector wedge geometry, this just
    supplies the real per-cell parameters behind it."""
    sites_path = _parquet_path("site_coordinates")
    params_path = _parquet_path("site_coverage_params")
    if not sites_path.exists() or not params_path.exists():
        return []

    con = get_connection()
    try:
        rows = con.execute(
            f"""
            SELECT p.site_id, s.latitude, s.longitude, p.azimuth, {_TECH_BUCKET_SQL} AS tech, p.coverage_radius_m
            FROM read_parquet('{params_path}') p
            JOIN read_parquet('{sites_path}') s ON p.site_id = s.site_id
            WHERE s.longitude BETWEEN ? AND ? AND s.latitude BETWEEN ? AND ?
              AND p.azimuth IS NOT NULL AND p.coverage_radius_m IS NOT NULL
            """,
            [west, east, south, north],
        ).fetchall()
        return [
            {"site_id": r[0], "latitude": r[1], "longitude": r[2], "azimuth": r[3], "technology": r[4], "coverage_radius_m": r[5]}
            for r in rows
            if r[4] is not None
        ]
    finally:
        con.close()


_SIGNAL_BANDS = {
    "high": (-120.0, -100.0),   # -100 to -120 dBm
    "mid": (-130.0, -121.0),    # -121 to -130 dBm
    "low": (None, -130.0),      # weaker than -130 dBm
}


def coverage_holes_by_band(south: float, west: float, north: float, east: float, band: str) -> list[dict]:
    """MR/Ookla coverage-hole points within the viewport, bucketed into
    the three signal-strength bands requested for the map's Signal
    layers. Empty whenever coverage_holes.parquet itself is empty —
    no MR/Ookla input data exists in dataset_example, so this is wired
    correctly but has nothing to show until real MR/Ookla source files
    are ingested."""
    if band not in _SIGNAL_BANDS:
        raise InvalidMetricError(f"Unknown signal band '{band}', expected one of {list(_SIGNAL_BANDS)}")
    holes_path = _parquet_path("coverage_holes")
    if not holes_path.exists():
        return []

    lower, upper = _SIGNAL_BANDS[band]
    con = get_connection()
    try:
        clauses = ["longitude BETWEEN ? AND ?", "latitude BETWEEN ? AND ?"]
        params: list[float] = [west, east, south, north]
        if lower is not None:
            clauses.append("signal_strength >= ?")
            params.append(lower)
        if upper is not None:
            clauses.append("signal_strength <= ?")
            params.append(upper)
        rows = con.execute(
            f"""
            SELECT latitude, longitude, signal_strength, serving_cell, data_source, cluster_id
            FROM read_parquet('{holes_path}')
            WHERE {' AND '.join(clauses)}
            """,
            params,
        ).fetchall()
        return [
            {"latitude": r[0], "longitude": r[1], "signal_strength": r[2], "serving_cell": r[3], "data_source": r[4], "cluster_id": r[5]}
            for r in rows
        ]
    finally:
        con.close()


def geoserver_layers() -> list[dict]:
    """Lists whatever layers are actually published on the GeoServer
    instance via WMS GetCapabilities, rather than hardcoding layer
    names — the legacy app never wired GeoServer up at all (only unused
    .sld style files existed, never referenced by any route), so there
    is no fixed legacy layer list to port. Returns an empty list (not
    an error) if GeoServer isn't reachable, since the map should still
    work without it."""
    url = f"{settings.geoserver_url}/wms"
    try:
        resp = httpx.get(url, params={"service": "WMS", "request": "GetCapabilities", "version": "1.3.0"}, timeout=3.0)
        resp.raise_for_status()
    except httpx.HTTPError:
        return []

    try:
        root = ElementTree.fromstring(resp.text)
    except ElementTree.ParseError:
        return []

    ns = {"wms": "http://www.opengis.net/wms"}
    layers = []
    for layer_el in root.findall(".//wms:Layer[wms:Name]", ns):
        name_el = layer_el.find("wms:Name", ns)
        title_el = layer_el.find("wms:Title", ns)
        if name_el is not None and name_el.text:
            layers.append({"name": name_el.text, "title": title_el.text if title_el is not None else name_el.text})
    return layers


def nearby_geoserver_features(layer: str, lat: float, lng: float, radius_m: float) -> list[dict]:
    """Point features within radius_m of (lat, lng) on a published
    GeoServer layer, via WFS GetFeature + a DWITHIN CQL filter.

    Used by the Genset and Bitcoin-mining map tools to find candidate
    substations/buildings from our own infrastructure (an admin-managed
    GeoServer layer) instead of querying a third-party API with real
    site coordinates — the legacy app queried the public Overpass API
    directly from the browser for this, which this rebuild deliberately
    does not replicate. Returns an empty list (not an error) if
    GeoServer is unreachable or the named layer doesn't exist yet,
    same fallback behavior as geoserver_layers()."""
    url = f"{settings.geoserver_url}/wfs"
    cql_filter = f"DWITHIN(the_geom,POINT({lng} {lat}),{radius_m},meters)"
    try:
        resp = httpx.get(
            url,
            params={
                "service": "WFS", "version": "2.0.0", "request": "GetFeature",
                "typeName": layer, "outputFormat": "application/json", "cql_filter": cql_filter,
            },
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    results = []
    for feature in data.get("features", []):
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates")
        point = _feature_centroid(geom.get("type"), coords)
        if point is None:
            continue
        props = feature.get("properties") or {}
        results.append({"lat": point[1], "lng": point[0], "name": props.get("name", feature.get("id", "")), "properties": props})
    return results


def _feature_centroid(geom_type: str | None, coords) -> tuple[float, float] | None:
    """Cheap centroid for the geometry types GeoServer is likely to
    return here (Point, or a Polygon/MultiPolygon building footprint) —
    average of the outer ring's vertices, not a true area centroid,
    which is precise enough for the proximity check these two tools
    actually need."""
    if geom_type == "Point" and coords:
        return (coords[0], coords[1])
    if geom_type == "Polygon" and coords:
        ring = coords[0]
        return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
    if geom_type == "MultiPolygon" and coords:
        ring = coords[0][0]
        return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
    return None


def overview_stats() -> dict:
    """Network-wide stats, not scoped to the viewport — the panel above
    the bounds-scoped tab. Worst-congested-sectors/Ookla/MR clusters
    are each a top-10 list (not just the single worst) so the panel
    can show a ranked, click-to-pan list."""
    congestion_path = _parquet_path("congestion_analysis")
    sites_path = _parquet_path("site_coordinates")
    holes_path = _parquet_path("coverage_holes")
    capex_files = _capex_files()

    if not congestion_path.exists() and not holes_path.exists() and not capex_files:
        return {
            "total_sites": 0, "total_congested_sites": 0, "total_capex": 0.0,
            "worst_congested_sectors": [], "worst_ookla_clusters": [], "worst_mr_clusters": [],
        }

    con = get_connection()
    try:
        total_sites = total_congested = 0
        worst_congested_sectors: list[dict] = []
        if congestion_path.exists():
            row = con.execute(f"""
                WITH latest AS (
                    SELECT *, row_number() OVER (
                        PARTITION BY zoom_sector_id ORDER BY year DESC, week DESC
                    ) AS rn FROM read_parquet('{congestion_path}')
                )
                SELECT count(DISTINCT site_id), count(DISTINCT CASE WHEN congested THEN site_id END)
                FROM latest WHERE rn = 1
            """).fetchone()
            total_sites, total_congested = row[0] or 0, row[1] or 0

            # "Worst" = most persistently congested sector, i.e. the most
            # weeks spent over the congestion threshold — not just currently
            # congested, since a sector congested for 1 week is a different
            # problem than one congested for 10.
            join_clause = (
                f"LEFT JOIN read_parquet('{sites_path}') s ON split_part(c.zoom_sector_id, '_', 1) = s.site_id"
                if sites_path.exists() else ""
            )
            site_cols = "s.latitude, s.longitude" if sites_path.exists() else "NULL, NULL"
            worst_rows = con.execute(f"""
                SELECT c.zoom_sector_id, c.region, max(c.congested_weeks) AS weeks, {site_cols}
                FROM read_parquet('{congestion_path}') c
                {join_clause}
                WHERE c.congested_weeks IS NOT NULL
                GROUP BY c.zoom_sector_id, c.region, {site_cols}
                ORDER BY weeks DESC
                LIMIT 10
            """).fetchall()
            worst_congested_sectors = [
                {"zoom_sector_id": r[0], "region": r[1], "congested_weeks": r[2], "latitude": r[3], "longitude": r[4]}
                for r in worst_rows
                if r[2]
            ]

        total_capex = 0.0
        if capex_files:
            row = con.execute(f"SELECT sum(estimated_total_capex_rm) FROM read_parquet('{_capex_glob()}')").fetchone()
            total_capex = round(row[0], 2) if row and row[0] is not None else 0.0

        def worst_clusters(source: str) -> list[dict]:
            if not holes_path.exists():
                return []
            rows = con.execute(
                f"""
                SELECT cluster_id, count(*) AS point_count, avg(signal_strength) AS avg_signal,
                       avg(latitude) AS lat, avg(longitude) AS lng
                FROM read_parquet('{holes_path}')
                WHERE data_source = ? AND cluster_id != -1
                GROUP BY cluster_id
                ORDER BY point_count DESC
                LIMIT 10
                """,
                [source],
            ).fetchall()
            return [
                {
                    "cluster_id": r[0], "data_source": source, "point_count": r[1],
                    "avg_signal": round(r[2], 1) if r[2] is not None else None,
                    "latitude": r[3], "longitude": r[4],
                }
                for r in rows
            ]

        return {
            "total_sites": total_sites, "total_congested_sites": total_congested, "total_capex": total_capex,
            "worst_congested_sectors": worst_congested_sectors,
            "worst_ookla_clusters": worst_clusters("Ookla"), "worst_mr_clusters": worst_clusters("MR"),
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
