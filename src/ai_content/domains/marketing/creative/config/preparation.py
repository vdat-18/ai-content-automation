"""Runtime configuration for bounded M1 strategy and brief model steps."""

import hashlib
import json
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PreparationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: str = Field(min_length=1)
    backend: Literal["baml"]
    model: str = Field(min_length=1)
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key: str | None = None
    max_ideas: int = Field(default=3, ge=1, le=3)
    step_timeout_seconds: float = Field(default=60, gt=0)
    run_timeout_seconds: float = Field(default=150, gt=0)
    max_attempts: int = Field(default=1, ge=1, le=3)
    retry_delay_seconds: float = Field(default=0, ge=0, le=10)
    probe_on_startup: bool = False
    probe_timeout_seconds: float = Field(default=10, gt=0, le=30)
    max_context_bytes: int | None = Field(default=None, gt=0)
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high"] | None = "high"
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int = Field(default=12000, gt=0, le=65536)

    @property
    def config_hash(self) -> str:
        data = self.model_dump(mode="json")
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def from_settings(cls, settings: object) -> "PreparationConfig":
        return cls(
            name="creative-preparation",
            backend="baml",
            model=getattr(settings, "prep_model", "xai/grok-4-fast-reasoning"),
            base_url=getattr(settings, "prep_base_url", "http://127.0.0.1:1234/v1"),
            api_key=getattr(settings, "prep_api_key_value", None),
            reasoning_effort=getattr(settings, "prep_reasoning_effort", "medium"),
            max_output_tokens=getattr(settings, "prep_max_tokens", 12000),
            max_attempts=getattr(settings, "prep_max_attempts", 3),
            step_timeout_seconds=getattr(settings, "prep_timeout", 90.0),
            run_timeout_seconds=getattr(settings, "prep_timeout", 90.0) * 3,
        )

    @model_validator(mode="after")
    def validate_endpoint(self) -> Self:
        url = urlsplit(self.base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("base_url must be an HTTP endpoint without credentials or query")
        return self


__all__ = ["PreparationConfig"]
