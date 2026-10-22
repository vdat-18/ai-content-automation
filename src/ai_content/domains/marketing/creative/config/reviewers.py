"""Versioned configuration for multimodal Static Creative review."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .loader import ConfigError


class SemanticReviewPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    text: str = Field(min_length=1)


class SemanticCriterionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion_id: str = Field(min_length=1)
    section: Literal["hard_gate", "scored"]
    check: str = Field(min_length=1)
    weight: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_weight(self) -> Self:
        if self.section == "scored" and self.weight is None:
            raise ValueError("Scored review criteria require a weight")
        if self.section == "hard_gate" and self.weight is not None:
            raise ValueError("Hard-gate review criteria cannot have a weight")
        return self


class _SemanticReviewerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: str = Field(min_length=1)
    backend: Literal["baml"]
    mode: Literal["shadow", "gate"] = "shadow"
    model: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    runtime_version: str = Field(min_length=1)
    base_url: str
    api_key_env: str = Field(min_length=1)
    request_timeout_seconds: float = Field(default=120, gt=0)
    max_criteria_per_request: int = Field(default=3, ge=1, le=10)
    max_image_bytes: int = Field(default=10_000_000, gt=0)
    max_total_image_bytes: int = Field(default=25_000_000, gt=0)
    max_product_images: int = Field(default=5, ge=1, le=10)
    max_reference_images: int = Field(default=3, ge=0, le=10)

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
        if not self.api_key_env.isidentifier():
            raise ValueError("api_key_env must be an environment variable name")
        if self.max_total_image_bytes < self.max_image_bytes:
            raise ValueError("max_total_image_bytes cannot be smaller than max_image_bytes")
        return self


class SemanticReviewerConfig(_SemanticReviewerSettings):
    prompt: SemanticReviewPrompt
    rubric_ref: str = Field(min_length=1)
    criteria: tuple[SemanticCriterionSpec, ...] = Field(min_length=1)

    @property
    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _SemanticReviewerConfigFile(_SemanticReviewerSettings):
    prompt: Path
    rubric: Path
    criterion_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_criteria(self) -> Self:
        if len(set(self.criterion_ids)) != len(self.criterion_ids):
            raise ValueError("criterion_ids must be unique")
        return self


def load_semantic_reviewer_config(path: Path) -> SemanticReviewerConfig:
    """Load reviewer settings and the selected criterion text from one rubric."""
    try:
        settings = _SemanticReviewerConfigFile.model_validate_json(path.read_text(encoding="utf-8"))
        root = path.resolve().parent
        prompt = SemanticReviewPrompt.model_validate_json(
            (root / settings.prompt).read_text(encoding="utf-8")
        )
        rubric = yaml.safe_load((root / settings.rubric).read_text(encoding="utf-8"))
        if not isinstance(rubric, dict):
            raise ValueError("rubric must be a mapping")
        available: dict[str, SemanticCriterionSpec] = {}
        for section_key, section in (("hard_gates", "hard_gate"), ("scored_criteria", "scored")):
            rows = rubric.get(section_key)
            if not isinstance(rows, list):
                raise ValueError(f"rubric {section_key} must be a list")
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError(f"rubric {section_key} entries must be mappings")
                criterion_id = str(row["id"])
                available[criterion_id] = SemanticCriterionSpec(
                    criterion_id=criterion_id,
                    section=section,
                    check=str(row["check"]),
                    weight=(Decimal(str(row["weight"])) if section == "scored" else None),
                )
        missing = [item for item in settings.criterion_ids if item not in available]
        if missing:
            raise ValueError(f"unknown reviewer criterion_ids: {', '.join(missing)}")
        rubric_ref = f"{rubric['id']}@{rubric['version']}"
        return SemanticReviewerConfig(
            **settings.model_dump(exclude={"prompt", "rubric", "criterion_ids"}),
            prompt=prompt,
            rubric_ref=rubric_ref,
            criteria=tuple(available[item] for item in settings.criterion_ids),
        )
    except (OSError, ValueError, KeyError, ValidationError, yaml.YAMLError) as exc:
        raise ConfigError(f"Invalid semantic reviewer config {path}: {exc}") from exc


__all__ = [
    "SemanticCriterionSpec",
    "SemanticReviewerConfig",
    "SemanticReviewPrompt",
    "load_semantic_reviewer_config",
]
