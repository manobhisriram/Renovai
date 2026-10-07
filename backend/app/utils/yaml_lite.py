"""Minimal `key: value` front-matter parser (scalars + inline lists). Avoids a PyYAML dependency."""

from __future__ import annotations

from typing import Any


def _scalar(v: str) -> Any:
    v = v.strip().strip("'\"")
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def load_simple(block: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for line in block.splitlines():
        if not line.strip() or line.strip().startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            out[key.strip()] = [_scalar(x) for x in value[1:-1].split(",") if x.strip()]
        else:
            out[key.strip()] = _scalar(value)
    return out
