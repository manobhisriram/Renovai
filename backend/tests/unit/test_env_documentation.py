"""Fails if a Settings field exists that .env.example does not document (and vice versa), or if code reads os.environ directly."""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parents[3]
ENV_EXAMPLE = ROOT / ".env.example"
COMPOSE_ONLY = {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "QDRANT_IMAGE_TAG", "INSTALL_ML", "RUN_MIGRATIONS", "FORWARDED_ALLOW_IPS"}


def documented() -> set[str]:
    return set(re.findall(r"^([A-Z][A-Z0-9_]+)=", ENV_EXAMPLE.read_text(), re.M))


def test_every_setting_is_documented_in_env_example():
    fields = {name.upper() for name in Settings.model_fields}
    assert not fields - documented(), f"undocumented settings: {sorted(fields - documented())}"


def test_env_example_has_no_unknown_variables():
    fields = {name.upper() for name in Settings.model_fields}
    assert not documented() - fields - COMPOSE_ONLY, f"documented but unused: {sorted(documented() - fields - COMPOSE_ONLY)}"


def test_env_example_defaults_equal_code_defaults(tmp_path):
    """The example file must describe the real defaults (catches stale docs)."""
    text = ENV_EXAMPLE.read_text()
    env = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]+)=([^#]*?)\s*(#.*)?$", line)
        if m and m.group(2).strip() and m.group(1) not in COMPOSE_ONLY:
            env[m.group(1)] = m.group(2).strip()
    mismatches = []
    defaults = Settings(_env_file=None)
    for key, val in env.items():
        actual = getattr(defaults, key.lower())
        if hasattr(actual, "get_secret_value"):
            actual = actual.get_secret_value()
        if str(actual).lower() != val.lower() and not (isinstance(actual, float) and float(val) == actual):
            mismatches.append((key, val, actual))
    assert not mismatches, mismatches


def test_application_code_never_reads_environment_directly():
    offenders = [str(p) for p in (ROOT / "backend" / "app").rglob("*.py") if p.parent.name != "config" and re.search(r"os\.(environ|getenv)", p.read_text())]
    assert offenders == [], f"use app.config.Settings instead: {offenders}"
