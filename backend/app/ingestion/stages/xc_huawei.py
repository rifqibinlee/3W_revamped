"""xC (Huawei) weekly sector calculations.

Ports `scripts_example/xC Huawei Dataset.py`. The legacy script does three
things that don't shrink to SQL:
  1. Converts raw .xlsb to a column-filtered CSV (pyxlsb has no DuckDB
     equivalent), keeping only columns useful downstream — these files are
     95-113MB/week, so filtering at conversion time matters for the 40GB
     disk budget.
  2. Detects which raw column means what (vendor exports use inconsistent
     headers across weeks) — stays in Python, same as other stages.
  3. Parses year/week from the filename when not present as columns.

Everything that scales with row count — top-4-per-cell-band-week selection,
the per-cell aggregation, the reference join, and the per-site-sector
rollup — is one chain of DuckDB SQL instead of the legacy chunked pandas
loop with manual top-4 reduction every 5 chunks.

Two-level aggregation, matching the legacy script exactly:
  1. Per (cell_name, band, week, year): sum PRB/throughput numerators and
     denominators across the top-4 busy-hour rows, mean volume/users.
  2. Per (site_id, ibc_macro, sector_suffix, week, year) — i.e. across
     bands/cells in the same sector — sum the per-cell sums again, derive
     PRB utilization % and throughput from the combined numerator/denominator.

`compute_base_sector_id` in the legacy script collapses a sector id to
`site_id_ibcmacro_digit`, which is already exactly how zoom_sector_id is
constructed here (site_id has no internal delimiters), so it's a no-op and
isn't reimplemented separately.
"""

import csv
import re
import tempfile
from pathlib import Path

import pyxlsb

from app.analytics.db import get_connection
from app.ingestion import parquet_store, sql_macros

OUTPUT_TABLE = "xc_huawei"

NEEDED_COLS = {
    "location_id", "site_id", "cellname", "cell_name", "week_number", "week",
    "bh_max_user_#", "eric_max_rrc_user", "bh_dl_rb_util_pct", "dl_rb_util",
    "dl_user_throughput", "dl_throughput", "traffic", "data_volume", "volume",
    "dl_prb_num", "dl_prb_denom", "user_dl_thp_num", "user_dl_thp_denom",
    "band", "year", "date", "time", "region",
}
ALWAYS_KEEP_SUBSTRINGS = ("volume", "traffic", "cellname", "cell_name", "date", "time", "region")

COLUMN_RENAMES = {
    "location_id": "site_id",
    "cellname": "cell_name",
    "week_number": "week",
    "bh_max_user_#": "eric_max_rrc_user",
    "bh_dl_rb_util_pct": "dl_rb_util",
    "dl_user_throughput": "dl_throughput",
    "traffic": "data_volume",
}

NUMERIC_COLUMNS = (
    "dl_rb_util", "dl_throughput", "data_volume", "eric_max_rrc_user",
    "dl_prb_num", "dl_prb_denom", "user_dl_thp_num", "user_dl_thp_denom",
)


def _clean_header(raw: str) -> str:
    return (
        str(raw).lower().replace(" ", "_").replace("(", "").replace(")", "")
        .replace("+", "_").replace("%", "pct")
    )


def _parse_year_week(filename: str) -> tuple[int, int]:
    year_match = re.search(r"(?:year|y)[-_=\s]*(\d{4})", filename, re.IGNORECASE) or re.search(r"(202\d)", filename)
    week_match = re.search(r"(?:week|wk|w)[-_=\s]*(\d{1,2})", filename, re.IGNORECASE)
    year = int(year_match.group(1)) if year_match else 2025
    week = int(week_match.group(1)) if week_match else 1
    return year, week


def _xlsb_to_filtered_csv(path: str) -> str:
    """Streams the first sheet of an .xlsb to CSV, keeping only columns in
    NEEDED_COLS (or matching a keep-substring) — mirrors the legacy
    header_map filter so converted files don't balloon disk usage."""
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", newline="", encoding="utf-8")
    with pyxlsb.open_workbook(path) as wb, wb.get_sheet(wb.sheets[0]) as sheet:
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
                    if clean_col in NEEDED_COLS or any(s in clean_col for s in ALWAYS_KEEP_SUBSTRINGS):
                        header_indices.append(c_idx)
                        ordered_headers.append(clean_col)
                writer.writerow(ordered_headers)
            else:
                if not any(cells):
                    continue
                writer.writerow([cells[i] if i < len(cells) else None for i in header_indices])
    tmp.close()
    return tmp.name


def run(raw_file_path: str, cell_reference_path: str) -> str:
    con = get_connection()
    temp_csv: str | None = None
    try:
        return _run(con, raw_file_path, cell_reference_path, temp_csv)
    finally:
        con.close()


def _run(con, raw_file_path: str, cell_reference_path: str, temp_csv: str | None) -> str:
    sql_macros.register(con)
    file_year, file_week = _parse_year_week(raw_file_path)

    if raw_file_path.lower().endswith(".xlsb"):
        temp_csv = _xlsb_to_filtered_csv(raw_file_path)
        csv_path = temp_csv
    else:
        csv_path = raw_file_path

    try:
        con.execute(f"CREATE OR REPLACE TEMP VIEW raw AS SELECT * FROM read_csv('{csv_path}', ignore_errors=true, delim=',', quote='\"', escape='\"', sample_size=-1, max_line_size=10000000, strict_mode=false, null_padding=true, parallel=false)")
        raw_columns = [r[0] for r in con.execute("DESCRIBE raw").fetchall()]

        cleaned_to_raw: dict[str, str] = {}
        for raw_col in raw_columns:
            cleaned = _clean_header(raw_col)
            cleaned = COLUMN_RENAMES.get(cleaned, cleaned)
            cleaned_to_raw.setdefault(cleaned, raw_col)

        if "data_volume" not in cleaned_to_raw:
            vol_col = next((raw for cleaned, raw in cleaned_to_raw.items() if "volume" in cleaned or "traffic" in cleaned), None)
            if vol_col:
                cleaned_to_raw["data_volume"] = vol_col

        if "cell_name" not in cleaned_to_raw:
            raise ValueError(f"{raw_file_path}: no cell_name/cellname column detected")

        def col(name: str, default_sql: str = "NULL") -> str:
            raw_col = cleaned_to_raw.get(name)
            return f'"{raw_col}"' if raw_col else default_sql

        numeric_selects = ", ".join(
            f"COALESCE(TRY_CAST({col(c)} AS DOUBLE), 0.0) AS {c}" for c in NUMERIC_COLUMNS
        )

        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE parsed AS
            SELECT
                trim(CAST({col('cell_name')} AS VARCHAR)) AS cell_name,
                CAST({col('band')} AS VARCHAR) AS band,
                COALESCE(TRY_CAST({col('week')} AS INTEGER), {file_week}) AS week,
                COALESCE(TRY_CAST({col('year')} AS INTEGER), {file_year}) AS year,
                CAST({col('region')} AS VARCHAR) AS region,
                CAST({col('vendor', "'Huawei'")} AS VARCHAR) AS vendor,
                {numeric_selects}
            FROM raw
            WHERE {col('cell_name')} IS NOT NULL
        """)

        con.execute("""
            CREATE OR REPLACE TEMP TABLE enriched AS
            SELECT
                *,
                CASE
                    WHEN cell_name LIKE '%\\_%' ESCAPE '\\' THEN 'Celcom'
                    WHEN cell_name LIKE '%-%' THEN 'Digi'
                    ELSE 'Unknown'
                END AS operator,
                classify_ibc_macro(upper(cell_name)) AS ibc_macro,
                classify_f1f2f3(upper(trim(cell_name, '_'))) AS f1f2f3,
                extract_sector_suffix(cell_name) AS sector_suffix,
                upper(split_part(replace(replace(cell_name, '-', '_'), ' ', '_'), '_', 1)) AS site_id
            FROM parsed
        """)

        con.execute("""
            CREATE OR REPLACE TEMP TABLE enriched2 AS
            SELECT *, site_id || '_' || ibc_macro || '_' || sector_suffix AS zoom_sector_id
            FROM enriched
        """)

        con.execute("""
            CREATE OR REPLACE TEMP TABLE top4 AS
            SELECT * FROM (
                SELECT *,
                    row_number() OVER (
                        PARTITION BY cell_name, band, week, year
                        ORDER BY eric_max_rrc_user DESC, dl_rb_util DESC
                    ) AS rn
                FROM enriched2
            )
            WHERE rn <= 4
        """)

        con.execute("""
            CREATE OR REPLACE TEMP TABLE per_cell AS
            SELECT
                cell_name, band, week, year,
                first(zoom_sector_id) AS zoom_sector_id,
                first(ibc_macro) AS ibc_macro,
                first(f1f2f3) AS f1f2f3,
                first(operator) AS operator,
                first(vendor) AS vendor,
                first(site_id) AS site_id,
                first(region) AS region,
                sum(dl_prb_num) AS sum_dl_prb_num,
                sum(dl_prb_denom) AS sum_dl_prb_denom,
                sum(user_dl_thp_num) AS sum_thp_num,
                sum(user_dl_thp_denom) AS sum_thp_denom,
                avg(data_volume) AS sum_vol,
                avg(eric_max_rrc_user) AS sum_users
            FROM top4
            GROUP BY cell_name, band, week, year
        """)

        # The site-level fallback must be deduplicated to one row per site_id
        # before joining — cell_reference has many rows per site (one per
        # cell), so joining on site_id directly would multiply every
        # per_cell row by however many cells share that site_id.
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE ref_by_site_dedup AS
            SELECT
                site_id,
                first(area_target) FILTER (WHERE area_target IS NOT NULL) AS area_target,
                first(bau_nic) FILTER (WHERE bau_nic IS NOT NULL) AS bau_nic
            FROM read_parquet('{cell_reference_path}')
            GROUP BY site_id
        """)

        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE per_cell_with_ref AS
            SELECT
                pc.*,
                COALESCE(ref_by_cell.area_target, ref_by_site.area_target) AS area_target,
                COALESCE(ref_by_cell.bau_nic, ref_by_site.bau_nic) AS bau_nic
            FROM per_cell pc
            LEFT JOIN read_parquet('{cell_reference_path}') ref_by_cell
                ON upper(regexp_replace(pc.cell_name, '[^A-Za-z0-9]', '', 'g')) = ref_by_cell.join_key
            LEFT JOIN ref_by_site_dedup ref_by_site
                ON pc.site_id = ref_by_site.site_id
        """)

        # Each call processes one raw weekly file — the output filename must
        # encode that, or calling this once per week (as the DAG requires)
        # silently overwrites the previous week's output under the same
        # static filename.
        safe_stem = re.sub(r"[^A-Za-z0-9]", "_", parquet_store.stem_from_uri(raw_file_path))
        output_uri = parquet_store.parquet_uri(f"{OUTPUT_TABLE}_{safe_stem}.parquet")
        con.execute(f"""
            COPY (
                SELECT
                    first(site_id) AS site_id,
                    zoom_sector_id,
                    week,
                    year,
                    upper(trim(coalesce(first(region), 'Unknown'))) AS region,
                    'Unknown' AS cluster,
                    first(ibc_macro) AS ibc_macro,
                    string_agg(DISTINCT lower(f1f2f3), '' ORDER BY lower(f1f2f3)) AS f1f2f3,
                    sum(sum_vol) AS eric_data_volume_ul_dl,
                    CASE WHEN sum(sum_dl_prb_denom) > 0
                        THEN sum(sum_dl_prb_num) / sum(sum_dl_prb_denom) * 100.0 ELSE 0.0 END AS eric_prb_util_rate,
                    CASE WHEN sum(sum_thp_denom) > 0
                        THEN sum(sum_thp_num) / sum(sum_thp_denom) / 1000.0 ELSE 0.0 END AS eric_dl_user_ip_thpt,
                    CAST(sum(sum_users) AS BIGINT) AS eric_max_rrc_user,
                    CAST(sum(sum_users) AS BIGINT) AS max_active_user,
                    'xC' AS dataset_type,
                    first(operator) AS operator,
                    coalesce(first(area_target) FILTER (WHERE area_target IS NOT NULL), 'Unknown') AS area_target,
                    coalesce(first(bau_nic) FILTER (WHERE bau_nic IS NOT NULL), 'Unknown') AS bau_nic,
                    coalesce(first(vendor), 'Unknown') AS vendor
                FROM per_cell_with_ref
                GROUP BY zoom_sector_id, week, year
            ) TO '{output_uri}' (FORMAT PARQUET, COMPRESSION SNAPPY)
        """)
        return output_uri
    finally:
        if temp_csv:
            Path(temp_csv).unlink(missing_ok=True)
