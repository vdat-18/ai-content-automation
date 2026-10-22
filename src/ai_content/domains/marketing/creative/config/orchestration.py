"""Versioned configuration for selected-SKU Creative orchestration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OrchestrationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: str = Field(min_length=1)
    backend: Literal["fake", "baml"]
    model: str = Field(min_length=1)
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key_env: str | None = None
    prompt_version: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
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
        if self.api_key_env is not None and not self.api_key_env.isidentifier():
            raise ValueError("api_key_env must be an environment variable name")
        return self

    @property
    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


def load_orchestration_config(path: Path) -> OrchestrationConfig:
    return OrchestrationConfig.model_validate_json(path.read_text(encoding="utf-8"))


__all__ = ["OrchestrationConfig", "load_orchestration_config"]
