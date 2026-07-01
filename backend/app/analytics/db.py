import duckdb

from app.core.config import settings


def get_connection() -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection, configured for S3 or local Parquet access.

    When USE_REAL_S3=true, installs and loads the httpfs extension so that
    read_parquet('s3://...') and COPY TO 's3://...' work transparently.
    On EC2 with an IAM role, credentials are picked up automatically via
    the instance metadata credential chain — no explicit keys required.
    """
    con = duckdb.connect(settings.duckdb_path)
    from app.ingestion.parquet_store import configure_s3
    configure_s3(con)
    if not settings.use_real_s3:
        con.execute(f"SET temp_directory = '{settings.parquet_dir}/.duckdb_tmp'")
    return con
