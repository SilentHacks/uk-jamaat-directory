from __future__ import annotations

import asyncio
import uuid
from functools import lru_cache

import boto3
from botocore.exceptions import ClientError

from uk_jamaat_directory.config import Settings, get_settings

_CONTENT_TYPE_EXTENSIONS: dict[str, str] = {
    "application/json": "json",
    "text/html": "html",
    "application/pdf": "pdf",
    "text/plain": "txt",
}


def artifact_object_key(
    *,
    source_id: uuid.UUID,
    artifact_id: uuid.UUID,
    content_hash: str,
    content_type: str | None,
) -> str:
    ext = _CONTENT_TYPE_EXTENSIONS.get(content_type or "", "bin")
    prefix = content_hash[:16]
    return f"artifacts/{source_id}/{artifact_id}/{prefix}.{ext}"


@lru_cache
def _sync_client(
    endpoint_url: str,
    region_name: str,
    aws_access_key_id: str,
    aws_secret_access_key: str,
):
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region_name,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
    )


def _client_for_settings(settings: Settings):
    return _sync_client(
        settings.s3_endpoint_url,
        settings.s3_region,
        settings.s3_access_key_id,
        settings.s3_secret_access_key,
    )


class S3Storage:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def ensure_bucket(self) -> None:
        client = _client_for_settings(self._settings)
        bucket = self._settings.s3_bucket

        def _ensure() -> None:
            try:
                client.head_bucket(Bucket=bucket)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code in {"404", "NoSuchBucket", "NotFound"}:
                    client.create_bucket(Bucket=bucket)
                else:
                    raise

        await asyncio.to_thread(_ensure)

    async def put_bytes(self, key: str, body: bytes, content_type: str) -> None:
        client = _client_for_settings(self._settings)
        bucket = self._settings.s3_bucket

        def _put() -> None:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )

        await asyncio.to_thread(_put)

    async def get_bytes(self, key: str) -> bytes:
        client = _client_for_settings(self._settings)
        bucket = self._settings.s3_bucket

        def _get() -> bytes:
            response = client.get_object(Bucket=bucket, Key=key)
            return response["Body"].read()

        return await asyncio.to_thread(_get)

    async def head_object(self, key: str) -> bool:
        client = _client_for_settings(self._settings)
        bucket = self._settings.s3_bucket

        def _head() -> bool:
            try:
                client.head_object(Bucket=bucket, Key=key)
            except ClientError:
                return False
            return True

        return await asyncio.to_thread(_head)
