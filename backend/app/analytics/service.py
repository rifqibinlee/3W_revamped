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
    legacy UI offers W13/W26/W39/W52), joined with coordinates. Region
    comes from the site join — forecast_results itself has no region
    column (it's per-sector, not joined to site data)."""
    forecast_path = _parquet_path("forecast_results")
    sites_path = _parquet_path("site_coordinates")
    if not forecast_path.exists() or not sites_path.exists():
        return []

    con = get_connection()
    try:
        rows = con.execute(
            f"""
            SELECT
                f.zoom_sector_id, f.congested, s.region,
                s.site_id, s.latitude, s.longitude
            FROM read_parquet('{forecast_path}') f
            LEFT JOIN read_parquet('{sites_path}') s
                ON split_part(f.zoom_sector_id, '_', 1) = s.site_id
            WHERE f.year = ? AND f.week = ?
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
    ):
        self.region = region
        self.year = year
        self.week = week
        self.operator = operator
        self.cluster = cluster

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
        where_sql, params = filters.where_clause(available_columns=("year", "week", "operator"))
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


def overview_stats() -> dict:
    """Network-wide stats, not scoped to the viewport — the panel above
    the bounds-scoped tab."""
    congestion_path = _parquet_path("congestion_analysis")
    holes_path = _parquet_path("coverage_holes")
    capex_files = _capex_files()

    if not congestion_path.exists() and not holes_path.exists() and not capex_files:
        return {
            "total_sites": 0, "total_congested_sites": 0, "total_capex": 0.0,
            "worst_ookla_cluster": None, "worst_mr_cluster": None,
        }

    con = get_connection()
    try:
        total_sites = total_congested = 0
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

        total_capex = 0.0
        if capex_files:
            row = con.execute(f"SELECT sum(estimated_total_capex_rm) FROM read_parquet('{_capex_glob()}')").fetchone()
            total_capex = round(row[0], 2) if row and row[0] is not None else 0.0

        def worst_cluster(source: str) -> dict | None:
            if not holes_path.exists():
                return None
            top = con.execute(
                f"""
                SELECT cluster_id, count(*) AS point_count, avg(signal_strength) AS avg_signal
                FROM read_parquet('{holes_path}')
                WHERE data_source = ? AND cluster_id != -1
                GROUP BY cluster_id
                ORDER BY point_count DESC
                LIMIT 1
                """,
                [source],
            ).fetchone()
            if not top:
                return None
            return {
                "cluster_id": top[0], "data_source": source,
                "point_count": top[1], "avg_signal": round(top[2], 1) if top[2] is not None else None,
            }

        return {
            "total_sites": total_sites, "total_congested_sites": total_congested, "total_capex": total_capex,
            "worst_ookla_cluster": worst_cluster("Ookla"), "worst_mr_cluster": worst_cluster("MR"),
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
