"""Site coordinate extraction.

Ports the logic of legacy `scripts/Capacity-Site-Coordinate-Process.py`:
read raw location exports (csv/xlsx), keep site_id/region/cluster/lat/lon,
drop rows with missing coordinates, dedupe by site_id (last occurrence wins).

Rewritten as DuckDB SQL instead of a pandas dedupe loop — DuckDB reads CSV
and Excel-exported-as-CSV directly and the dedupe is a single window
function over the whole file, no chunking needed for files in this size
range (DuckDB streams larger-than-RAM CSVs natively).
"""

from pathlib import Path

from app.analytics.db import get_connection
from app.core.config import settings

OUTPUT_TABLE = "site_coordinates"


def run(raw_csv_paths: list[str]) -> Path:
    """Builds the deduplicated site_coordinates Parquet from one or more raw CSV exports.

    raw_csv_paths: local paths to staged raw files (see ingestion.storage.staged_object).
    Column names are matched case-insensitively by keyword, mirroring the
    dynamic column detection in the legacy script, since vendor exports do
    not use a stable header naming convention.
    """
    con = get_connection()
    union_sql = " UNION ALL BY NAME ".join(
        f"SELECT * FROM read_csv('{p}', union_by_name=true, ignore_errors=true)"
        for p in raw_csv_paths
    )

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE raw_sites AS
        WITH normalized AS (
            SELECT
                regexp_replace(lower(site_id), '[-_]', '') AS site_id,
                COALESCE(region, 'Unknown') AS region,
                COALESCE(cluster, 'Unknown') AS cluster,
                CAST(latitude AS DOUBLE) AS latitude,
                CAST(longitude AS DOUBLE) AS longitude
            FROM ({union_sql})
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
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
    con.close()
    return output_path
