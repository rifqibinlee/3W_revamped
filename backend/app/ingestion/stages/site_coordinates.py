"""Site coordinate extraction.

Ports `scripts_example/Capacity-Site-Coordinate-Process.py`: read raw
location exports (csv/xlsx/xlsb), detect site_id/lat/lon/region/cluster
columns by keyword (vendor exports have no stable header naming), drop
rows with missing coordinates, dedupe by site_id (last occurrence wins).

Column detection is ported faithfully from the legacy script, including
its fragility: SITE_KEYWORDS includes a bare `'id'`, so the *first*
column in file order containing "id" or "site" wins, even if a column
named exactly `site_id` appears later. This is a real quirk already
present in the legacy heuristic, not something introduced here — kept
as-is for behavioral parity rather than silently "fixing" semantics that
might be relied on elsewhere.
"""

import tempfile
from pathlib import Path

import pandas as pd

from app.analytics.db import get_connection
from app.core.config import settings
from app.ingestion import parquet_safe

OUTPUT_TABLE = "site_coordinates"

SITE_KEYWORDS = ("site", "site_id", "site id", "location", "location_id", "code", "id", "site id(new)")
LAT_KEYWORDS = ("latitude", "lat", "y_coord", "north")
LON_KEYWORDS = ("longitude", "long", "lng", "x_coord", "east")


def _clean_header(raw: str) -> str:
    return (
        str(raw).lower().strip().replace(" ", "_").replace("(", "").replace(")", "").replace("/", "_")
    )


def _detect_column(columns: list[str], keywords: tuple[str, ...]) -> str | None:
    for col in columns:
        cl = col.lower().strip()
        if any(k == cl or k in cl for k in keywords):
            return col
    return None


def _excel_sheets_to_sources(path: str) -> list[str]:
    engine = "pyxlsb" if path.lower().endswith(".xlsb") else None
    xls = pd.ExcelFile(path, engine=engine)
    out_paths = []
    for sheet in xls.sheet_names:
        df = xls.parse(sheet_name=sheet)
        df.columns = [_clean_header(c) for c in df.columns]
        if df.empty:
            continue
        tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
        tmp.close()  # Windows can't delete a file with an open handle later
        parquet_safe.to_parquet(df, tmp.name)
        out_paths.append(tmp.name)
    xls.close()
    return out_paths


def _select_clause(columns: list[str]) -> str | None:
    site_col = _detect_column(columns, SITE_KEYWORDS)
    lat_col = _detect_column(columns, LAT_KEYWORDS)
    lon_col = _detect_column(columns, LON_KEYWORDS)
    if not (site_col and lat_col and lon_col):
        return None

    region_col = next((c for c in columns if "region" in c.lower()), None)
    cluster_col = next((c for c in columns if "cluster" in c.lower() or "district" in c.lower()), None)
    region_expr = f'CAST("{region_col}" AS VARCHAR)' if region_col else "CAST(NULL AS VARCHAR)"
    cluster_expr = f'CAST("{cluster_col}" AS VARCHAR)' if cluster_col else "CAST(NULL AS VARCHAR)"

    return f"""
        SELECT
            CAST("{site_col}" AS VARCHAR) AS site_id_raw,
            {region_expr} AS region,
            {cluster_expr} AS cluster,
            TRY_CAST("{lat_col}" AS DOUBLE) AS latitude,
            TRY_CAST("{lon_col}" AS DOUBLE) AS longitude
        FROM read_file
    """


def run(raw_file_paths: list[str]) -> Path:
    con = get_connection()
    temp_parquets: list[str] = []
    try:
        return _run(con, raw_file_paths, temp_parquets)
    finally:
        con.close()
        for p in temp_parquets:
            Path(p).unlink(missing_ok=True)


def _run(con, raw_file_paths: list[str], temp_parquets: list[str]) -> Path:
    selects: list[str] = []
    i = 0

    for path in raw_file_paths:
        if path.lower().endswith(".csv"):
            sources = [path]
        else:
            sources = _excel_sheets_to_sources(path)
            temp_parquets.extend(sources)

        for source in sources:
            if source.lower().endswith(".csv"):
                con.execute(f"CREATE OR REPLACE TEMP VIEW read_file_raw AS SELECT * FROM read_csv('{source}', ignore_errors=true)")
                raw_columns = [r[0] for r in con.execute("DESCRIBE read_file_raw").fetchall()]
                renames = ", ".join(f'"{c}" AS "{_clean_header(c)}"' for c in raw_columns)
                con.execute(f"CREATE OR REPLACE TEMP VIEW read_file AS SELECT {renames} FROM read_file_raw")
            else:
                con.execute(f"CREATE OR REPLACE TEMP VIEW read_file AS SELECT * FROM read_parquet('{source}')")
            columns = [r[0] for r in con.execute("DESCRIBE read_file").fetchall()]
            clause = _select_clause(columns)
            if clause:
                con.execute(f"CREATE OR REPLACE TEMP TABLE file_{i} AS {clause}")
                selects.append(f"SELECT * FROM file_{i}")
                i += 1

    if not selects:
        raise ValueError("No input file had detectable site_id/latitude/longitude columns")

    union_sql = " UNION ALL ".join(selects)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE raw_sites AS
        WITH normalized AS (
            SELECT
                regexp_replace(upper(trim(CAST(site_id_raw AS VARCHAR))), '[_ -].*$', '') AS site_id,
                COALESCE(region, 'Unknown') AS region,
                COALESCE(cluster, 'Unknown') AS cluster,
                latitude,
                longitude
            FROM ({union_sql})
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL AND site_id_raw IS NOT NULL
        )
        SELECT
            site_id, region, cluster, latitude, longitude,
            row_number() OVER (PARTITION BY site_id ORDER BY 1 DESC) AS rn
        FROM normalized
    """)

    output_path = Path(settings.parquet_dir) / f"{OUTPUT_TABLE}.parquet"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (
            SELECT site_id, region, cluster, latitude, longitude
            FROM raw_sites
            WHERE rn = 1
        ) TO '{output_path}' (FORMAT PARQUET, COMPRESSION SNAPPY)
    """)
    return output_path
