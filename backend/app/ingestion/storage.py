import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager

import boto3

from app.core.config import settings


def get_s3_client():
    """Returns a boto3 S3 client.

    When USE_REAL_S3=true points at AWS S3 — on EC2 with an IAM role attached,
    omitting credentials lets boto3 pick them up from the instance metadata
    automatically. When false, points at the local MinIO instance.
    """
    if settings.use_real_s3:
        kwargs: dict = {"region_name": settings.aws_region}
        if settings.aws_access_key and settings.aws_secret_key:
            kwargs["aws_access_key_id"] = settings.aws_access_key
            kwargs["aws_secret_access_key"] = settings.aws_secret_key
        return boto3.client("s3", **kwargs)
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )


@contextmanager
def staged_object(bucket: str, key: str) -> Iterator[str]:
    """Downloads one raw object to a local temp file, yields its path, deletes it on exit.

    Raw vendor files (xlsb/xlsx/csv) are 95-167MB each and must never persist
    on disk beyond the single transform that consumes them — the 40GB target
    EC2 instance has no room to accumulate raw + intermediate + Parquet copies.
    """
    client = get_s3_client()
    suffix = os.path.splitext(key)[1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name
    try:
        client.download_file(bucket, key, tmp_path)
        yield tmp_path
    finally:
        os.remove(tmp_path)


def list_objects(bucket: str, prefix: str) -> list[str]:
    client = get_s3_client()
    paginator = client.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(
            obj["Key"] for obj in page.get("Contents", [])
            if obj["Size"] > 0 and not obj["Key"].endswith("/")
        )
    return keys


@contextmanager
def stage_all(bucket: str, keys: list[str]) -> Iterator[list[str]]:
    """Download multiple S3 objects to local temp files, yield their paths,
    delete them all on exit — even if processing raises.

    Use when a stage needs all files present simultaneously (e.g. site_coordinates
    which unions every location export in one DuckDB query).
    """
    client = get_s3_client()
    tmp_paths: list[str] = []
    try:
        for key in keys:
            suffix = os.path.splitext(key)[1]
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp_path = tmp.name
            client.download_file(bucket, key, tmp_path)
            tmp_paths.append(tmp_path)
        yield tmp_paths
    finally:
        for p in tmp_paths:
            try:
                os.remove(p)
            except FileNotFoundError:
                pass
