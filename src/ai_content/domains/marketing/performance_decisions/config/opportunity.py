"""Versioned configuration for Creative Opportunity shadow analysis."""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OpportunityPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    text: str = Field(min_length=1)


class OpportunityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    base_url: str
    api_key_env: str | None = None
    prompt: OpportunityPrompt
    rubric_version: str = Field(min_length=1)
    timeout_seconds: float = Field(default=60, gt=0)

    @model_validator(mode="after")
    def validate_endpoint(self) -> "OpportunityConfig":
        endpoint = urlsplit(self.base_url)
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.hostname
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
        ):
            raise ValueError("base_url must be an HTTP endpoint without credentials or query")
        if self.api_key_env is not None and not self.api_key_env.isidentifier():
            raise ValueError("api_key_env must be an environment variable name")
        return self


class _OpportunityConfigFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    base_url: str
    api_key_env: str | None = None
    prompt: Path
    rubric_version: str
    timeout_seconds: float = 60


def load_opportunity_config(path: Path) -> OpportunityConfig:
    data = _OpportunityConfigFile.model_validate_json(path.read_text(encoding="utf-8"))
    return OpportunityConfig(
        **data.model_dump(exclude={"prompt"}),
        prompt=OpportunityPrompt.model_validate_json(
            (path.resolve().parent / data.prompt).read_text(encoding="utf-8")
        ),
    )


__all__ = ["OpportunityConfig", "OpportunityPrompt", "load_opportunity_config"]
