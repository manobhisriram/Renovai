from __future__ import annotations

import pytest

from app.config import ConfigurationError
from tests.conftest import make_settings


def test_production_rejects_unsafe_defaults(tmp_path):
    s = make_settings(tmp_path, app_env="production", secret_key="short", llm_provider="mock", cors_origins="*")
    problems = " | ".join(s.missing_required())
    assert "SECRET_KEY" in problems and "CORS_ORIGINS" in problems and "mock" in problems and "PostgreSQL" in problems
    with pytest.raises(ConfigurationError):
        s.validate_for_startup()


def test_missing_credentials_are_actionable(tmp_path):
    s = make_settings(tmp_path, llm_provider="anthropic", crm_provider="hubspot", storage_backend="s3", viz_provider="openai_images")
    text = " ".join(s.missing_required())
    for needle in ("ANTHROPIC_API_KEY", "HUBSPOT_ACCESS_TOKEN", "S3_BUCKET", "OPENAI_API_KEY"):
        assert needle in text


def test_dev_mode_starts_even_when_incomplete(tmp_path):
    s = make_settings(tmp_path, llm_provider="anthropic")
    s.validate_for_startup()  # warns, does not raise, outside production


def test_valid_production_config_passes(tmp_path):
    s = make_settings(tmp_path, app_env="production", llm_provider="anthropic", anthropic_api_key="sk-ant-" + "x" * 20,
                      secret_key="s" * 40, database_url="postgresql://u:p@db/renovai")
    assert s.missing_required() == []


def test_checkpoint_backend_resolution(tmp_path):
    assert make_settings(tmp_path).resolved_checkpoint_backend == "memory"
    assert make_settings(tmp_path, app_env="development").resolved_checkpoint_backend == "sqlite"
    assert make_settings(tmp_path, app_env="development", database_url="postgresql://u@h/d").resolved_checkpoint_backend == "postgres"


def test_secret_values_collected_for_redaction(tmp_path):
    s = make_settings(tmp_path, anthropic_api_key="sk-ant-secretsecret")
    assert "sk-ant-secretsecret" in s.secret_values()
