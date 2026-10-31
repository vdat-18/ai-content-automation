"""Typed process settings loaded directly from environment variables."""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_content.platform.artifacts import ObjectStorageSettings
from ai_content.platform.observability import ObservabilitySettings


class ApplicationSettings(BaseSettings):
    """Single environment boundary for API, worker and maintenance entrypoints."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    data_root: Path = Field(Path(".creative-pilot"), validation_alias="AIC_AI_DATA_ROOT")
    config_dir: Path = Field(Path("config"), validation_alias="AIC_AI_CONFIG_DIR")

    # --- Brief & ideas preparation (BAML) ---
    prep_base_url: str = Field("http://127.0.0.1:1234/v1", validation_alias="AIC_PREP_BASE_URL")
    prep_api_key: SecretStr | None = Field(None, validation_alias="AIC_PREP_API_KEY")
    prep_model: str = Field("xai/grok-4-fast-reasoning", validation_alias="AIC_PREP_MODEL")
    prep_reasoning_effort: str = Field("medium", validation_alias="AIC_PREP_REASONING_EFFORT")
    prep_max_tokens: int = Field(12000, gt=0, validation_alias="AIC_PREP_MAX_TOKENS")
    prep_max_attempts: int = Field(3, ge=1, le=3, validation_alias="AIC_PREP_MAX_ATTEMPTS")
    prep_timeout: float = Field(90, gt=0, validation_alias="AIC_PREP_TIMEOUT")

    # --- Creative orchestration (BAML) ---
    orch_base_url: str = Field("http://127.0.0.1:1234/v1", validation_alias="AIC_ORCH_BASE_URL")
    orch_api_key: SecretStr | None = Field(None, validation_alias="AIC_ORCH_API_KEY")
    orch_model: str = Field("xai/grok-4-fast-reasoning", validation_alias="AIC_ORCH_MODEL")
    orch_reasoning_effort: str = Field("medium", validation_alias="AIC_ORCH_REASONING_EFFORT")
    orch_max_tokens: int = Field(32000, gt=0, validation_alias="AIC_ORCH_MAX_TOKENS")
    orch_max_attempts: int = Field(3, ge=1, le=5, validation_alias="AIC_ORCH_MAX_ATTEMPTS")
    orch_timeout: float = Field(180, gt=0, validation_alias="AIC_ORCH_TIMEOUT")

    # --- Image & video generation ---
    image_base_url: str = Field("http://127.0.0.1:1234/v1", validation_alias="AIC_IMAGE_BASE_URL")
    image_api_key: SecretStr | None = Field(None, validation_alias="AIC_IMAGE_API_KEY")
    video_base_url: str = Field("http://127.0.0.1:1234/v1", validation_alias="AIC_VIDEO_BASE_URL")
    video_api_key: SecretStr | None = Field(None, validation_alias="AIC_VIDEO_API_KEY")
    managed_media_config: Path | None = Field(None, validation_alias="AIC_AI_MANAGED_MEDIA_CONFIG")

    # --- Research reference screening ---
    screening_base_url: str = Field(
        "http://127.0.0.1:1234/v1", validation_alias="AIC_SCREENING_BASE_URL"
    )
    screening_api_key: SecretStr | None = Field(None, validation_alias="AIC_SCREENING_API_KEY")
    screening_model: str = Field("gemini-3.8-flash", validation_alias="AIC_SCREENING_MODEL")
    screening_max_concurrency: int = Field(
        5, ge=1, le=12, validation_alias="AIC_SCREENING_MAX_CONCURRENCY"
    )
    screening_timeout: float = Field(60, gt=0, validation_alias="AIC_SCREENING_TIMEOUT")

    # --- Performance learning / creative feedback (BAML) ---
    learning_base_url: str = Field(
        "http://127.0.0.1:1234/v1", validation_alias="AIC_LEARNING_BASE_URL"
    )
    learning_api_key: SecretStr | None = Field(None, validation_alias="AIC_LEARNING_API_KEY")
    learning_model: str = Field("xai/grok-4-fast-reasoning", validation_alias="AIC_LEARNING_MODEL")
    learning_timeout: float = Field(60, gt=0, validation_alias="AIC_LEARNING_TIMEOUT")
    media_asset_max_image_bytes: int = Field(
        100_000_000, gt=0, validation_alias="AIC_MEDIA_ASSET_MAX_IMAGE_BYTES"
    )
    media_asset_max_video_bytes: int = Field(
        1_000_000_000, gt=0, validation_alias="AIC_MEDIA_ASSET_MAX_VIDEO_BYTES"
    )
    media_asset_max_image_pixels: int = Field(
        100_000_000, gt=0, validation_alias="AIC_MEDIA_ASSET_MAX_IMAGE_PIXELS"
    )
    media_asset_max_video_duration_seconds: int = Field(
        600, gt=0, validation_alias="AIC_MEDIA_ASSET_MAX_VIDEO_DURATION_SECONDS"
    )
    media_asset_max_working_image_pixels: int = Field(
        16_777_216, gt=0, validation_alias="AIC_MEDIA_ASSET_MAX_WORKING_IMAGE_PIXELS"
    )
    media_asset_max_preview_image_pixels: int = Field(
        2_073_600, gt=0, validation_alias="AIC_MEDIA_ASSET_MAX_PREVIEW_IMAGE_PIXELS"
    )
    media_asset_processing_timeout_seconds: int = Field(
        120, gt=0, validation_alias="AIC_MEDIA_ASSET_PROCESSING_TIMEOUT_SECONDS"
    )
    data_sources_config: Path | None = Field(None, validation_alias="AIC_AI_DATA_SOURCES_CONFIG")
    data_source_timeout_seconds: float = Field(
        60, gt=0, le=60, validation_alias="AIC_AI_DATA_SOURCE_TIMEOUT_SECONDS"
    )
    research_crawl_timeout_seconds: float = Field(
        300, gt=0, le=300, validation_alias="AIC_AI_RESEARCH_CRAWL_TIMEOUT_SECONDS"
    )
    jev_api_url: str | None = Field(None, validation_alias="AIC_AI_JEV_API_URL")
    jev_api_key: SecretStr | None = Field(
        None, validation_alias=AliasChoices("AIC_JEV_API_KEY", "JEV_API_KEY")
    )
    research_cookies_file: Path | None = Field(
        None, validation_alias="AIC_AI_RESEARCH_COOKIES_FILE"
    )
    jev_navigation_model: str = Field(
        "jev-latest",
        validation_alias=AliasChoices("AIC_AI_JEV_MODEL", "AIC_AI_RESEARCH_CLASSIFICATION_MODEL"),
    )
    data_source_sync_interval_seconds: float | None = Field(
        None, ge=60, le=86400, validation_alias="AIC_AI_DATA_SOURCE_SYNC_INTERVAL_SECONDS"
    )
    meta_token_expires_at: datetime | None = Field(
        None, validation_alias="META_ACCESS_TOKEN_EXPIRES_AT"
    )
    google_ads_token_expires_at: datetime | None = Field(
        None, validation_alias="GOOGLE_ADS_ACCESS_TOKEN_EXPIRES_AT"
    )
    shopify_token_expires_at: datetime | None = Field(
        None, validation_alias="SHOPIFY_ACCESS_TOKEN_EXPIRES_AT"
    )
    database_backend: Literal["sqlite", "postgresql"] = Field(
        "sqlite", validation_alias="AIC_AI_DATABASE_BACKEND"
    )
    database_url: SecretStr | None = Field(None, validation_alias="AIC_AI_DATABASE_URL")
    execution_backend: Literal["lease_worker", "celery"] = Field(
        "lease_worker", validation_alias="AIC_AI_EXECUTION_BACKEND"
    )
    celery_broker_url: SecretStr | None = Field(None, validation_alias="AIC_AI_CELERY_BROKER_URL")
    celery_retry_delay_seconds: int = Field(
        5, ge=0, validation_alias="AIC_AI_CELERY_RETRY_DELAY_SECONDS"
    )
    celery_retry_poll_interval_seconds: int = Field(
        60,
        ge=1,
        le=300,
        validation_alias="AIC_AI_CELERY_RETRY_POLL_INTERVAL_SECONDS",
    )
    celery_command_lease_seconds: int = Field(
        120, ge=60, validation_alias="AIC_AI_CELERY_COMMAND_LEASE_SECONDS"
    )
    celery_task_time_limit_seconds: int = Field(
        3600, ge=60, validation_alias="AIC_AI_CELERY_TASK_TIME_LIMIT_SECONDS"
    )
    creative_automation_max_concurrency: int = Field(
        10, ge=1, le=20, validation_alias="AIC_AI_CREATIVE_AUTOMATION_MAX_CONCURRENCY"
    )
    creative_automation_allow_cached_shopify_fallback: bool = Field(
        False,
        validation_alias="AIC_AI_CREATIVE_AUTOMATION_ALLOW_CACHED_SHOPIFY_FALLBACK",
    )
    creative_automation_default_market: str = Field(
        "US",
        min_length=2,
        max_length=2,
        validation_alias="AIC_AI_CREATIVE_AUTOMATION_DEFAULT_MARKET",
    )
    creative_automation_video_duration_min_seconds: int = Field(
        15, ge=1, validation_alias="AIC_AI_CREATIVE_AUTOMATION_VIDEO_DURATION_MIN_SECONDS"
    )
    creative_automation_video_duration_max_seconds: int = Field(
        60, ge=1, validation_alias="AIC_AI_CREATIVE_AUTOMATION_VIDEO_DURATION_MAX_SECONDS"
    )
    # Clips of 5-8 seconds stay stable; longer single generations distort products and people.
    creative_automation_video_source_duration_max_seconds: int = Field(
        8, ge=1, validation_alias="AIC_AI_CREATIVE_AUTOMATION_VIDEO_SOURCE_DURATION_MAX_SECONDS"
    )
    celery_broker_connection_timeout_seconds: int = Field(
        10, ge=1, le=60, validation_alias="AIC_AI_CELERY_BROKER_CONNECTION_TIMEOUT_SECONDS"
    )
    outbox_poll_interval_seconds: float = Field(
        1, gt=0, le=60, validation_alias="AIC_AI_OUTBOX_POLL_INTERVAL_SECONDS"
    )
    outbox_batch_size: int = Field(20, ge=1, le=1000, validation_alias="AIC_AI_OUTBOX_BATCH_SIZE")
    outbox_lease_seconds: int = Field(30, ge=5, validation_alias="AIC_AI_OUTBOX_LEASE_SECONDS")
    outbox_retry_delay_seconds: int = Field(
        5, ge=0, validation_alias="AIC_AI_OUTBOX_RETRY_DELAY_SECONDS"
    )
    environment: str = Field("development", validation_alias="AIC_AI_ENVIRONMENT")
    cors_allow_origin: str | None = Field(None, validation_alias="AIC_CORS_ALLOW_ORIGINS")

    object_storage_backend: Literal["filesystem", "s3"] = Field(
        "filesystem", validation_alias="AIC_AI_OBJECT_STORAGE_BACKEND"
    )
    s3_endpoint_url: str | None = Field(None, validation_alias="AIC_AI_S3_ENDPOINT_URL")
    s3_bucket: str = Field("aicontent-ai-artifacts", validation_alias="AIC_AI_S3_BUCKET")
    s3_access_key: SecretStr | None = Field(None, validation_alias="AIC_AI_S3_ACCESS_KEY")
    s3_secret_key: SecretStr | None = Field(None, validation_alias="AIC_AI_S3_SECRET_KEY")
    s3_region: str = Field("us-east-1", validation_alias="AIC_AI_S3_REGION")
    backup_offsite_enabled: bool = Field(False, validation_alias="AIC_BACKUP_OFFSITE_ENABLED")
    backup_s3_endpoint_url: str | None = Field(None, validation_alias="AIC_BACKUP_S3_ENDPOINT_URL")
    backup_s3_bucket: str | None = Field(None, validation_alias="AIC_BACKUP_S3_BUCKET")
    backup_s3_access_key: SecretStr | None = Field(
        None, validation_alias="AIC_BACKUP_S3_ACCESS_KEY"
    )
    backup_s3_secret_key: SecretStr | None = Field(
        None, validation_alias="AIC_BACKUP_S3_SECRET_KEY"
    )
    backup_s3_region: str = Field("us-east-1", validation_alias="AIC_BACKUP_S3_REGION")
    backup_s3_prefix: str = Field(
        "aicontent-backups", min_length=1, validation_alias="AIC_BACKUP_S3_PREFIX"
    )

    tracing_enabled: bool = Field(False, validation_alias="AIC_AI_TRACING_ENABLED")
    otlp_traces_endpoint: str | None = Field(None, validation_alias="AIC_AI_OTLP_TRACES_ENDPOINT")
    trace_sample_ratio: float = Field(1.0, ge=0, le=1, validation_alias="AIC_AI_TRACE_SAMPLE_RATIO")
    metrics_enabled: bool = Field(True, validation_alias="AIC_AI_METRICS_ENABLED")
    metrics_port: int = Field(9464, ge=1, le=65535, validation_alias="AIC_AI_METRICS_PORT")
    command_metrics_interval_seconds: float = Field(
        15, gt=0, validation_alias="AIC_AI_COMMAND_METRICS_INTERVAL_SECONDS"
    )
    log_format: Literal["text", "json"] = Field("text", validation_alias="AIC_AI_LOG_FORMAT")
    ai_telemetry_enabled: bool = Field(False, validation_alias="AIC_AI_AI_TELEMETRY_ENABLED")
    langfuse_otlp_endpoint: str | None = Field(
        None, validation_alias="AIC_AI_LANGFUSE_OTLP_ENDPOINT"
    )
    langfuse_public_key: str | None = Field(None, validation_alias="AIC_AI_LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: SecretStr | None = Field(
        None, validation_alias="AIC_AI_LANGFUSE_SECRET_KEY"
    )

    shopify_access_token: SecretStr | None = Field(None, validation_alias="SHOPIFY_ACCESS_TOKEN")
    shopify_demohome_access_token: SecretStr | None = Field(
        None, validation_alias="SHOPIFY_DEMOHOME_ACCESS_TOKEN"
    )
    shopify_demofurn_access_token: SecretStr | None = Field(
        None, validation_alias="SHOPIFY_DEMOFURN_ACCESS_TOKEN"
    )
    shopify_demohome_client_id: str | None = Field(
        None, validation_alias="SHOPIFY_DEMOHOME_CLIENT_ID"
    )
    shopify_demohome_client_secret: SecretStr | None = Field(
        None, validation_alias="SHOPIFY_DEMOHOME_CLIENT_SECRET"
    )
    shopify_demofurn_client_id: str | None = Field(
        None, validation_alias="SHOPIFY_DEMOFURN_CLIENT_ID"
    )
    shopify_demofurn_client_secret: SecretStr | None = Field(
        None, validation_alias="SHOPIFY_DEMOFURN_CLIENT_SECRET"
    )
    lark_tenant_access_token: SecretStr | None = Field(
        None, validation_alias="LARK_TENANT_ACCESS_TOKEN"
    )
    lark_app_id: str | None = Field(None, validation_alias="LARK_APP_ID")
    lark_app_secret: SecretStr | None = Field(None, validation_alias="LARK_APP_SECRET")
    google_access_token: SecretStr | None = Field(None, validation_alias="GOOGLE_ACCESS_TOKEN")
    meta_access_token: SecretStr | None = Field(None, validation_alias="META_ACCESS_TOKEN")
    google_ads_access_token: SecretStr | None = Field(
        None, validation_alias="GOOGLE_ADS_ACCESS_TOKEN"
    )
    google_ads_client_id: str | None = Field(None, validation_alias="GOOGLE_ADS_CLIENT_ID")
    google_ads_client_secret: SecretStr | None = Field(
        None, validation_alias="GOOGLE_ADS_CLIENT_SECRET"
    )
    google_ads_refresh_token: SecretStr | None = Field(
        None, validation_alias="GOOGLE_ADS_REFRESH_TOKEN"
    )
    google_ads_developer_token: SecretStr | None = Field(
        None, validation_alias="GOOGLE_ADS_DEVELOPER_TOKEN"
    )
    google_ads_login_customer_id: str | None = Field(
        None, validation_alias="GOOGLE_ADS_LOGIN_CUSTOMER_ID"
    )
    pinterest_access_token: SecretStr | None = Field(
        None, validation_alias="PINTEREST_ACCESS_TOKEN"
    )
    google_merchant_access_token: SecretStr | None = Field(
        None, validation_alias="GOOGLE_MERCHANT_ACCESS_TOKEN"
    )
    klaviyo_api_key: SecretStr | None = Field(None, validation_alias="KLAVIYO_API_KEY")

    @field_validator(
        "data_sources_config",
        "research_cookies_file",
        mode="before",
    )
    @classmethod
    def empty_optional_path(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator(
        "data_source_sync_interval_seconds",
        "meta_token_expires_at",
        "google_ads_token_expires_at",
        "shopify_token_expires_at",
        mode="before",
    )
    @classmethod
    def empty_optional_data_source_value(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator(
        "langfuse_otlp_endpoint",
        "langfuse_public_key",
        "langfuse_secret_key",
        mode="before",
    )
    @classmethod
    def empty_optional_observability_value(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_runtime_dependencies(self) -> "ApplicationSettings":
        if self.database_backend == "postgresql" and self.database_url is None:
            raise ValueError("AIC_AI_DATABASE_URL is required for the PostgreSQL backend")
        if self.execution_backend == "celery":
            if self.database_backend != "postgresql":
                raise ValueError("Celery execution requires the PostgreSQL database backend")
            if self.celery_broker_url is None:
                raise ValueError("AIC_AI_CELERY_BROKER_URL is required for Celery")
        if (
            self.creative_automation_video_duration_max_seconds
            < self.creative_automation_video_duration_min_seconds
        ):
            raise ValueError("Creative automation video duration range is invalid")
        if (
            self.creative_automation_video_source_duration_max_seconds
            > self.creative_automation_video_duration_max_seconds
        ):
            raise ValueError("Creative automation source duration cannot exceed the final maximum")
        if self.media_asset_max_preview_image_pixels > self.media_asset_max_working_image_pixels:
            raise ValueError(
                "AIC_MEDIA_ASSET_MAX_PREVIEW_IMAGE_PIXELS cannot exceed "
                "AIC_MEDIA_ASSET_MAX_WORKING_IMAGE_PIXELS"
            )
        if self.object_storage_backend == "s3" and not all(
            (self.s3_endpoint_url, self.s3_bucket, self.s3_access_key, self.s3_secret_key)
        ):
            raise ValueError(
                "S3 object storage requires endpoint, bucket, access key and secret key"
            )
        if self.backup_offsite_enabled and not all(
            (
                self.backup_s3_endpoint_url,
                self.backup_s3_bucket,
                self.backup_s3_access_key,
                self.backup_s3_secret_key,
            )
        ):
            raise ValueError("Off-site backup requires endpoint, bucket, access key and secret key")
        return self

    @property
    def preparation_config_path(self) -> Path:
        return self.config_dir / "preparation/synthetic.json"

    @property
    def orchestration_config_path(self) -> Path:
        return self.config_dir / "orchestration/synthetic.json"

    @property
    def learning_config(self) -> Path | None:
        return None

    @property
    def research_screening_config(self) -> Path | None:
        return None

    @property
    def prep_api_key_value(self) -> str | None:
        return self.prep_api_key.get_secret_value() if self.prep_api_key else None

    @property
    def orch_api_key_value(self) -> str | None:
        return self.orch_api_key.get_secret_value() if self.orch_api_key else None

    @property
    def image_api_key_value(self) -> str | None:
        return self.image_api_key.get_secret_value() if self.image_api_key else None

    @property
    def video_api_key_value(self) -> str | None:
        return self.video_api_key.get_secret_value() if self.video_api_key else None

    @property
    def screening_api_key_value(self) -> str | None:
        return self.screening_api_key.get_secret_value() if self.screening_api_key else None

    @property
    def learning_api_key_value(self) -> str | None:
        return self.learning_api_key.get_secret_value() if self.learning_api_key else None

    @property
    def jev_api_key_value(self) -> str | None:
        return self.jev_api_key.get_secret_value() if self.jev_api_key else None

    def credential(self, name: str | None) -> str | None:
        if name is None:
            return None
        credentials: dict[str, str | None] = {
            "ROUTER_API_KEY": self.orch_api_key_value or self.prep_api_key_value,
            "JEV_API_KEY": self.jev_api_key_value,
            "VILAO_API_KEY": self.screening_api_key_value,
            "IMAGE_API_KEY": self.image_api_key_value,
            "VIDEO_API_KEY": self.video_api_key_value,
            "AIC_PREP_API_KEY": self.prep_api_key_value,
            "AIC_ORCH_API_KEY": self.orch_api_key_value,
            "AIC_IMAGE_API_KEY": self.image_api_key_value,
            "AIC_VIDEO_API_KEY": self.video_api_key_value,
            "AIC_SCREENING_API_KEY": self.screening_api_key_value,
            "AIC_LEARNING_API_KEY": self.learning_api_key_value,
            "AIC_JEV_API_KEY": self.jev_api_key_value,
        }
        if name not in credentials:
            raise ValueError(f"Unsupported credential environment variable: {name}")
        return credentials[name]

    def object_storage(self) -> ObjectStorageSettings:
        return ObjectStorageSettings(
            backend=self.object_storage_backend,
            endpoint_url=self.s3_endpoint_url,
            bucket=self.s3_bucket,
            access_key=(self.s3_access_key.get_secret_value() if self.s3_access_key else None),
            secret_key=(self.s3_secret_key.get_secret_value() if self.s3_secret_key else None),
            region=self.s3_region,
        )

    def backup_storage(self) -> ObjectStorageSettings | None:
        if not self.backup_offsite_enabled:
            return None
        assert self.backup_s3_endpoint_url is not None
        assert self.backup_s3_bucket is not None
        assert self.backup_s3_access_key is not None
        assert self.backup_s3_secret_key is not None
        return ObjectStorageSettings(
            backend="s3",
            endpoint_url=self.backup_s3_endpoint_url,
            bucket=self.backup_s3_bucket,
            access_key=self.backup_s3_access_key.get_secret_value(),
            secret_key=self.backup_s3_secret_key.get_secret_value(),
            region=self.backup_s3_region,
        )

    def observability(self, service_name: str) -> ObservabilitySettings:
        return ObservabilitySettings(
            enabled=self.tracing_enabled,
            service_name=service_name,
            deployment_environment=self.environment,
            otlp_traces_endpoint=self.otlp_traces_endpoint,
            trace_sample_ratio=self.trace_sample_ratio,
            metrics_enabled=self.metrics_enabled,
            metrics_port=self.metrics_port,
            command_metrics_interval_seconds=self.command_metrics_interval_seconds,
            log_format=self.log_format,
            ai_telemetry_enabled=self.ai_telemetry_enabled,
            langfuse_otlp_endpoint=self.langfuse_otlp_endpoint,
            langfuse_public_key=self.langfuse_public_key,
            langfuse_secret_key=(
                self.langfuse_secret_key.get_secret_value() if self.langfuse_secret_key else None
            ),
        )


__all__ = ["ApplicationSettings"]
