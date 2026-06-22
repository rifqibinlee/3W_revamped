"""CD Combined Result: the three downloadable reports the app serves
(`/download/cd_file`, `/download/sector`, `/download/congested`).

Ports `scripts_example/Capacity-CD-Combined-Result.py`. Output stays CSV
here deliberately — these are user-facing download files, not a query
engine, so CSV isn't the performance problem it was when it stood in for
the analytics database (see docs/adr/0001-architecture.md). Everything
else in this rebuild moved off CSV; this stage is the one legitimate place
it still belongs.

Three outputs:
  - Sector_Metrics: every xC/xD sector row, unfiltered (legacy loads this
    straight from the same sector-calculation files xc_huawei/xd_zte
    produce, not from congestion_analysis's filtered/flagged version —
    so a sector dropped by congestion_analysis's region/zero-row filters
    still shows up here).
  - Congested_Sectors: congestion_analysis rows where congested = true.
  - CD_Combined_Results: Sector_Metrics joined with congestion flags
    (defaulting to congested=false / congested_weeks=0 for sectors with
    no matching congestion row — e.g. ones the filters dropped).

`short_sector_id` collapses "SITE001_Macro_1" to "SITE001_M_1" (first
letter of ibc_macro) — same transform as the legacy `make_short_id`.
"""

from pathlib import Path

from app.analytics.db import get_connection
from app.core.config import settings

SECTOR_COLUMNS = (
    "zoom_sector_id", "region", "cluster", "ibc_macro", "f1f2f3",
    "eric_data_volume_ul_dl", "eric_prb_util_rate", "eric_dl_user_ip_thpt",
    "eric_max_rrc_user", "max_active_user", "area_target", "bau_nic",
    "dataset_type", "operator", "year", "week",
)

def run(xc_paths: list[str], xd_paths: list[str], congestion_path: str) -> dict[str, Path]:
    con = get_connection()
    try:
        return _run(con, xc_paths, xd_paths, congestion_path)
    finally:
        con.close()


def _run(con, xc_paths: list[str], xd_paths: list[str], congestion_path: str) -> dict[str, Path]:
    all_paths = list(xc_paths) + list(xd_paths)
    if not all_paths:
        raise ValueError("No xC or xD sector-calculation files provided")

    union_sql = " UNION ALL ".join(f"SELECT * FROM read_parquet('{p}')" for p in all_paths)
    sector_cols_sql = ", ".join(SECTOR_COLUMNS)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE sector_metrics AS
        SELECT {sector_cols_sql} FROM ({union_sql})
    """)

    out_dir = Path(settings.parquet_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sector_metrics_path = out_dir / "Sector_Metrics.csv"
    con.execute(f"COPY sector_metrics TO '{sector_metrics_path}' (FORMAT CSV, HEADER)")

    congested_sectors_path = out_dir / "Congested_Sectors.csv"
    con.execute(f"""
        COPY (
            SELECT * FROM read_parquet('{congestion_path}') WHERE congested = true
        ) TO '{congested_sectors_path}' (FORMAT CSV, HEADER)
    """)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE cong_slim AS
        SELECT DISTINCT zoom_sector_id, year, week, congested_weeks, congested
        FROM read_parquet('{congestion_path}')
    """)

    con.execute("""
        CREATE OR REPLACE TEMP TABLE cd_combined_raw AS
        SELECT
            sm.*,
            split_part(sm.zoom_sector_id, '_', 1) || '_' ||
                left(split_part(sm.zoom_sector_id, '_', 2), 1) || '_' ||
                split_part(sm.zoom_sector_id, '_', 3) AS short_sector_id,
            COALESCE(cs.congested_weeks, 0) AS congested_weeks,
            COALESCE(cs.congested, false) AS is_congested
        FROM sector_metrics sm
        LEFT JOIN cong_slim cs
            ON sm.zoom_sector_id = cs.zoom_sector_id AND sm.year = cs.year AND sm.week = cs.week
    """)

    cd_combined_path = out_dir / "CD_Combined_Results.csv"
    con.execute(f"""
        COPY (
            SELECT
                year, week, zoom_sector_id, short_sector_id,
                region, cluster, ibc_macro, f1f2f3,
                eric_data_volume_ul_dl, eric_prb_util_rate, eric_dl_user_ip_thpt,
                eric_max_rrc_user, max_active_user,
                COALESCE(area_target, 'Unknown') AS area_target,
                COALESCE(bau_nic, 'Unknown') AS bau_nic,
                COALESCE(dataset_type, 'Unknown') AS dataset_type,
                COALESCE(operator, 'Unknown') AS operator,
                congested_weeks, is_congested
            FROM cd_combined_raw
        ) TO '{cd_combined_path}' (FORMAT CSV, HEADER)
    """)

    return {
        "sector_metrics": sector_metrics_path,
        "congested_sectors": congested_sectors_path,
        "cd_combined": cd_combined_path,
    }
