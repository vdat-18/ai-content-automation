"""Runtime configuration for Creative Opportunity shadow analysis."""

from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OpportunityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    base_url: str
    api_key: str | None = None
    rubric_version: str = Field(min_length=1)
    timeout_seconds: float = Field(default=60, gt=0)

    @classmethod
    def from_settings(cls, settings: object) -> "OpportunityConfig":
        return cls(
            model=getattr(settings, "opportunity_model", "xai/grok-4-fast-reasoning"),
            base_url=getattr(settings, "opportunity_base_url", "http://127.0.0.1:1234/v1"),
            api_key=getattr(settings, "opportunity_api_key_value", None),
            rubric_version="performance-opportunity@2-draft",
            timeout_seconds=getattr(settings, "opportunity_timeout", 60.0),
        )

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
        return self


__all__ = ["OpportunityConfig"]
