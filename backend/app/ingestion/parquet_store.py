"""Central routing for processed Parquet output paths.

Returns either a local filesystem path (local dev / MinIO mode) or an
S3 URI (production). DuckDB's COPY TO and read_parquet() accept both
transparently once httpfs is loaded — callers never need to know which
they're working with.

Local mode: path is created under settings.parquet_dir, parent dirs
  are mkdir'd here so callers don't have to.
S3 mode:    returns s3://<bucket>/<processed_prefix>/<filename>. DuckDB
  httpfs handles the write; no local disk used for the output.
"""

import os
from pathlib import Path

from app.core.config import settings


def parquet_uri(filename: str) -> str:
    """Return the storage URI for a named processed Parquet output file."""
    if settings.use_real_s3:
        prefix = settings.s3_processed_prefix.rstrip("/")
        return f"s3://{settings.s3_bucket}/{prefix}/{filename}"
    path = Path(settings.parquet_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def stem_from_uri(uri: str) -> str:
    """Extract the filename stem from either a local path or S3 URI.

    Replaces Path(uri).stem for code that constructs derivative output
    names from an upstream stage's return value — Path() mangles S3 URIs
    on Windows.
    """
    return os.path.splitext(os.path.basename(uri))[0]


def parquet_exists(uri: str) -> bool:
    """Check whether a processed Parquet file exists.

    For local paths uses os.path.exists. For S3 URIs, issues a cheap
    HeadObject call so callers can guard against querying files that the
    ETL pipeline hasn't produced yet.
    """
    if not uri.startswith("s3://"):
        return os.path.exists(uri)
    from app.ingestion.storage import get_s3_client
    without_scheme = uri[5:]
    bucket, key = without_scheme.split("/", 1)
    try:
        get_s3_client().head_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def parquet_glob_uri(filename_pattern: str) -> str:
    """Return a wildcard URI suitable for DuckDB's read_parquet() glob syntax.

    For local: '/data/parquet/capex_upgrades_*.parquet'
    For S3:    's3://bucket/processed/capex_upgrades_*.parquet'
    """
    if settings.use_real_s3:
        prefix = settings.s3_processed_prefix.rstrip("/")
        return f"s3://{settings.s3_bucket}/{prefix}/{filename_pattern}"
    return str(Path(settings.parquet_dir) / filename_pattern)


def list_parquet_glob(filename_pattern: str) -> list[str]:
    """Return all processed Parquet files matching a filename glob pattern.

    For local mode, globs settings.parquet_dir. For S3, lists objects whose
    key starts with the non-wildcard prefix of the pattern (e.g.
    'capex_upgrades_*.parquet' → prefix 'capex_upgrades_').
    """
    if settings.use_real_s3:
        from app.ingestion.storage import list_objects
        prefix_part = filename_pattern.split("*")[0]
        s3_prefix = f"{settings.s3_processed_prefix.rstrip('/')}/{prefix_part}"
        keys = list_objects(settings.s3_bucket, s3_prefix)
        return [f"s3://{settings.s3_bucket}/{k}" for k in keys if k.endswith(".parquet")]
    return [str(p) for p in Path(settings.parquet_dir).glob(filename_pattern)]


def configure_s3(con) -> None:
    """Install httpfs and configure S3 credentials on a DuckDB connection.

    Safe to call unconditionally — no-ops when use_real_s3 is false.
    On EC2 with an IAM role attached, leave aws_access_key/aws_secret_key
    blank and DuckDB will pick up credentials from the instance metadata
    automatically via the credential chain.
    """
    if not settings.use_real_s3:
        return
    con.execute("INSTALL httpfs; LOAD httpfs;")
    if settings.aws_access_key and settings.aws_secret_key:
        con.execute(
            f"CREATE OR REPLACE SECRET _3w_s3 ("
            f"TYPE S3, REGION '{settings.aws_region}', "
            f"KEY_ID '{settings.aws_access_key}', "
            f"SECRET '{settings.aws_secret_key}'"
            f");"
        )
    else:
        # IAM role attached to EC2 — use instance metadata credential chain
        con.execute(
            f"CREATE OR REPLACE SECRET _3w_s3 ("
            f"TYPE S3, PROVIDER CREDENTIAL_CHAIN, REGION '{settings.aws_region}'"
            f");"
        )
