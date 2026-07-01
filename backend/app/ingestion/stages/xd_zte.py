"""xD (ZTE) weekly sector calculations.

Ports `scripts_example/xD (ZTE Dataset).py`. Structurally similar to
xc_huawei but simpler: the legacy script reads each file as a single
whole-sheet pandas DataFrame (no chunking, no top-4 busy-hour reduction —
ZTE exports are already one row per cell/week), so there's no equivalent
of xc_huawei's top-4 window step here.

Differences from xc_huawei worth noting since both feed the same
downstream schema:
  - avail_prb comes from a direct join on cell_name against
    cell_reference (exact match, no join_key normalization or
    site-level fallback — the legacy script doesn't have one for xD).
  - PRB utilization is computed from prb_used = (rate/100)*avail_prb
    per row, then summed and re-divided per group, rather than from raw
    numerator/denominator columns like xC.
  - data volume and throughput have a "divide by 1000 if >= 1000" unit
    safeguard in the legacy script (some weeks report in different
    units) — kept as-is.

site_id/sector_suffix/operator reuse the same `extract_site_id` /
`extract_sector_suffix` macros as cell_reference, since xD's
`parse_sector_info` uses the identical split-on-first-delimiter rule.
"""

import re
import tempfile
from pathlib import Path

import pandas as pd

from app.analytics.db import get_connection
from app.ingestion import parquet_store
from app.ingestion import parquet_safe, sql_macros

OUTPUT_TABLE = "xd_zte"

COLUMN_RENAMES = {
    "week_number": "week",
    "cellname": "cell_name",
    "eric_prb_utilzation_rate": "eric_prb_util_rate",
    "maximum_active_user_number_on_user_plane": "max_active_user",
    "eric_data_volumeul_dl": "eric_data_volume_ul_dl",
    "eric_dl_usert_thpt_nom": "eric_dl_user_thpt_nom",
}


def _clean_header(raw: str) -> str:
    return (
        str(raw).lower().replace(" ", "_").replace("(", "").replace(")", "")
        .replace("+", "_").replace("%", "pct")
    )


def _parse_year_week(filename: str) -> tuple[int, int]:
    year_match = re.search(r"(?:year|y)[-_=\s]*(\d{4})", filename, re.IGNORECASE) or re.search(r"(202\d)", filename)
    week_match = re.search(r"(?:week|wk|w)[-_=\s]*(\d{1,2})", filename, re.IGNORECASE)
    year = int(year_match.group(1)) if year_match else 2026
    week = int(week_match.group(1)) if week_match else 1
    return year, week


def _first_sheet_to_parquet(path: str) -> str:
    """Legacy script reads only the first/default sheet (`pd.read_excel(file,
    engine='pyxlsb')` with no sheet_name) — matched here rather than scanning
    every sheet like cell_reference does."""
    engine = "pyxlsb" if path.lower().endswith(".xlsb") else None
    xls = pd.ExcelFile(path, engine=engine)
    df = xls.parse(sheet_name=xls.sheet_names[0])
    xls.close()
    tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
    tmp.close()  # Windows can't delete a file with an open handle later
    parquet_safe.to_parquet(df, tmp.name)
    return tmp.name


def run(raw_file_path: str, cell_reference_path: str) -> str:
    con = get_connection()
    try:
        return _run(con, raw_file_path, cell_reference_path)
    finally:
        con.close()


def _run(con, raw_file_path: str, cell_reference_path: str) -> str:
    sql_macros.register(con)
    file_year, file_week = _parse_year_week(raw_file_path)
    temp_file: str | None = None

    try:
        if raw_file_path.lower().endswith(".csv"):
            source_path = raw_file_path
        else:
            temp_file = _first_sheet_to_parquet(raw_file_path)
            source_path = temp_file

        reader = "read_csv" if source_path.lower().endswith(".csv") else "read_parquet"
        # sample_size=-1 scans the whole file for type inference instead of
        # the first ~20k rows, avoiding cast errors on columns that are
        # numeric early on but switch to text later in large files.
        reader_opts = ", ignore_errors=true, sample_size=-1" if reader == "read_csv" else ""
        con.execute(f"CREATE OR REPLACE TEMP VIEW raw AS SELECT * FROM {reader}('{source_path}'{reader_opts})")
        raw_columns = [r[0] for r in con.execute("DESCRIBE raw").fetchall()]

        cleaned_to_raw: dict[str, str] = {}
        for raw_col in raw_columns:
            cleaned = _clean_header(raw_col)
            cleaned = COLUMN_RENAMES.get(cleaned, cleaned)
            cleaned_to_raw.setdefault(cleaned, raw_col)

        if "cell_name" not in cleaned_to_raw:
            raise ValueError(f"{raw_file_path}: no cell_name/cellname column detected")

        def col(name: str, default_sql: str = "NULL") -> str:
            raw_col = cleaned_to_raw.get(name)
            return f'"{raw_col}"' if raw_col else default_sql

        def num(name: str, default_sql: str = "NULL") -> str:
            raw_col = cleaned_to_raw.get(name)
            return f'TRY_CAST("{raw_col}" AS DOUBLE)' if raw_col else default_sql

        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE parsed AS
            SELECT
                trim(CAST({col('cell_name')} AS VARCHAR)) AS cell_name,
                COALESCE(TRY_CAST({col('week')} AS INTEGER), {file_week}) AS week,
                COALESCE(TRY_CAST({col('year')} AS INTEGER), {file_year}) AS year,
                CAST({col('region')} AS VARCHAR) AS region,
                CAST({col('cluster')} AS VARCHAR) AS cluster,
                CAST({col('vendor', "'ZTE'")} AS VARCHAR) AS vendor,
                COALESCE({num('eric_prb_util_rate')}, 0.0) AS eric_prb_util_rate,
                COALESCE({num('max_active_user')}, 0.0) AS max_active_user,
                CASE WHEN COALESCE({num('eric_data_volume_ul_dl')}, 0.0) >= 1000
                     THEN COALESCE({num('eric_data_volume_ul_dl')}, 0.0) / 1000.0
                     ELSE COALESCE({num('eric_data_volume_ul_dl')}, 0.0) END AS eric_data_volume_ul_dl,
                CASE WHEN COALESCE({num('eric_dl_user_ip_thpt')}, 0.0) >= 1000
                     THEN COALESCE({num('eric_dl_user_ip_thpt')}, 0.0) / 1000.0
                     ELSE COALESCE({num('eric_dl_user_ip_thpt')}, 0.0) END AS eric_dl_user_ip_thpt,
                {num('eric_dl_user_thpt_nom', '0.0')} AS eric_dl_user_thpt_nom,
                {num('eric_dl_user_ip_thpt_denom', '0.0')} AS eric_dl_user_ip_thpt_denom
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
                extract_site_id(cell_name) AS site_id_raw,
                extract_sector_suffix(cell_name) AS sector_suffix
            FROM parsed
        """)

        con.execute("""
            CREATE OR REPLACE TEMP TABLE enriched2 AS
            SELECT *, upper(site_id_raw) AS site_id,
                   upper(site_id_raw) || '_' || ibc_macro || '_' || sector_suffix AS zoom_sector_id
            FROM enriched
        """)

        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE with_ref AS
            SELECT
                e.*,
                ref.avail_prb,
                ref.area_target,
                ref.bau_nic
            FROM enriched2 e
            LEFT JOIN read_parquet('{cell_reference_path}') ref
                ON e.cell_name = ref.cell_name
        """)

        con.execute("""
            CREATE OR REPLACE TEMP TABLE with_prb_used AS
            SELECT *, (eric_prb_util_rate / 100.0) * COALESCE(avail_prb, 0.0) AS prb_used
            FROM with_ref
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
                    upper(trim(coalesce(first(region) FILTER (WHERE region IS NOT NULL), 'Unknown'))) AS region,
                    coalesce(first(cluster) FILTER (WHERE cluster IS NOT NULL), 'Unknown') AS cluster,
                    first(ibc_macro) AS ibc_macro,
                    string_agg(DISTINCT lower(f1f2f3), '' ORDER BY lower(f1f2f3)) AS f1f2f3,
                    sum(eric_data_volume_ul_dl) AS eric_data_volume_ul_dl,
                    CASE WHEN sum(avail_prb) > 0
                        THEN sum(prb_used) / sum(avail_prb) * 100.0 ELSE 0.0 END AS eric_prb_util_rate,
                    CASE WHEN sum(eric_dl_user_ip_thpt_denom) > 0
                        THEN sum(eric_dl_user_thpt_nom) / sum(eric_dl_user_ip_thpt_denom)
                        ELSE avg(eric_dl_user_ip_thpt) END AS eric_dl_user_ip_thpt,
                    CAST(sum(max_active_user) AS BIGINT) AS eric_max_rrc_user,
                    CAST(sum(max_active_user) AS BIGINT) AS max_active_user,
                    'xD' AS dataset_type,
                    first(operator) AS operator,
                    coalesce(first(area_target) FILTER (WHERE area_target IS NOT NULL), 'Unknown') AS area_target,
                    coalesce(first(bau_nic) FILTER (WHERE bau_nic IS NOT NULL), 'Unknown') AS bau_nic,
                    coalesce(first(vendor) FILTER (WHERE vendor IS NOT NULL), 'Unknown') AS vendor
                FROM with_prb_used
                GROUP BY zoom_sector_id, week, year, ibc_macro
            ) TO '{output_uri}' (FORMAT PARQUET, COMPRESSION SNAPPY)
        """)
        return output_uri
    finally:
        if temp_file:
            Path(temp_file).unlink(missing_ok=True)
