"""Configuration for selected-SKU Creative orchestration."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OrchestrationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: str = Field(min_length=1)
    backend: Literal["fake", "baml"]
    model: str = Field(min_length=1)
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key: str | None = None
    prompt_version: str = Field(min_length=1)
    timeout_seconds: float = Field(default=120, gt=0, le=900)
    max_attempts: int = Field(default=3, ge=1, le=5)
    retry_delay_seconds: float = Field(default=1, ge=0, le=60)
    max_context_bytes: int | None = Field(default=None, gt=0)
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high"] | None = "high"
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int = Field(default=32000, gt=0, le=65536)

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

    @property
    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    @classmethod
    def from_settings(cls, settings: object) -> OrchestrationConfig:
        return cls(
            profile_id="creative-orchestration@1",
            backend="baml",
            model=getattr(settings, "orch_model", "xai/grok-4-fast-reasoning"),
            base_url=getattr(settings, "orch_base_url", "http://127.0.0.1:1234/v1"),
            api_key=getattr(settings, "orch_api_key_value", None),
            prompt_version="creative-automation-orchestration@6",
            timeout_seconds=getattr(settings, "orch_timeout", 180.0),
            max_attempts=getattr(settings, "orch_max_attempts", 3),
            reasoning_effort=getattr(settings, "orch_reasoning_effort", "medium"),
            max_output_tokens=getattr(settings, "orch_max_tokens", 32000),
        )


__all__ = ["OrchestrationConfig"]
