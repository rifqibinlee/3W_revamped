import duckdb

from app.core.config import settings


def get_connection() -> duckdb.DuckDBPyConnection:
    """Single shared DuckDB connection over the local Parquet warehouse.

    DuckDB is embedded (no server process) — safe to open per-request or
    per-job; callers are responsible for closing what they open.
    """
    con = duckdb.connect(settings.duckdb_path)
    con.execute(f"SET temp_directory = '{settings.parquet_dir}/.duckdb_tmp'")
    return con
