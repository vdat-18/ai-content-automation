"""Typed process settings loaded directly from environment variables."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_content.platform.artifacts import ObjectStorageSettings
from ai_content.platform.observability import ObservabilitySettings


class ApplicationSettings(BaseSettings):
    """Single environment boundary for the API and maintenance entrypoints."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    data_root: Path = Field(Path(".creative-pilot"), validation_alias="AIC_AI_DATA_ROOT")
    config_dir: Path = Field(Path("config"), validation_alias="AIC_AI_CONFIG_DIR")

    # --- Reference keyword drafting and image review (BAML, OpenAI-compatible endpoint) ---
    screening_base_url: str = Field(
        "http://127.0.0.1:1234/v1", validation_alias="AIC_SCREENING_BASE_URL"
    )
    screening_api_key: SecretStr | None = Field(None, validation_alias="AIC_SCREENING_API_KEY")
    # One model per job, no fallback: writer drafts text, review checks images and clips.
    writer_model: str = Field("", validation_alias="AIC_WRITER_MODEL")
    review_model: str = Field("", validation_alias="AIC_REVIEW_MODEL")

    # --- Image generation; base URL and key fall back to the screening endpoint when empty ---
    image_base_url: str = Field("", validation_alias="AIC_IMAGE_BASE_URL")
    image_api_key: SecretStr | None = Field(None, validation_alias="AIC_IMAGE_API_KEY")
    image_model: str = Field("", validation_alias="AIC_IMAGE_MODEL")
    image_api: Literal["chat", "edits"] = Field("chat", validation_alias="AIC_IMAGE_API")
    video_base_url: str = Field("", validation_alias="AIC_VIDEO_BASE_URL")
    video_api_key: SecretStr | None = Field(None, validation_alias="AIC_VIDEO_API_KEY")
    video_model: str = Field("", validation_alias="AIC_VIDEO_MODEL")
    video_frame_fields: str = Field(
        "image", validation_alias="AIC_VIDEO_FRAME_FIELDS"
    )
    tts_base_url: str = Field("", validation_alias="AIC_TTS_BASE_URL")
    tts_api_key: SecretStr | None = Field(None, validation_alias="AIC_TTS_API_KEY")
    tts_model: str = Field("", validation_alias="AIC_TTS_MODEL")
    tts_voice: str = Field("", validation_alias="AIC_TTS_VOICE")

    # Text embedding of reference descriptions, used to find references for each shot. The URL
    # and key fall back to the image settings; an empty model disables reference matching.
    text_embedding_base_url: str = Field("", validation_alias="AIC_TEXT_EMBEDDING_BASE_URL")
    text_embedding_api_key: SecretStr | None = Field(
        None, validation_alias="AIC_TEXT_EMBEDDING_API_KEY"
    )
    text_embedding_model: str = Field("", validation_alias="AIC_TEXT_EMBEDDING_MODEL")

    # Local ONNX image embedding used to drop duplicate references; empty disables it.
    embedding_model: str = Field("", validation_alias="AIC_EMBEDDING_MODEL")

    database_url: SecretStr = Field(validation_alias="AIC_AI_DATABASE_URL")
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
    log_format: Literal["text", "json"] = Field("text", validation_alias="AIC_AI_LOG_FORMAT")
    ai_telemetry_enabled: bool = Field(False, validation_alias="AIC_AI_AI_TELEMETRY_ENABLED")
    langfuse_otlp_endpoint: str | None = Field(
        None, validation_alias="AIC_AI_LANGFUSE_OTLP_ENDPOINT"
    )
    langfuse_public_key: str | None = Field(None, validation_alias="AIC_AI_LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: SecretStr | None = Field(
        None, validation_alias="AIC_AI_LANGFUSE_SECRET_KEY"
    )

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
    def screening_api_key_value(self) -> str | None:
        return self.screening_api_key.get_secret_value() if self.screening_api_key else None

    @property
    def image_api_key_value(self) -> str | None:
        key = self.image_api_key or self.screening_api_key
        return key.get_secret_value() if key else None

    @property
    def text_embedding_api_key_value(self) -> str | None:
        key = self.text_embedding_api_key or self.image_api_key or self.screening_api_key
        return key.get_secret_value() if key else None

    @property
    def video_api_key_value(self) -> str | None:
        key = self.video_api_key or self.image_api_key or self.screening_api_key
        return key.get_secret_value() if key else None

    @property
    def tts_api_key_value(self) -> str | None:
        key = self.tts_api_key or self.video_api_key or self.image_api_key or self.screening_api_key
        return key.get_secret_value() if key else None

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
            log_format=self.log_format,
            ai_telemetry_enabled=self.ai_telemetry_enabled,
            langfuse_otlp_endpoint=self.langfuse_otlp_endpoint,
            langfuse_public_key=self.langfuse_public_key,
            langfuse_secret_key=(
                self.langfuse_secret_key.get_secret_value() if self.langfuse_secret_key else None
            ),
        )


__all__ = ["ApplicationSettings"]
