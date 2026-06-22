"""Pre-CAPEX upgrades: per-sector PRB demand aggregated from raw xC/xD
files, filtered to sectors that congestion_analysis already flagged as
ever congested.

Ports `scripts_example/Pre-Capacity-CAPEX-Upgrades.py`. The legacy script
re-reads the *raw* xC/xD files a second time (not the processed
xc_huawei/xd_zte parquet) because it needs `daily_rb_used` computed from
the raw busy-hour utilization column at a finer grain than the weekly
sector rollup keeps — so this stage takes a raw file path again, same as
xc_huawei/xd_zte, rather than reading their output.

xC and xD differ in shape (legacy duplicates near-identical code 3x per
format for each — collapsed here into one function with a `dataset_type`
switch):
  - xC: top-4-per-cell-name by (user_count, daily_rb_used) descending,
    then mean per cell, mirroring the busy-hour reduction in xc_huawei.
  - xD: no top-4 step — every row is summed directly into its sector.

avail_prb resolution order (per row): a bandwidth column in the raw file
itself if present (bw_mhz * 5.0), otherwise the cell's avail_prb from
cell_reference. `sum_existing_prb` (the sector's already-installed
capacity, used as the baseline subtracted from demand) always comes from
cell_reference, never from the raw file.
"""

import re
from pathlib import Path

from app.analytics.db import get_connection
from app.core.config import settings

OUTPUT_TABLE = "pre_capex_upgrades"


def _detect_column(columns: list[str], must_contain_all: tuple[str, ...]) -> str | None:
    for col in columns:
        cl = col.lower().strip()
        if all(k in cl for k in must_contain_all):
            return col
    return None


def _parse_year_week(filename: str) -> tuple[int, int]:
    """year/week aren't in the legacy script's output at all (it relies on
    S3 partition paths instead) — added here as real columns since
    capex_upgrades needs to join pre_capex_upgrades against
    congestion_analysis by (zoom_sector_id, year, week)."""
    year_match = re.search(r"(?:year|y)[-_=\s]*(\d{4})", filename, re.IGNORECASE) or re.search(r"(202\d)", filename)
    week_match = re.search(r"(?:week|wk|w)[-_=\s]*(\d{1,2})", filename, re.IGNORECASE)
    year = int(year_match.group(1)) if year_match else 2025
    week = int(week_match.group(1)) if week_match else 1
    return year, week


def run(raw_file_path: str, cell_reference_path: str, congestion_path: str, dataset_type: str) -> Path | None:
    if dataset_type not in ("xC", "xD"):
        raise ValueError(f"dataset_type must be 'xC' or 'xD', got {dataset_type!r}")

    con = get_connection()
    try:
        return _run(con, raw_file_path, cell_reference_path, congestion_path, dataset_type)
    finally:
        con.close()


def _run(con, raw_file_path: str, cell_reference_path: str, congestion_path: str, dataset_type: str) -> Path | None:
    file_year, file_week = _parse_year_week(raw_file_path)
    reader = "read_csv" if raw_file_path.lower().endswith(".csv") else "read_parquet"
    # sample_size=-1 scans the whole file for type inference instead of the
    # first ~20k rows, avoiding cast errors on columns that are numeric
    # early on but switch to text later in large files.
    reader_opts = ", ignore_errors=true, sample_size=-1" if reader == "read_csv" else ""
    con.execute(f"CREATE OR REPLACE TEMP VIEW raw AS SELECT * FROM {reader}('{raw_file_path}'{reader_opts})")
    raw_columns = [r[0] for r in con.execute("DESCRIBE raw").fetchall()]

    cell_col = _detect_column(raw_columns, ("cell", "name"))
    bw_col = _detect_column(raw_columns, ("bw",))
    if dataset_type == "xC":
        util_col = _detect_column(raw_columns, ("bh", "rb", "util"))
        user_col = _detect_column(raw_columns, ("user", "count"))
    else:
        util_col = _detect_column(raw_columns, ("eric_prb", "utilzation"))
        user_col = None

    if not cell_col or not util_col:
        return None

    bw_expr = f'COALESCE(TRY_CAST("{bw_col}" AS DOUBLE), 0.0) * 5.0' if bw_col else None
    user_expr = f'COALESCE(TRY_CAST("{user_col}" AS DOUBLE), 0.0)' if user_col else "0.0"

    # A bw column in the raw file always wins, even if it's 0/blank for a
    # given row — the legacy script never falls back to the reference
    # lookup in that case, it only uses the reference avail_prb when the
    # raw file has no bw column at all.
    avail_prb_expr = bw_expr if bw_expr else "COALESCE(ref.avail_prb, 0.0)"

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE rows_with_rb AS
        SELECT
            trim(CAST(raw."{cell_col}" AS VARCHAR)) AS cell_name,
            ref.zoom_sector_id,
            (COALESCE(TRY_CAST(raw."{util_col}" AS DOUBLE), 0.0) / 100.0) * {avail_prb_expr} AS rb_used,
            {user_expr} AS user_count
        FROM raw
        LEFT JOIN read_parquet('{cell_reference_path}') ref
            ON trim(CAST(raw."{cell_col}" AS VARCHAR)) = ref.cell_name
        WHERE raw."{cell_col}" IS NOT NULL AND ref.zoom_sector_id IS NOT NULL
    """)

    if dataset_type == "xC":
        con.execute("""
            CREATE OR REPLACE TEMP TABLE top4 AS
            SELECT * FROM (
                SELECT *,
                    row_number() OVER (
                        PARTITION BY cell_name ORDER BY user_count DESC, rb_used DESC
                    ) AS rn
                FROM rows_with_rb
            ) WHERE rn <= 4
        """)
        con.execute("""
            CREATE OR REPLACE TEMP TABLE sector_sums AS
            SELECT zoom_sector_id, sum(avg_rb_used) AS sum_rb_used
            FROM (
                SELECT zoom_sector_id, cell_name, avg(rb_used) AS avg_rb_used
                FROM top4
                GROUP BY zoom_sector_id, cell_name
            )
            GROUP BY zoom_sector_id
        """)
    else:
        con.execute("""
            CREATE OR REPLACE TEMP TABLE sector_sums AS
            SELECT zoom_sector_id, sum(rb_used) AS sum_rb_used
            FROM rows_with_rb
            GROUP BY zoom_sector_id
        """)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE cong_sectors AS
        SELECT zoom_sector_id, first(area_target) AS area_target
        FROM read_parquet('{congestion_path}')
        GROUP BY zoom_sector_id
    """)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE existing_prb AS
        SELECT zoom_sector_id, sum(avail_prb) AS sum_existing_prb
        FROM read_parquet('{cell_reference_path}')
        GROUP BY zoom_sector_id
    """)

    output_path = Path(settings.parquet_dir) / f"{OUTPUT_TABLE}_{dataset_type}_{re.sub(r'[^A-Za-z0-9]', '_', Path(raw_file_path).stem)}.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (
            SELECT
                ss.zoom_sector_id,
                '{dataset_type}' AS dataset_type,
                {file_year} AS year,
                {file_week} AS week,
                COALESCE(ep.sum_existing_prb, 0.0) AS sum_existing_prb,
                ss.sum_rb_used,
                (ss.sum_rb_used / CASE
                    WHEN lower(COALESCE(cs.area_target, 'unknown')) LIKE '%urban%'
                        OR lower(COALESCE(cs.area_target, 'unknown')) LIKE '%kmc%'
                    THEN 0.8 ELSE 0.92 END) - COALESCE(ep.sum_existing_prb, 0.0) AS additional_rb
            FROM sector_sums ss
            INNER JOIN cong_sectors cs ON ss.zoom_sector_id = cs.zoom_sector_id
            LEFT JOIN existing_prb ep ON ss.zoom_sector_id = ep.zoom_sector_id
        ) TO '{output_path}' (FORMAT PARQUET, COMPRESSION SNAPPY)
    """)
    return output_path
