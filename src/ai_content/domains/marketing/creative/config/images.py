"""Typed files used by the image pilot; paths are relative to their config file."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..domain.reviews import CriterionStatus
from ..ports.contracts import RevisionRequest, StaticCreativeInput


class ImageBackendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    backend: Literal["synthetic", "invokeai", "openai_compatible", "comfyui"]
    model: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    runtime_version: str = Field(min_length=1)
    base_url: str = "http://127.0.0.1:9090"
    token_env: str | None = None
    api_key_env: str | None = None
    graph_path: Path | None = None
    output_node: str | None = None
    one_image_workflow_path: Path | None = None
    two_image_workflow_path: Path | None = None
    background_workflow_path: Path | None = None
    prompt_template: str = (
        "<goal>\nCreate one product-conditioned advertising visual.\n</goal>\n"
        "<visual_direction>\n$visual_direction\n</visual_direction>\n"
        "<constraints>\nPreserve the supplied product image and product identity unchanged. "
        "Reserve clean negative space for later deterministic copy and logo placement. "
        "Generate a clean visual only. Do not render words, letters, typography, prices, "
        "watermarks, logos, labels, signage, symbols, or promotional claims. "
        "Do not imitate or invent brand marks.\n</constraints>"
    )
    background_prompt_template: str = (
        "<goal>\nCreate one photorealistic advertising background.\n</goal>\n"
        "<visual_direction>\n$visual_direction\n</visual_direction>\n"
        "<constraints>\nGenerate only the scene, environment, lighting, and surface. "
        "Keep the planned product placement area clear. Do not render or imitate the product. "
        "Do not render words, letters, typography, prices, watermarks, logos, labels, "
        "signage, symbols, or promotional claims.\n</constraints>"
    )
    request_timeout_seconds: float = Field(default=30, gt=0)
    generation_timeout_seconds: float = Field(default=600, gt=0)
    poll_interval_seconds: float = Field(default=1, gt=0)
    max_image_bytes: int = Field(default=30_000_000, gt=0)

    @model_validator(mode="after")
    def validate_service(self) -> Self:
        allowed = {"visual_direction", "heading", "subtext", "brand", "sku", "constraints"}
        for raw_template in (self.prompt_template, self.background_prompt_template):
            template = Template(raw_template)
            if not template.is_valid() or not set(template.get_identifiers()).issubset(allowed):
                raise ValueError("Invalid prompt template placeholders")
        if self.backend in {"invokeai", "openai_compatible", "comfyui"}:
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
        if self.backend == "invokeai":
            if self.graph_path is None or not self.output_node:
                raise ValueError("InvokeAI needs graph_path and output_node")
            url = urlsplit(self.base_url)
            if url.path not in {"", "/"}:
                raise ValueError("base_url must be an HTTP origin without credentials")
        if self.backend == "comfyui":
            if self.one_image_workflow_path is None or self.two_image_workflow_path is None:
                raise ValueError("ComfyUI needs one- and two-image API workflow paths")
            if urlsplit(self.base_url).path not in {"", "/"}:
                raise ValueError("base_url must be an HTTP origin without credentials")
            if self.api_key_env is not None or self.token_env is not None:
                raise ValueError("ComfyUI backend does not support API credentials")
        return self


def render_image_prompt(
    config: ImageBackendConfig,
    input_data: StaticCreativeInput,
    revision: RevisionRequest | None = None,
    *,
    generation_target: Literal["full_visual", "background"] = "full_visual",
) -> str:
    visual_direction = (
        input_data.composition.visual_prompt
        if input_data.composition is not None
        else input_data.visual_direction
    )
    selected_template = (
        config.background_prompt_template
        if generation_target == "background"
        else config.prompt_template
    )
    prompt = Template(selected_template).substitute(
        visual_direction=visual_direction,
        heading="",
        subtext="",
        brand="",
        sku="",
        constraints="Do not render promotional claims or copy.",
    )
    if revision is None:
        return prompt
    instructions = "; ".join(revision.instructions or revision.issues)
    immutable = "; ".join(revision.immutable_constraints)
    source_instruction = (
        "Regenerate the background without using a previous generated image.\n"
        if generation_target == "background"
        else "Use the image named revision_source as the previous visual.\n"
    )
    return (
        f"{prompt}\n"
        f"<revision>\n{source_instruction}"
        f"Required corrections: {instructions}\n"
        f"Immutable elements: {immutable}\n"
        "Change only what is required. Preserve everything else. Do not render text or logos.\n"
        "</revision>"
    )


class HumanCriterionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=1)
    status: CriterionStatus
    reason: str = Field(min_length=1)
    score: int | None = Field(default=None, ge=0, le=4)


class HistoricalHumanReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accept", "revise", "reject"]
    reason: str = Field(min_length=1)
    reviewer_alias: str = Field(min_length=1)
    rubric_version: str = Field(min_length=1)
    critical_product_error: bool = False
    criteria: list[HumanCriterionReview] = Field(default_factory=list)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def unique_criteria(self) -> Self:
        if len({item.criterion_id for item in self.criteria}) != len(self.criteria):
            raise ValueError("criterion_id values must be unique within a review")
        return self


class HistoricalCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    candidate_paths: list[Path] = Field(min_length=1)
    stage: Literal["first_draft", "revision", "final"]
    sequence: int = Field(ge=1)
    reviews: list[HistoricalHumanReview] = Field(default_factory=list)


class GoldenCaseMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usage_permission_confirmed: bool = False
    source_truth_resolved: bool = False
    historical_candidates: list[HistoricalCandidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_candidates(self) -> Self:
        candidate_ids = [item.candidate_id for item in self.historical_candidates]
        sequences = [item.sequence for item in self.historical_candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("candidate_id values must be unique within a golden case")
        if len(set(sequences)) != len(sequences):
            raise ValueError("candidate sequence values must be unique within a golden case")
        return self


class ImageCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    input: StaticCreativeInput
    checklist: list[str] = Field(min_length=1)
    golden: GoldenCaseMetadata | None = None


class ImageDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    cases: list[ImageCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self) -> Self:
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("case_id must be unique")
        return self


def load_image_config(path: Path) -> ImageBackendConfig:
    config = ImageBackendConfig.model_validate_json(path.read_text(encoding="utf-8"))
    if config.graph_path is not None:
        config.graph_path = (path.resolve().parent / config.graph_path).resolve()
    for field_name in (
        "one_image_workflow_path",
        "two_image_workflow_path",
        "background_workflow_path",
    ):
        workflow_path = getattr(config, field_name)
        if workflow_path is not None:
            setattr(config, field_name, (path.resolve().parent / workflow_path).resolve())
    return config


def load_image_dataset(path: Path) -> ImageDataset:
    dataset = ImageDataset.model_validate_json(path.read_text(encoding="utf-8"))
    # Resolve assets once so subsequent working-directory changes do not affect input.
    for case in dataset.cases:
        for key in ("product_assets", "reference_assets"):
            assets = []
            for asset in getattr(case.input, key):
                if "://" in asset.url:
                    raise ValueError("Dataset image assets must be local files")
                assets.append(
                    replace(asset, url=str((path.resolve().parent / asset.url).resolve()))
                )
            case.input = replace(case.input, **{key: tuple(assets)})
        if case.input.logo_asset is not None:
            logo = case.input.logo_asset
            if "://" in logo.url:
                raise ValueError("Dataset logo asset must be a local file")
            case.input = replace(
                case.input,
                logo_asset=replace(logo, url=str((path.resolve().parent / logo.url).resolve())),
            )
        if case.golden is not None:
            for candidate in case.golden.historical_candidates:
                candidate.candidate_paths = [
                    (path.resolve().parent / candidate_path).resolve()
                    for candidate_path in candidate.candidate_paths
                ]
    return dataset


__all__ = [
    "GoldenCaseMetadata",
    "HistoricalCandidate",
    "HistoricalHumanReview",
    "HumanCriterionReview",
    "ImageBackendConfig",
    "ImageCase",
    "ImageDataset",
    "load_image_config",
    "load_image_dataset",
    "render_image_prompt",
]
