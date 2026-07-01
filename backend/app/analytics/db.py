import duckdb

from app.core.config import settings


def _open(read_only: bool) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(settings.duckdb_path, read_only=read_only)
    from app.ingestion.parquet_store import configure_s3
    configure_s3(con)
    if not settings.use_real_s3 and not read_only:
        con.execute(f"SET temp_directory = '{settings.parquet_dir}/.duckdb_tmp'")
    return con


def get_connection() -> duckdb.DuckDBPyConnection:
    """Read-only DuckDB connection for analytics queries.

    Multiple uvicorn workers can open read-only connections simultaneously
    without lock conflicts. Use get_write_connection() for ETL stages.
    """
    return _open(read_only=True)


def get_write_connection() -> duckdb.DuckDBPyConnection:
    """Read-write DuckDB connection for ETL stages.

    Only one write connection can be held at a time — ETL runs serially
    so this is safe. Analytics queries use get_connection() (read-only)
    and won't block or be blocked by this.
    """
    return _open(read_only=False)
