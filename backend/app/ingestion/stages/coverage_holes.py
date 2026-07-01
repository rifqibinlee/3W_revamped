"""Coverage holes: DBSCAN-clustered poor-signal points from MR/Ookla data.

Ports `scripts_example/Capacity-Coverage-Holes-Cluster-(DBSCAN).py`.
Column detection and the signal<-110dBm filter are DuckDB SQL (same
dynamic-column pattern as the other stages); the actual clustering stays
in Python via scikit-learn, since haversine-metric DBSCAN with an
auto-tuned epsilon/min_samples has no SQL equivalent — it's a genuinely
spatial algorithm, not an aggregation.

`auto_tune_dbscan` is ported verbatim: estimates min_samples from the
ratio of average 5th-nearest-neighbor distance to average nearest-
neighbor distance, then picks eps from the 74.5th percentile of
k-distances (a simple elbow heuristic), both in haversine-radians space.
"""

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.neighbors import NearestNeighbors

from app.analytics.db import get_connection
from app.ingestion import parquet_store
from app.ingestion import parquet_safe

OUTPUT_TABLE = "coverage_holes"

OOKLA_SIGNATURES = ("Operator_N", "Sim_Slot", "App_Versio", "Cell_ID")
SERVING_CELL_CANDIDATES = ("Serving Cell", "ServingCell", "Cell_ID", "Site_ID")
LAT_CANDIDATES = ("Latitude", "latitude")
LON_CANDIDATES = ("Longitude", "longitude")
SIGNAL_CANDIDATES = ("Cell Server Signal", "Signal")

DEFAULT_EPS_RAD = 0.05 / 6371.0088
DEFAULT_MIN_PTS = 3


def _first_present(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    for c in candidates:
        if c in columns:
            return c
    return None


def _excel_sheets_to_sources(path: str) -> list[str]:
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


def auto_tune_dbscan(x_radians: np.ndarray) -> tuple[float, int]:
    n_points = len(x_radians)
    if n_points < 6:
        return DEFAULT_EPS_RAD, DEFAULT_MIN_PTS

    neigh = NearestNeighbors(n_neighbors=6, metric="haversine")
    nbrs = neigh.fit(x_radians)
    distances, _ = nbrs.kneighbors(x_radians)

    avg_nn = float(np.mean(distances[:, 1]))
    avg_d5 = float(np.mean(distances[:, -1]))
    beta = 2.0
    safe_avg_nn = max(avg_nn, 1e-9)

    min_pts = max(3, int(round(beta * (avg_d5 / safe_avg_nn))))
    min_pts = min(min_pts, n_points - 1)

    neigh_k = NearestNeighbors(n_neighbors=min_pts, metric="haversine")
    nbrs_k = neigh_k.fit(x_radians)
    distances_k, _ = nbrs_k.kneighbors(x_radians)
    k_distances = np.sort(distances_k[:, -1])

    elbow_index = int(len(k_distances) * 0.745)
    eps_rad = float(k_distances[elbow_index])

    return eps_rad, min_pts


def run(raw_file_paths: list[str]) -> str | None:
    con = get_connection()
    temp_parquets: list[str] = []
    try:
        return _run(con, raw_file_paths, temp_parquets)
    finally:
        con.close()
        for p in temp_parquets:
            Path(p).unlink(missing_ok=True)


def _run(con, raw_file_paths: list[str], temp_parquets: list[str]) -> str | None:
    selects: list[str] = []
    i = 0

    for path in raw_file_paths:
        lower = path.lower()
        if lower.endswith(".csv") or lower.endswith(".parquet"):
            sources = [path]
        else:
            sources = _excel_sheets_to_sources(path)
            temp_parquets.extend(sources)

        for source in sources:
            if source.lower().endswith(".csv"):
                reader = "read_csv"
                # sample_size=-1 scans the whole file for type inference
                # instead of the first ~20k rows, avoiding cast errors on
                # columns that are numeric early then switch to text later.
                reader_opts = ", ignore_errors=true, delim=',', quote='\"', escape='\"', sample_size=-1, max_line_size=10000000, strict_mode=false, null_padding=true, parallel=false"
            else:
                reader = "read_parquet"
                reader_opts = ""
            con.execute(f"CREATE OR REPLACE TEMP VIEW src AS SELECT * FROM {reader}('{source}'{reader_opts})")
            columns = [r[0].strip() for r in con.execute("DESCRIBE src").fetchall()]

            lat_col = _first_present(columns, LAT_CANDIDATES)
            lon_col = _first_present(columns, LON_CANDIDATES)
            sig_col = _first_present(columns, SIGNAL_CANDIDATES)
            if not (lat_col and lon_col and sig_col):
                continue

            serving_col = _first_present(columns, SERVING_CELL_CANDIDATES)
            data_source = "Ookla" if any(c in columns for c in OOKLA_SIGNATURES) else "MR"
            serving_expr = f'CAST("{serving_col}" AS VARCHAR)' if serving_col else "'Unknown'"

            con.execute(f"""
                CREATE OR REPLACE TEMP TABLE filtered_{i} AS
                SELECT
                    TRY_CAST("{lat_col}" AS DOUBLE) AS latitude,
                    TRY_CAST("{lon_col}" AS DOUBLE) AS longitude,
                    TRY_CAST("{sig_col}" AS DOUBLE) AS signal_strength,
                    COALESCE({serving_expr}, 'Unknown') AS serving_cell,
                    '{data_source}' AS data_source
                FROM src
                WHERE TRY_CAST("{lat_col}" AS DOUBLE) IS NOT NULL
                  AND TRY_CAST("{lon_col}" AS DOUBLE) IS NOT NULL
                  AND TRY_CAST("{sig_col}" AS DOUBLE) IS NOT NULL
                  AND TRY_CAST("{sig_col}" AS DOUBLE) < -110
            """)
            selects.append(f"SELECT * FROM filtered_{i}")
            i += 1

    if not selects:
        return None

    points_df = con.execute(" UNION ALL ".join(selects)).fetchdf()
    if points_df.empty:
        return None

    x_rad = np.radians(points_df[["latitude", "longitude"]].to_numpy())

    if len(x_rad) > 10:
        eps_rad, min_pts = auto_tune_dbscan(x_rad)
    else:
        eps_rad, min_pts = DEFAULT_EPS_RAD, DEFAULT_MIN_PTS

    db = DBSCAN(eps=eps_rad, min_samples=min_pts, metric="haversine", algorithm="ball_tree").fit(x_rad)
    points_df["cluster_id"] = db.labels_.astype(int)

    output_uri = parquet_store.parquet_uri(f"{OUTPUT_TABLE}.parquet")
    con.register("coverage_holes_df", points_df)
    con.execute(f"COPY coverage_holes_df TO '{output_uri}' (FORMAT PARQUET, COMPRESSION SNAPPY)")
    return output_uri
