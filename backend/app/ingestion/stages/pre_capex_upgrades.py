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

import csv
import re
import tempfile
from pathlib import Path

import pandas as pd
import pyxlsb

from app.analytics.db import get_write_connection as get_connection
from app.ingestion import parquet_store
from app.ingestion import parquet_safe

OUTPUT_TABLE = "pre_capex_upgrades"

# Keywords for the columns this stage actually reads (see _detect_column
# calls below) — used to filter columns at read time so large weekly xlsb
# files (95-115MB) don't get fully materialized into a pandas DataFrame
# with every vendor column. Loading a full sheet via pd.ExcelFile.parse()
# routinely hit MemoryError on these files; xc_huawei already avoids this
# by streaming+filtering through pyxlsb directly (_xlsb_to_filtered_csv) —
# same pattern applied here.
_KEEP_KEYWORD_GROUPS = (
    ("cell", "name"),
    ("bw",),
    ("bh", "rb", "util"),
    ("eric_prb", "utilzation"),
    ("user", "count"),
)


def _detect_column(columns: list[str], must_contain_all: tuple[str, ...]) -> str | None:
    for col in columns:
        cl = col.lower().strip()
        if all(k in cl for k in must_contain_all):
            return col
    return None


def _clean_header(raw: str) -> str:
    return str(raw).lower().strip().replace(" ", "_")


def _xlsb_sheet_to_filtered_csv(path: str, sheet_name: str) -> str | None:
    """Streams one xlsb sheet to a temp CSV, keeping only columns that match
    one of _KEEP_KEYWORD_GROUPS — mirrors xc_huawei._xlsb_to_filtered_csv's
    column-filtering streaming approach instead of loading the whole sheet
    into a pandas DataFrame (which OOMs on these ~100MB weekly files)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="", encoding="utf-8")
    wrote_any_row = False
    with pyxlsb.open_workbook(path) as wb, wb.get_sheet(sheet_name) as sheet:
        writer = csv.writer(tmp)
        header_indices: list[int] = []
        for r_idx, row in enumerate(sheet.rows()):
            cells = [c.v for c in row]
            if r_idx == 0:
                ordered_headers = []
                for c_idx, val in enumerate(cells):
                    if val is None:
                        continue
                    clean_col = _clean_header(val)
                    if any(all(k in clean_col for k in group) for group in _KEEP_KEYWORD_GROUPS):
                        header_indices.append(c_idx)
                        ordered_headers.append(clean_col)
                if not ordered_headers:
                    break
                writer.writerow(ordered_headers)
            else:
                if not any(cells):
                    continue
                writer.writerow([cells[i] if i < len(cells) else None for i in header_indices])
                wrote_any_row = True
    tmp.close()
    if not wrote_any_row:
        Path(tmp.name).unlink(missing_ok=True)
        return None
    return tmp.name


def _excel_sheets_to_parquet(path: str) -> list[str]:
    """xlsb/xlsx aren't handled by read_csv/read_parquet directly. For xlsb,
    streams+filters each sheet to CSV via pyxlsb (see
    _xlsb_sheet_to_filtered_csv) to avoid materializing the full ~100MB
    sheet in memory; for xlsx (much smaller in this dataset), keeps the
    original per-sheet pandas conversion."""
    if path.lower().endswith(".xlsb"):
        with pyxlsb.open_workbook(path) as wb:
            sheet_names = list(wb.sheets)
        out_paths = []
        for sheet_name in sheet_names:
            csv_path = _xlsb_sheet_to_filtered_csv(path, sheet_name)
            if csv_path:
                out_paths.append(csv_path)
        return out_paths

    xls = pd.ExcelFile(path)
    out_paths = []
    for sheet in xls.sheet_names:
        df = xls.parse(sheet_name=sheet)
        if df.empty:
            continue
        tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
        tmp.close()  # Windows can't delete a file with an open handle later
        parquet_safe.to_parquet(df, tmp.name)
        out_paths.append(tmp.name)
    xls.close()
    return out_paths


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


def run(raw_file_path: str, cell_reference_path: str, congestion_path: str, dataset_type: str) -> str | None:
    if dataset_type not in ("xC", "xD"):
        raise ValueError(f"dataset_type must be 'xC' or 'xD', got {dataset_type!r}")

    con = get_connection()
    temp_parquets: list[str] = []
    try:
        return _run(con, raw_file_path, cell_reference_path, congestion_path, dataset_type, temp_parquets)
    finally:
        con.close()
        for p in temp_parquets:
            Path(p).unlink(missing_ok=True)


def _run(con, raw_file_path: str, cell_reference_path: str, congestion_path: str, dataset_type: str, temp_parquets: list[str]) -> str | None:
    file_year, file_week = _parse_year_week(raw_file_path)

    lower = raw_file_path.lower()
    if lower.endswith((".csv", ".parquet")):
        sources = [raw_file_path]
    else:
        sources = _excel_sheets_to_parquet(raw_file_path)
        temp_parquets.extend(sources)

    selects: list[str] = []
    i = 0
    for source in sources:
        reader = "read_csv" if source.lower().endswith(".csv") else "read_parquet"
        reader_opts = ", ignore_errors=true, delim=',', quote='\"', escape='\"', sample_size=-1, max_line_size=10000000, strict_mode=false, null_padding=true, parallel=false" if reader == "read_csv" else ""
        con.execute(f"CREATE OR REPLACE TEMP VIEW raw_{i} AS SELECT * FROM {reader}('{source}'{reader_opts})")
        raw_columns = [r[0] for r in con.execute(f"DESCRIBE raw_{i}").fetchall()]

        cell_col = _detect_column(raw_columns, ("cell", "name"))
        bw_col = _detect_column(raw_columns, ("bw",))
        if dataset_type == "xC":
            util_col = _detect_column(raw_columns, ("bh", "rb", "util"))
            user_col = _detect_column(raw_columns, ("user", "count"))
        else:
            util_col = _detect_column(raw_columns, ("eric_prb", "utilzation"))
            user_col = None

        if not cell_col or not util_col:
            i += 1
            continue

        bw_expr = f'COALESCE(TRY_CAST(raw_{i}."{bw_col}" AS DOUBLE), 0.0) * 5.0' if bw_col else None
        user_expr = f'COALESCE(TRY_CAST(raw_{i}."{user_col}" AS DOUBLE), 0.0)' if user_col else "0.0"

        # A bw column in the raw file always wins, even if it's 0/blank for a
        # given row — the legacy script never falls back to the reference
        # lookup in that case, it only uses the reference avail_prb when the
        # raw file has no bw column at all.
        avail_prb_expr = bw_expr if bw_expr else "COALESCE(ref.avail_prb, 0.0)"

        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE rows_with_rb_{i} AS
            SELECT
                trim(CAST(raw_{i}."{cell_col}" AS VARCHAR)) AS cell_name,
                ref.zoom_sector_id,
                (COALESCE(TRY_CAST(raw_{i}."{util_col}" AS DOUBLE), 0.0) / 100.0) * {avail_prb_expr} AS rb_used,
                {user_expr} AS user_count
            FROM raw_{i}
            LEFT JOIN read_parquet('{cell_reference_path}') ref
                ON trim(CAST(raw_{i}."{cell_col}" AS VARCHAR)) = ref.cell_name
            WHERE raw_{i}."{cell_col}" IS NOT NULL AND ref.zoom_sector_id IS NOT NULL
        """)
        selects.append(f"SELECT * FROM rows_with_rb_{i}")
        i += 1

    if not selects:
        return None

    con.execute(f"CREATE OR REPLACE TEMP TABLE rows_with_rb AS {' UNION ALL '.join(selects)}")

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

    output_path = parquet_store.parquet_uri(f"{OUTPUT_TABLE}_{dataset_type}_{re.sub(r'[^A-Za-z0-9]', '_', parquet_store.stem_from_uri(raw_file_path))}.parquet")
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
