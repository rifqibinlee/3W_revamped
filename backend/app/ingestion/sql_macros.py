"""Shared DuckDB macros for parsing vendor cell-name conventions.

Registered per-connection (DuckDB macros aren't persisted across
connections) and reused by every stage that needs to derive site_id,
sector suffix, F1/F2/F3 layer, or inbuilding/PBTS/macro classification
from a raw cell_name string — currently `cell_reference` and `xc_huawei`,
eventually `xd_zte`.

classify_f1f2f3's legacy regex uses a negative lookahead (`ML(?!C)`) which
DuckDB's RE2 engine doesn't support — approximated as "contains ML and
not MLC" (see docs/adr/0001-architecture.md addendum for why this is
equivalent for the data observed).
"""

_CLASSIFY_F1F2F3_MACRO = r"""
CREATE OR REPLACE MACRO classify_f1f2f3(cell_str) AS (
    CASE
        WHEN regexp_matches(cell_str, '^\d{2,3}$') THEN 'F1'
        WHEN regexp_matches(cell_str, '(_\d{2}_\d$)|(-XL\d+$)') THEN 'F3'
        WHEN regexp_matches(cell_str, 'CMM|BLC|DLC|MLC|PLC|CL|RAMO|[A-Z]{2}\d{5}_\d+_\d+') THEN 'F2'
        WHEN regexp_matches(cell_str, 'DMM|DLD|DL|LD|BL|UL|BLD')
            OR (cell_str ILIKE '%ML%' AND NOT cell_str ILIKE '%MLC%') THEN 'F1'
        ELSE 'F1'
    END
);
"""

_IBC_MACRO_MACRO = """
CREATE OR REPLACE MACRO classify_ibc_macro(cell_upper) AS (
    CASE
        WHEN cell_upper LIKE '%BL%' OR cell_upper LIKE '%IB %' OR cell_upper LIKE '%IB-%' THEN 'Inbuilding'
        WHEN cell_upper LIKE '%PL%' THEN 'PBTS'
        ELSE 'Macro'
    END
);
"""

_SITE_ID_MACRO = r"""
CREATE OR REPLACE MACRO extract_site_id(cell_name) AS (
    CASE
        WHEN cell_name LIKE '%\_%' ESCAPE '\' THEN split_part(cell_name, '_', 1)
        WHEN cell_name LIKE '%-%' THEN split_part(cell_name, '-', 1)
        ELSE cell_name
    END
);
"""

_SECTOR_SUFFIX_MACRO = r"""
CREATE OR REPLACE MACRO extract_sector_suffix(cell_name) AS (
    COALESCE(NULLIF(regexp_extract(reverse(cell_name), '\d'), ''), '1')
);
"""

ALL_MACROS = (
    _CLASSIFY_F1F2F3_MACRO,
    _IBC_MACRO_MACRO,
    _SITE_ID_MACRO,
    _SECTOR_SUFFIX_MACRO,
)


def register(con) -> None:
    for macro_sql in ALL_MACROS:
        con.execute(macro_sql)
