"""Centralised, typed configuration. Nothing else in the codebase reads os.environ."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-insecure-secret-change-me-0000000000"  # noqa: S105  (rejected by production validation)


class ConfigurationError(RuntimeError):
    """Raised when required configuration is missing or unsafe."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Application -------------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "RenovAI"
    app_version: str = "1.0.0"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173"
    secret_key: SecretStr = SecretStr(DEV_SECRET)
    access_token_expire_minutes: int = 480
    allow_self_registration: bool = False
    seed_admin_email: str = "admin@renovai.local"
    seed_admin_password: SecretStr | None = None

    # --- Datastores --------------------------------------------------------
    database_url: str = "sqlite:///./renovai.db"
    redis_url: str | None = None
    graph_checkpoint_backend: Literal["auto", "memory", "sqlite", "postgres"] = "auto"
    graph_checkpoint_sqlite_path: str = "./renovai_checkpoints.db"

    # --- LLM ---------------------------------------------------------------
    llm_provider: Literal["anthropic", "openai", "mock"] = "anthropic"
    llm_model_simple: str = "claude-haiku-4-5-20251001"
    llm_model_medium: str = "claude-sonnet-5-5"
    llm_model_complex: str = "claude-opus-5-5"
    llm_fallback_enabled: bool = True
    llm_timeout_seconds: float = 90.0
    llm_max_retries: int = 3
    llm_max_output_tokens: int = 4096
    llm_task_tier_overrides: str = ""  # JSON: {"vision_analysis": "complex"}
    llm_pricing_json: str = ""  # JSON: {"model-prefix": {"input": 1.0, "output": 5.0}} USD per 1M tokens
    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_version: str = "2023-06-01"
    openai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"

    # --- RAG ---------------------------------------------------------------
    qdrant_url: str | None = None
    qdrant_api_key: SecretStr | None = None
    qdrant_local_path: str = "./qdrant_data"
    qdrant_collection: str = "renovai_knowledge"
    embedding_provider: Literal["hash", "sentence_transformers"] = "hash"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    rag_top_k: int = 6
    rag_candidate_k: int = 18
    rag_chunk_chars: int = 900
    rag_chunk_overlap: int = 120
    rag_context_max_chars: int = 7000

    cv_detector_model: str | None = None  # path/name of YOLO weights; requires requirements-ml.txt

    # --- Storage -----------------------------------------------------------
    storage_backend: Literal["local", "s3"] = "local"
    upload_dir: str = "./uploads"
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    max_upload_mb: int = 8
    max_images_per_project: int = 12
    max_image_pixels: int = 40_000_000

    # --- CRM ---------------------------------------------------------------
    crm_provider: Literal["internal", "hubspot", "google_sheets"] = "internal"
    hubspot_access_token: SecretStr | None = None
    hubspot_base_url: str = "https://api.hubapi.com"
    google_sheets_spreadsheet_id: str | None = None
    google_sheets_range: str = "Leads!A:L"
    google_service_account_json: SecretStr | None = None  # raw JSON string

    # --- Visualisation -----------------------------------------------------
    viz_provider: Literal["none", "openai_images"] = "none"
    viz_openai_model: str = "gpt-image-1"

    # --- Notifications -----------------------------------------------------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str = "renovai@localhost"
    notify_reviewer_email: str | None = None

    # --- Business rules ----------------------------------------------------
    default_currency: str = "INR"
    default_tax_pct: float = 18.0
    default_contingency_pct: float = 8.0
    default_logistics_pct: float = 3.0
    approval_require_always: bool = True
    approval_total_threshold: float = 2_500_000.0
    approval_min_confidence: float = 0.6
    max_clarification_rounds: int = 2

    # --- Security / limits -------------------------------------------------
    rate_limit_per_minute: int = 120
    auth_rate_limit_per_minute: int = 10
    tool_timeout_seconds: float = 15.0

    # --- Observability -----------------------------------------------------
    metrics_enabled: bool = True
    metrics_token: SecretStr | None = None  # if set, /metrics requires header X-Metrics-Token
    otel_exporter_otlp_endpoint: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    @field_validator("cors_origins")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    # ---- Derived helpers --------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def uses_postgres(self) -> bool:
        return self.database_url.startswith(("postgresql", "postgres"))

    @property
    def resolved_checkpoint_backend(self) -> str:
        if self.graph_checkpoint_backend != "auto":
            return self.graph_checkpoint_backend
        if self.is_test:
            return "memory"
        return "postgres" if self.uses_postgres else "sqlite"

    @property
    def task_tier_overrides(self) -> dict[str, str]:
        if not self.llm_task_tier_overrides.strip():
            return {}
        try:
            data = json.loads(self.llm_task_tier_overrides)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"LLM_TASK_TIER_OVERRIDES is not valid JSON: {exc}") from exc
        bad = {k: v for k, v in data.items() if v not in ("simple", "medium", "complex")}
        if bad:
            raise ConfigurationError(f"LLM_TASK_TIER_OVERRIDES has invalid tiers: {bad}")
        return dict(data)

    @property
    def llm_pricing(self) -> dict[str, dict[str, float]]:
        if not self.llm_pricing_json.strip():
            return {}
        try:
            return dict(json.loads(self.llm_pricing_json))
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"LLM_PRICING_JSON is not valid JSON: {exc}") from exc

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def secret_values(self) -> list[str]:
        """All configured secret strings, used by the log redactor."""
        out: list[str] = []
        for name in (
            "secret_key", "anthropic_api_key", "openai_api_key", "qdrant_api_key",
            "hubspot_access_token", "google_service_account_json", "smtp_password",
            "langfuse_secret_key", "seed_admin_password", "metrics_token",
        ):
            val = getattr(self, name)
            if val is not None and len(val.get_secret_value()) >= 6:
                out.append(val.get_secret_value())
        return out

    def missing_required(self) -> list[str]:
        """Human-readable list of configuration problems for the current mode."""
        problems: list[str] = []
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            problems.append("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic (create one at https://platform.claude.com)")
        if self.llm_provider == "openai" and not self.openai_api_key:
            problems.append("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        if self.crm_provider == "hubspot" and not self.hubspot_access_token:
            problems.append("HUBSPOT_ACCESS_TOKEN is required when CRM_PROVIDER=hubspot (HubSpot private app token)")
        if self.crm_provider == "google_sheets" and not (
            self.google_sheets_spreadsheet_id and self.google_service_account_json
        ):
            problems.append("GOOGLE_SHEETS_SPREADSHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON are required when CRM_PROVIDER=google_sheets")
        if self.storage_backend == "s3" and not (self.s3_bucket and self.s3_region):
            problems.append("S3_BUCKET and S3_REGION are required when STORAGE_BACKEND=s3")
        if self.viz_provider == "openai_images" and not self.openai_api_key:
            problems.append("OPENAI_API_KEY is required when VIZ_PROVIDER=openai_images")
        if self.is_production:
            secret = self.secret_key.get_secret_value()
            if secret == DEV_SECRET or len(secret) < 32:
                problems.append("SECRET_KEY must be a random string of at least 32 characters in production")
            if "*" in self.cors_origin_list:
                problems.append("CORS_ORIGINS must not contain '*' in production")
            if self.llm_provider == "mock":
                problems.append("LLM_PROVIDER=mock is not allowed in production")
            if self.database_url.startswith("sqlite"):
                problems.append("DATABASE_URL must point to PostgreSQL in production")
        return problems

    def validate_for_startup(self) -> None:
        problems = self.missing_required()
        if problems and self.is_production:
            raise ConfigurationError("Invalid production configuration:\n - " + "\n - ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
