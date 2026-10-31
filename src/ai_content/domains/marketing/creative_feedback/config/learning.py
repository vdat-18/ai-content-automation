"""Versioned configuration for Performance Learning shadow analysis."""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LearningPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    text: str = Field(min_length=1)


class PerformanceLearningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    base_url: str
    api_key: str | None = None
    api_key_env: str | None = None
    diagnosis_prompt: LearningPrompt
    synthesis_prompt: LearningPrompt
    rubric_version: str = Field(min_length=1)
    timeout_seconds: float = Field(default=60, gt=0)

    @classmethod
    def from_settings(
        cls, settings: object, config_dir: Path | None = None
    ) -> "PerformanceLearningConfig":
        root = config_dir or getattr(settings, "config_dir", Path("config"))
        prompt_dir = root / "creative_feedback/prompts"
        return cls(
            model=getattr(settings, "learning_model", "xai/grok-4-fast-reasoning"),
            base_url=getattr(settings, "learning_base_url", "http://127.0.0.1:1234/v1"),
            api_key=getattr(settings, "learning_api_key_value", None),
            diagnosis_prompt=LearningPrompt.model_validate_json(
                (prompt_dir / "diagnose_ads_outcome.v1.json").read_text(encoding="utf-8")
            ),
            synthesis_prompt=LearningPrompt.model_validate_json(
                (prompt_dir / "synthesize_creative_lesson.v1.json").read_text(encoding="utf-8")
            ),
            rubric_version="performance-learning@1-draft",
            timeout_seconds=getattr(settings, "learning_timeout", 60.0),
        )

    @model_validator(mode="after")
    def validate_endpoint(self) -> "PerformanceLearningConfig":
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


class _LearningConfigFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    base_url: str
    api_key_env: str | None = None
    diagnosis_prompt: Path
    synthesis_prompt: Path
    rubric_version: str
    timeout_seconds: float = 60


def load_performance_learning_config(path: Path) -> PerformanceLearningConfig:
    data = _LearningConfigFile.model_validate_json(path.read_text(encoding="utf-8"))
    root = path.resolve().parent
    return PerformanceLearningConfig(
        **data.model_dump(exclude={"diagnosis_prompt", "synthesis_prompt"}),
        diagnosis_prompt=LearningPrompt.model_validate_json(
            (root / data.diagnosis_prompt).read_text(encoding="utf-8")
        ),
        synthesis_prompt=LearningPrompt.model_validate_json(
            (root / data.synthesis_prompt).read_text(encoding="utf-8")
        ),
    )


__all__ = [
    "LearningPrompt",
    "PerformanceLearningConfig",
    "load_performance_learning_config",
]
