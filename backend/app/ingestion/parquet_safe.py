"""Defensive Parquet write for pandas DataFrames built from messy vendor
Excel sheets.

Real exports routinely have a column that's numeric for most rows but
holds a literal "Unknown"/"Pending"/etc. string in a handful of others —
pyarrow's strict type inference throws on the whole column when that
happens, even when downstream SQL never touches that specific column.

`to_parquet` tries the normal write first (no behavior change for the
common case); only on failure does it fall back to stringifying
object-dtype columns. Critically, this preserves real `NaN`/`None` as
nulls rather than turning them into the literal string "nan" — a blanket
`df.astype(str)` would do that and silently break every downstream
`COALESCE(col, 'Unknown')` check, since "nan" is non-null.
"""

import pandas as pd


def to_parquet(df: pd.DataFrame, path: str) -> None:
    try:
        df.to_parquet(path, engine="pyarrow")
        return
    except Exception:
        pass

    safe_df = df.copy()
    for col in safe_df.columns:
        if safe_df[col].dtype == object:
            safe_df[col] = safe_df[col].apply(lambda x: None if pd.isna(x) else str(x))
    safe_df.to_parquet(path, engine="pyarrow")
