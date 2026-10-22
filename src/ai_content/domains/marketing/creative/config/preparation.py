"""Versioned configuration for bounded M1 strategy and brief model steps."""

import hashlib
import json
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PreparationPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    text: str = Field(min_length=1)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


class _PreparationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: str = Field(min_length=1)
    backend: Literal["fake", "baml"]
    model: str = Field(min_length=1)
    fallback_model: str | None = Field(default=None, min_length=1)
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key_env: str | None = None
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
    selection_rule_version: Literal[
        "m1-first-eligible@1-draft", "m1-strategy-selection@1-draft"
    ] = "m1-strategy-selection@1-draft"

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


class PreparationConfig(_PreparationSettings):
    persona_prompt: PreparationPrompt | None = None
    idea_prompt: PreparationPrompt
    brief_prompt: PreparationPrompt
    composition_prompt: PreparationPrompt

    @property
    def config_hash(self) -> str:
        data = self.model_dump(mode="json")
        # Preserve fingerprints created before operational retry/probe controls existed.
        if self.max_attempts == 1:
            data.pop("max_attempts")
        if self.retry_delay_seconds == 0:
            data.pop("retry_delay_seconds")
        data.pop("probe_on_startup")
        data.pop("probe_timeout_seconds")
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _PreparationConfigFile(_PreparationSettings):
    persona_prompt: Path = Path("../prompts/creative/v1_resolve_persona.json")
    idea_prompt: Path
    brief_prompt: Path
    composition_prompt: Path


def load_preparation_config(path: Path) -> PreparationConfig:
    settings = _PreparationConfigFile.model_validate_json(path.read_text(encoding="utf-8"))
    root = path.resolve().parent
    return PreparationConfig(
        **settings.model_dump(
            exclude={
                "persona_prompt",
                "idea_prompt",
                "brief_prompt",
                "composition_prompt",
            }
        ),
        persona_prompt=(
            PreparationPrompt.model_validate_json(
                (root / settings.persona_prompt).read_text(encoding="utf-8")
            )
        ),
        idea_prompt=PreparationPrompt.model_validate_json(
            (root / settings.idea_prompt).read_text(encoding="utf-8")
        ),
        brief_prompt=PreparationPrompt.model_validate_json(
            (root / settings.brief_prompt).read_text(encoding="utf-8")
        ),
        composition_prompt=PreparationPrompt.model_validate_json(
            (root / settings.composition_prompt).read_text(encoding="utf-8")
        ),
    )
