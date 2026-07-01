"""Per-cell antenna coverage parameters.

Ports `scripts/Capacity-Site-Coverage-Parameters.py`: detect site/cell/
azimuth/tilt columns by keyword (vendor exports have no stable header
naming), then compute a coverage radius per cell either from a
technology-based default or trigonometrically from antenna height + tilt.

Column *detection* stays in Python — the set of columns varies per vendor
file and isn't known until the file is opened, so there's nothing to
vectorize there. The radius calculation and final dedupe, which scale with
row count, are pushed into DuckDB SQL instead of the legacy per-row
`df.apply(...)`.
"""

import tempfile
from pathlib import Path

import pandas as pd

from app.analytics.db import get_connection
from app.ingestion import parquet_safe, parquet_store

OUTPUT_TABLE = "site_coverage_params"

SITE_KEYWORDS = ("site", "site_id", "site id", "location", "code")
CELL_KEYWORDS = ("cell", "cell_name", "sector", "cellname")
AZIMUTH_KEYWORDS = ("azimuth", "dir", "orientation")
TECH_KEYWORDS = ("tech", "technology", "system", "band")
HEIGHT_KEYWORDS = ("height", "ant_height", "agl", "antenna_height")
MTILT_KEYWORDS = ("m_tilt", "mtilt", "mech_tilt", "mechanical")
ETILT_KEYWORDS = ("e_tilt", "etilt", "elec_tilt", "electrical")
REMARK_KEYWORDS = ("remark", "type", "category")


def _detect_column(columns: list[str], keywords: tuple[str, ...]) -> str | None:
    for col in columns:
        cl = col.lower().strip()
        if any(k == cl or k in cl for k in keywords):
            return col
    return None


def _select_clause(columns: list[str]) -> str | None:
    """Builds the SELECT ... AS aliasing for one raw file's columns. Returns
    None if the file doesn't have the minimum site_id + azimuth columns."""
    site_col = _detect_column(columns, SITE_KEYWORDS)
    az_col = _detect_column(columns, AZIMUTH_KEYWORDS)
    if not (site_col and az_col):
        return None

    cell_col = _detect_column(columns, CELL_KEYWORDS)
    tech_col = _detect_column(columns, TECH_KEYWORDS)
    height_col = _detect_column(columns, HEIGHT_KEYWORDS)
    mtilt_col = _detect_column(columns, MTILT_KEYWORDS)
    etilt_col = _detect_column(columns, ETILT_KEYWORDS)
    remark_col = _detect_column(columns, REMARK_KEYWORDS)

    cell_expr = f'"{cell_col}"' if cell_col else f'"{site_col}" || \'_1\''
    tech_expr = f'"{tech_col}"' if tech_col else "'Unknown'"
    height_expr = f'TRY_CAST("{height_col}" AS DOUBLE)' if height_col else "0.0"
    mtilt_expr = f'TRY_CAST("{mtilt_col}" AS DOUBLE)' if mtilt_col else "0.0"
    etilt_expr = f'TRY_CAST("{etilt_col}" AS DOUBLE)' if etilt_col else "0.0"
    remark_expr = f'"{remark_col}"' if remark_col else "''"

    return f"""
        SELECT
            upper(regexp_replace(trim(CAST("{site_col}" AS VARCHAR)), '[_ -].*$', '')) AS site_id,
            CAST({cell_expr} AS VARCHAR) AS cell_name,
            COALESCE(TRY_CAST("{az_col}" AS DOUBLE), 0.0) AS azimuth,
            CAST({tech_expr} AS VARCHAR) AS technology,
            COALESCE({height_expr}, 0.0) AS antenna_height,
            COALESCE({mtilt_expr}, 0.0) AS m_tilt,
            COALESCE({etilt_expr}, 0.0) AS e_tilt,
            CAST({remark_expr} AS VARCHAR) AS remark
        FROM read_file
    """


def _excel_sheets_to_parquet(path: str) -> list[str]:
    """DuckDB has no built-in xlsb reader and the xlsx reader needs an
    extension that may not be installed offline, so Excel/XLSB sheets are
    converted to temp Parquet via pandas (one read per sheet, matching the
    legacy script's sheet-by-sheet streaming) and DuckDB takes over from there."""
    engine = "pyxlsb" if path.lower().endswith(".xlsb") else None
    xls = pd.ExcelFile(path, engine=engine)
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


def run(raw_file_paths: list[str]) -> str:
    con = get_connection()
    temp_parquets: list[str] = []
    try:
        return _run(con, raw_file_paths, temp_parquets)
    finally:
        con.close()
        for p in temp_parquets:
            Path(p).unlink(missing_ok=True)


def _run(con, raw_file_paths: list[str], temp_parquets: list[str]) -> str:
    selects: list[str] = []
    i = 0

    for path in raw_file_paths:
        sources = [path] if path.lower().endswith(".csv") else _excel_sheets_to_parquet(path)
        temp_parquets.extend(p for p in sources if p != path)

        for source in sources:
            reader = "read_csv" if source.lower().endswith(".csv") else "read_parquet"
            # sample_size=-1 forces DuckDB to scan the whole file for type
            # inference instead of the first ~20k rows — real vendor CSVs
            # routinely have a column that's numeric for thousands of rows
            # then switches to a string value (e.g. "NBIOT") past the
            # default sample window, which otherwise throws a cast error.
            reader_opts = ", ignore_errors=true, delim=',', quote='\"', escape='\"', sample_size=-1, max_line_size=10000000, strict_mode=false, null_padding=true" if reader == "read_csv" else ""
            con.execute(f"CREATE OR REPLACE TEMP VIEW read_file AS SELECT * FROM {reader}('{source}'{reader_opts})")
            columns = [r[0] for r in con.execute("DESCRIBE read_file").fetchall()]
            clause = _select_clause(columns)
            if clause:
                con.execute(f"CREATE OR REPLACE TEMP TABLE file_{i} AS {clause}")
                selects.append(f"SELECT * FROM file_{i}")
                i += 1

    if not selects:
        raise ValueError("No input file had both a site_id and azimuth column")

    union_sql = " UNION ALL ".join(selects)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE coverage AS
        SELECT
            site_id,
            cell_name,
            azimuth,
            technology,
            antenna_height,
            m_tilt,
            e_tilt,
            remark,
            CASE
                WHEN remark ILIKE '%FEMTO%' OR remark ILIKE '%IBC%' OR remark ILIKE '%INBUILDING%' THEN 50.0
                WHEN antenna_height > 0 AND (m_tilt + e_tilt) > 0
                    THEN LEAST(antenna_height / tan(radians(m_tilt + e_tilt)), 35000.0)
                WHEN technology ILIKE '%2G%' THEN 5000.0
                WHEN technology ILIKE '%3G%' THEN 3000.0
                WHEN technology ILIKE '%5G%' OR technology ILIKE '%NR%' THEN 500.0
                ELSE 1500.0
            END AS coverage_radius_m,
            row_number() OVER (PARTITION BY cell_name ORDER BY 1 DESC) AS rn
        FROM ({union_sql})
        WHERE site_id IS NOT NULL
    """)

    output_uri = parquet_store.parquet_uri(f"{OUTPUT_TABLE}.parquet")
    con.execute(f"""
        COPY (
            SELECT site_id, cell_name, azimuth, technology, antenna_height,
                   m_tilt, e_tilt, remark, coverage_radius_m
            FROM coverage
            WHERE rn = 1
        ) TO '{output_uri}' (FORMAT PARQUET, COMPRESSION SNAPPY)
    """)
    return output_uri
