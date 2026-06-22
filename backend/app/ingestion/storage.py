import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager

import boto3

from app.core.config import settings


def get_s3_client():
    """Returns a boto3 S3 client pointed at MinIO locally, real S3 in AWS phase.

    Same SDK calls work against both — only the endpoint_url changes.
    """
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
        keys.extend(obj["Key"] for obj in page.get("Contents", []))
    return keys
