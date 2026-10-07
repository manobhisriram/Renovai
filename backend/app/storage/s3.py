from __future__ import annotations

from typing import Any

from app.config import Settings
from app.storage.base import validate_key
from app.utils.errors import ExternalServiceError


class S3Storage:
    """S3-compatible object storage. Credentials come from the standard AWS chain (env vars / IAM role)."""

    def __init__(self, settings: Settings, client: Any | None = None):
        import boto3
        from botocore.config import Config

        self.bucket = settings.s3_bucket or ""
        self._client = client or boto3.client(
            "s3", region_name=settings.s3_region, endpoint_url=settings.s3_endpoint_url,
            config=Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=5, read_timeout=15),
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        key = validate_key(key)  # an unsafe key is a bug/attack, not a storage outage: raise ValueError like LocalStorage
        try:
            self._client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type, ServerSideEncryption="AES256")
        except Exception as exc:
            raise ExternalServiceError(f"Object storage write failed: {type(exc).__name__}") from exc

    def get(self, key: str) -> bytes:
        key = validate_key(key)
        try:
            return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as exc:
            raise ExternalServiceError(f"Object storage read failed: {type(exc).__name__}") from exc

    def delete(self, key: str) -> None:
        key = validate_key(key)
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            raise ExternalServiceError(f"Object storage delete failed: {type(exc).__name__}") from exc

    def healthy(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False
