"""Forecast results: 52-week-ahead linear projection per sector.

Ports `scripts_example/Capacity-Forecast-Results.py`. The legacy script
fits three independent `sklearn.LinearRegression` models per sector in a
Python loop. Ordinary least squares with one feature has a closed form,
and DuckDB's `regr_slope`/`regr_intercept` aggregates compute exactly
that — so the regression itself is pushed into one SQL aggregation over
all sectors at once instead of a per-sector Python fit.

What stays in Python: generating the 52 future (year, week, month) tuples
per sector via `date.fromisocalendar`/`timedelta`. DuckDB's ISO-week date
parts exist but re-deriving the legacy script's exact
`date.fromisocalendar(year, week, 1)` arithmetic in SQL risks a subtle
mismatch for a part of the system that's otherwise easy to get exactly
right in a few lines of Python — not worth the risk for what's a small
fraction of this stage's total work (52 rows/sector, not 52 regressions).

`zoom_sector_id_override` doesn't exist anywhere in this pipeline's data
model (no upstream stage produces it) — kept as a column, always NULL,
since the legacy schema has it.
"""

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from app.analytics.db import get_connection
from app.ingestion import parquet_store

OUTPUT_TABLE = "forecast_results"
FORECAST_HORIZON = 52


def _get_iso_date(year: int, week: int) -> date | None:
    try:
        return date.fromisocalendar(int(year), int(week), 1)
    except ValueError:
        return None


def run(xc_paths: list[str], xd_paths: list[str]) -> str | None:
    con = get_connection()
    try:
        return _run(con, xc_paths, xd_paths)
    finally:
        con.close()


def _run(con, xc_paths: list[str], xd_paths: list[str]) -> str | None:
    all_paths = list(xc_paths) + list(xd_paths)
    if not all_paths:
        raise ValueError("No xC or xD sector-calculation files provided")

    union_sql = " UNION ALL ".join(f"SELECT * FROM read_parquet('{p}')" for p in all_paths)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE ordered AS
        SELECT
            *,
            CASE WHEN dataset_type = 'xC' THEN eric_max_rrc_user ELSE max_active_user END AS user_metric,
            row_number() OVER (PARTITION BY zoom_sector_id ORDER BY year, week) AS x
        FROM ({union_sql})
    """)

    global_row = con.execute("""
        SELECT year AS global_max_year, week AS global_max_week
        FROM ordered
        ORDER BY year DESC, week DESC
        LIMIT 1
    """).fetchone()
    if global_row is None:
        return None
    global_max_year, global_max_week = global_row
    global_base_date = _get_iso_date(global_max_year, global_max_week)
    if global_base_date is None:
        return None

    sector_df = con.execute("""
        SELECT
            zoom_sector_id,
            count(*) AS n_points,
            arg_max(ibc_macro, x) AS ibc_macro,
            arg_max(f1f2f3, x) AS f1f2f3,
            arg_max(dataset_type, x) AS dataset_type,
            arg_max(operator, x) AS operator,
            arg_max(year, x) AS last_year,
            arg_max(week, x) AS last_week,
            avg(user_metric) AS avg_user_count,
            regr_slope(eric_data_volume_ul_dl, x) AS slope_vol,
            regr_intercept(eric_data_volume_ul_dl, x) AS int_vol,
            regr_slope(eric_prb_util_rate, x) AS slope_prb,
            regr_intercept(eric_prb_util_rate, x) AS int_prb,
            regr_slope(eric_dl_user_ip_thpt, x) AS slope_thp,
            regr_intercept(eric_dl_user_ip_thpt, x) AS int_thp
        FROM ordered
        GROUP BY zoom_sector_id
        HAVING count(*) >= 2
    """).fetchdf()

    if sector_df.empty:
        return None

    rows: list[dict] = []
    for sector in sector_df.to_dict("records"):
        n_points = sector["n_points"]
        sector_end_date = _get_iso_date(sector["last_year"], sector["last_week"])
        if sector_end_date is None:
            continue

        week_gap = max((global_base_date - sector_end_date).days // 7, 0)

        for offset in range(1, FORECAST_HORIZON + 1):
            future_x = n_points + week_gap + offset
            future_date = global_base_date + timedelta(days=offset * 7)
            f_year, f_week, _ = future_date.isocalendar()
            f_month = future_date.month

            pred_vol = max(0.0, sector["slope_vol"] * future_x + sector["int_vol"])
            pred_prb = max(0.0, min(100.0, sector["slope_prb"] * future_x + sector["int_prb"]))
            pred_thp = max(0.0, sector["slope_thp"] * future_x + sector["int_thp"])
            is_congested = bool(pred_prb >= 80.0 and pred_thp < 3.0 and sector["avg_user_count"] >= 120)

            rows.append({
                "zoom_sector_id": sector["zoom_sector_id"],
                "zoom_sector_id_override": None,
                "week": f_week,
                "year": int(f_year),
                "month": f_month,
                "ibc_macro": sector["ibc_macro"],
                "f1f2f3": sector["f1f2f3"],
                "predicted_eric_data_volume_ul_dl": float(pred_vol),
                "predicted_eric_prb_util_rate": float(pred_prb),
                "predicted_eric_dl_user_ip_thpt": float(pred_thp),
                "congested": is_congested,
                "data_points_used": int(n_points),
                "dataset_type": sector["dataset_type"],
                "operator": sector["operator"],
            })

    if not rows:
        return None

    df = pd.DataFrame(rows)
    summary = df.groupby("zoom_sector_id")["congested"].sum().rename("forecast_congested_weeks")
    df = df.merge(summary, on="zoom_sector_id", how="left")
    df["month_congested"] = df["forecast_congested_weeks"] >= 3

    output_uri = parquet_store.parquet_uri(f"{OUTPUT_TABLE}.parquet")
    con.register("forecast_df", df)
    con.execute(f"COPY forecast_df TO '{output_uri}' (FORMAT PARQUET, COMPRESSION SNAPPY)")
    return output_uri
