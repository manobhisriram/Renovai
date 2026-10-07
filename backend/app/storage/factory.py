from __future__ import annotations

from app.config import Settings
from app.storage.base import Storage
from app.storage.local import LocalStorage


def build_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "s3":
        from app.storage.s3 import S3Storage

        return S3Storage(settings)
    return LocalStorage(settings.upload_dir)
