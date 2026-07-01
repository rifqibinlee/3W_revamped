"""Master cell-hardware reference: XTXR/MIMO config, band, layer (F1/F2/F3),
available PRB, area_target/bau_nic classification per cell.

Extracted from 4 legacy scripts (xC Huawei Dataset.py, xD (ZTE Dataset).py,
Pre-Capacity-CAPEX-Upgrades.py, Capacity-CAPEX-Upgrades.py) which each
independently re-parsed `reference xC & xD cell_Dec25.xlsb` from scratch —
see docs/adr/0001-architecture.md addendum. This stage parses it once.

Column detection (which column holds band/xtxr/bandwidth) stays in Python
since it varies per source sheet ("xC ref" / "xD ref"). The per-cell
parsing (site_id, sector suffix, F1/F2/F3 classification, zoom_sector_id,
avail_prb) is pushed into DuckDB SQL as a single vectorized pass instead of
the legacy `master_ref.itertuples()` Python loop.

Note: classify_f1f2f3's legacy regex uses a negative lookahead
(`ML(?!C)` — match "ML" not followed by "C") which DuckDB's RE2 engine
doesn't support. Approximated below as "contains ML and does not contain
MLC", which is equivalent unless a cell name has both ML and MLC as
separate occurrences — not observed in the legacy reference data.
"""

import tempfile
from pathlib import Path

import pandas as pd

from app.analytics.db import get_connection
from app.ingestion import parquet_store
from app.ingestion import parquet_safe, sql_macros

OUTPUT_TABLE = "cell_reference"

CELL_KEYWORDS = ("cell_name", "cellname", "cell")
BAND_EXCLUDE = ("width", "mhz")
BAND_KEYWORDS = ("band", "layer")
XTXR_KEYWORDS = ("txrx", "xtxr", "mimo", "antenna")
BW_KEYWORDS = ("bw", "width", "mhz")
AREA_TARGET_KEYWORDS = ("urban", "kmc", "target", "outside")
BAU_NIC_KEYWORDS = ("bau", "nic")

REF_SHEET_MARKERS = ("xc ref", "xd ref")


def _detect_column(columns: list[str], keywords: tuple[str, ...], exclude: tuple[str, ...] = ()) -> str | None:
    for col in columns:
        cl = col.lower().strip()
        if any(k in cl for k in keywords) and not any(x in cl for x in exclude):
            return col
    return None


def _excel_ref_sheets_to_parquet(path: str) -> list[str]:
    """Only sheets named like 'xC ref' / 'xD ref' hold reference data —
    other sheets in the same workbook are notes/lookups, mirroring the
    legacy script's `if 'xc ref' in sheet_name.lower()...` filter."""
    engine = "pyxlsb" if path.lower().endswith(".xlsb") else None
    xls = pd.ExcelFile(path, engine=engine)
    out_paths = []
    for sheet in xls.sheet_names:
        if not any(marker in sheet.lower() for marker in REF_SHEET_MARKERS):
            continue
        df = xls.parse(sheet_name=sheet)
        if df.empty:
            continue
        tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
        tmp.close()  # Windows can't delete a file with an open handle later
        parquet_safe.to_parquet(df, tmp.name)
        out_paths.append(tmp.name)
    xls.close()
    return out_paths


def _select_clause(columns: list[str]) -> str | None:
    cell_col = _detect_column(columns, CELL_KEYWORDS)
    if not cell_col:
        return None

    band_col = _detect_column(columns, BAND_KEYWORDS, exclude=BAND_EXCLUDE)
    xtxr_col = _detect_column(columns, XTXR_KEYWORDS)
    bw_col = _detect_column(columns, BW_KEYWORDS)
    area_target_col = _detect_column(columns, AREA_TARGET_KEYWORDS)
    bau_nic_col = _detect_column(columns, BAU_NIC_KEYWORDS)

    band_expr = f'normalize_band_key(CAST("{band_col}" AS VARCHAR))' if band_col else "CAST(NULL AS VARCHAR)"
    xtxr_expr = f'CAST("{xtxr_col}" AS VARCHAR)' if xtxr_col else "'2T2R'"
    bw_expr = f'TRY_CAST("{bw_col}" AS DOUBLE)' if bw_col else "0.0"
    area_target_expr = f'CAST("{area_target_col}" AS VARCHAR)' if area_target_col else "CAST(NULL AS VARCHAR)"
    bau_nic_expr = f'CAST("{bau_nic_col}" AS VARCHAR)' if bau_nic_col else "CAST(NULL AS VARCHAR)"

    return f"""
        SELECT
            trim(CAST("{cell_col}" AS VARCHAR)) AS cell_name,
            {band_expr} AS band_raw,
            COALESCE({xtxr_expr}, '2T2R') AS xtxr,
            COALESCE({bw_expr}, 0.0) * 5.0 AS avail_prb,
            nullif(trim({area_target_expr}), '') AS area_target,
            nullif(trim({bau_nic_expr}), '') AS bau_nic
        FROM read_file
    """


_NORMALIZE_BAND_MACRO = """
CREATE OR REPLACE MACRO normalize_band_key(raw_band) AS (
    CASE
        WHEN raw_band IS NULL THEN NULL
        WHEN upper(raw_band) LIKE '%900%' OR upper(raw_band) LIKE '%L9%' THEN 'L9'
        WHEN upper(raw_band) LIKE '%1800%' OR upper(raw_band) LIKE '%L18%' OR upper(raw_band) LIKE '%1.8%' THEN 'L18'
        WHEN upper(raw_band) LIKE '%2100%' OR upper(raw_band) LIKE '%L21%' OR upper(raw_band) LIKE '%2.1%' THEN 'L21'
        WHEN upper(raw_band) LIKE '%2600%' OR upper(raw_band) LIKE '%L26%' OR upper(raw_band) LIKE '%2.6%' THEN 'L26'
        ELSE 'UNKNOWN'
    END
);
"""

_EXTRACT_BAND_FROM_CELL_MACRO = """
CREATE OR REPLACE MACRO band_from_cell_name(cell_str) AS (
    CASE
        WHEN cell_str ILIKE '%900%' OR cell_str ILIKE '%L9%' OR cell_str ILIKE '%_9_%' OR cell_str ILIKE '%-9%' THEN 'L9'
        WHEN cell_str ILIKE '%1800%' OR cell_str ILIKE '%L18%' OR cell_str ILIKE '%_18_%' OR cell_str ILIKE '%-18%' THEN 'L18'
        WHEN cell_str ILIKE '%2100%' OR cell_str ILIKE '%L21%' OR cell_str ILIKE '%_21_%' OR cell_str ILIKE '%-21%' THEN 'L21'
        WHEN cell_str ILIKE '%2600%' OR cell_str ILIKE '%L26%' OR cell_str ILIKE '%_26_%' OR cell_str ILIKE '%-26%'
            OR cell_str ILIKE '%_7_%' OR cell_str ILIKE '%-7%' THEN 'L26'
        ELSE 'UNKNOWN'
    END
);
"""

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
    con.execute(_NORMALIZE_BAND_MACRO)
    con.execute(_EXTRACT_BAND_FROM_CELL_MACRO)
    sql_macros.register(con)

    selects: list[str] = []
    i = 0

    for path in raw_file_paths:
        sources = [path] if path.lower().endswith(".csv") else _excel_ref_sheets_to_parquet(path)
        temp_parquets.extend(p for p in sources if p != path)

        for source in sources:
            reader = "read_csv" if source.lower().endswith(".csv") else "read_parquet"
            # sample_size=-1 scans the whole file for type inference instead
            # of the first ~20k rows, avoiding cast errors on columns that
            # are numeric early on but switch to text later in large files.
            reader_opts = ", ignore_errors=true, delim=',', quote='\"', escape='\"', sample_size=-1, max_line_size=10000000, strict_mode=false, null_padding=true, parallel=false" if reader == "read_csv" else ""
            con.execute(f"CREATE OR REPLACE TEMP VIEW read_file AS SELECT * FROM {reader}('{source}'{reader_opts})")
            columns = [r[0] for r in con.execute("DESCRIBE read_file").fetchall()]
            clause = _select_clause(columns)
            if clause:
                con.execute(f"CREATE OR REPLACE TEMP TABLE file_{i} AS {clause}")
                selects.append(f"SELECT * FROM file_{i}")
                i += 1

    if not selects:
        raise ValueError("No reference file had a detectable cell name column")

    union_sql = " UNION ALL ".join(selects)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE parsed AS
        WITH base AS (
            SELECT
                cell_name,
                upper(cell_name) AS cell_upper,
                band_raw,
                xtxr,
                avail_prb,
                area_target,
                bau_nic,
                CASE
                    WHEN cell_name LIKE '%\\_%' ESCAPE '\\' THEN split_part(cell_name, '_', 1)
                    WHEN cell_name LIKE '%-%' THEN split_part(cell_name, '-', 1)
                    ELSE cell_name
                END AS site_id,
                CASE
                    WHEN cell_name LIKE '%\\_%' ESCAPE '\\' THEN regexp_extract(cell_name, '([^_]+)$')
                    WHEN cell_name LIKE '%-%' THEN regexp_extract(cell_name, '([^-]+)$')
                    ELSE cell_name
                END AS last_token
            FROM ({union_sql})
        )
        SELECT
            cell_name,
            site_id,
            COALESCE(NULLIF(regexp_extract(reverse(last_token), '\\d'), ''), '1') AS sector_suffix,
            CASE
                WHEN cell_upper LIKE '%BL%' OR cell_upper LIKE '%IB %' OR cell_upper LIKE '%IB-%' THEN 'Inbuilding'
                WHEN cell_upper LIKE '%PL%' THEN 'PBTS'
                ELSE 'Macro'
            END AS ibc_macro,
            classify_f1f2f3(cell_upper) AS f1f2f3,
            COALESCE(band_raw, band_from_cell_name(cell_upper)) AS band,
            xtxr,
            avail_prb,
            area_target,
            bau_nic
        FROM base
    """)

    output_path = parquet_store.parquet_uri(f"{OUTPUT_TABLE}.parquet")
    con.execute(f"""
        COPY (
            SELECT
                cell_name,
                upper(regexp_replace(cell_name, '[^A-Za-z0-9]', '', 'g')) AS join_key,
                upper(site_id) || '_' || ibc_macro || '_' || sector_suffix AS zoom_sector_id,
                site_id,
                sector_suffix,
                ibc_macro,
                f1f2f3,
                band,
                xtxr,
                avail_prb,
                area_target,
                bau_nic
            FROM parsed
        ) TO '{output_path}' (FORMAT PARQUET, COMPRESSION SNAPPY)
    """)
    return output_path
