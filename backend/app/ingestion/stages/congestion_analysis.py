"""Congestion analysis: unions xC + xD sector calculations and flags
congested sectors.

Ports `scripts_example/Capacity-Congestion-Analysis.py`. The legacy script
parses year/week back out of S3 partition paths (`year=YYYY/week=WW/`)
because its output dropped those columns before writing each partition.
Not needed here — xc_huawei/xd_zte already keep `year`/`week`/`dataset_type`
as real columns in their output, so this stage is a straight UNION ALL
plus filtering and two window functions, no partition-path parsing.

Congestion thresholds (unchanged from legacy):
  - Urban/KMC + NIC:      PRB >= 80% AND throughput < 7 Mbps
  - Urban/KMC (non-NIC):  PRB >= 80% AND throughput < 5 Mbps
  - Rural/non-urban:      PRB >= 92% AND throughput < 3 Mbps

`congested_weeks` is a running cumulative count of congested weeks per
sector ordered by (year, week) — a window function here instead of the
legacy `groupby(...).cumsum()` on a pre-sorted DataFrame.
"""

from app.analytics.db import get_connection
from app.ingestion import parquet_store

OUTPUT_TABLE = "congestion_analysis"

DROP_REGION_VALUES = ("0", "UNKNOWN", "NAN", "NONE")


def run(xc_paths: list[str], xd_paths: list[str]) -> str:
    con = get_connection()
    try:
        return _run(con, xc_paths, xd_paths)
    finally:
        con.close()


def _run(con, xc_paths: list[str], xd_paths: list[str]) -> Path:
    all_paths = list(xc_paths) + list(xd_paths)
    if not all_paths:
        raise ValueError("No xC or xD sector-calculation files provided")

    union_sql = " UNION ALL ".join(f"SELECT * FROM read_parquet('{p}')" for p in all_paths)
    drop_values_sql = ", ".join(f"'{v}'" for v in DROP_REGION_VALUES)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE filtered AS
        SELECT *
        FROM ({union_sql})
        WHERE upper(trim(region)) NOT IN ({drop_values_sql})
          AND NOT (eric_prb_util_rate = 0.0 AND eric_dl_user_ip_thpt = 0.0 AND eric_data_volume_ul_dl = 0.0)
    """)

    con.execute("""
        CREATE OR REPLACE TEMP TABLE flagged AS
        SELECT
            *,
            LEAST(GREATEST(CAST(FLOOR((week - 1) / 4.0) AS INTEGER) + 1, 1), 12) AS month,
            (
                (area_target ILIKE '%urban%' OR area_target ILIKE '%kmc%')
                AND bau_nic ILIKE '%nic%'
                AND eric_prb_util_rate >= 80.0 AND eric_dl_user_ip_thpt < 7.0
            ) OR (
                (area_target ILIKE '%urban%' OR area_target ILIKE '%kmc%')
                AND NOT bau_nic ILIKE '%nic%'
                AND eric_prb_util_rate >= 80.0 AND eric_dl_user_ip_thpt < 5.0
            ) OR (
                NOT (area_target ILIKE '%urban%' OR area_target ILIKE '%kmc%')
                AND eric_prb_util_rate >= 92.0 AND eric_dl_user_ip_thpt < 3.0
            ) AS congested
        FROM filtered
    """)

    output_uri = parquet_store.parquet_uri(f"{OUTPUT_TABLE}.parquet")
    con.execute(f"""
        COPY (
            SELECT
                *,
                sum(CAST(congested AS INTEGER)) OVER (
                    PARTITION BY zoom_sector_id ORDER BY year, week
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS congested_weeks,
                sum(CAST(congested AS INTEGER)) OVER (
                    PARTITION BY zoom_sector_id, year, month
                ) AS congested_count_month
            FROM flagged
        ) TO '{output_uri}' (FORMAT PARQUET, COMPRESSION SNAPPY)
    """)
    return output_uri
