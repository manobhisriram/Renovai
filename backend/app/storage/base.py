from __future__ import annotations

import re
from typing import Protocol

_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-./]*$")


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def healthy(self) -> bool: ...


def validate_key(key: str) -> str:
    """Reject traversal and odd characters. Keys are always generated server-side."""
    if not _SAFE_KEY.match(key) or ".." in key.split("/") or key.startswith("/") or "//" in key:
        raise ValueError("unsafe storage key")
    return key
