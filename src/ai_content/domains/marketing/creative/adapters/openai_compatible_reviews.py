"""OpenAI-compatible multimodal reviewer for Static Creative shadow QA."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from decimal import Decimal
from typing import Protocol, Self

from baml_py import Collector, Image
from baml_py.baml_py import BamlError
from baml_py.logging import set_log_level
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ai_content.platform.ai_usage import (
    AIUsageCompletion,
    AIUsageFailure,
    AIUsageStart,
    AIUsageTracker,
)
from ai_content.platform.observability import observe_ai_call

from ..config.reviewers import SemanticCriterionSpec, SemanticReviewerConfig
from ..domain.entities import QASession
from ..domain.reviews import (
    CriterionReview,
    CriterionStatus,
    IssueSeverity,
    RepairAction,
    ReviewEvidence,
    ReviewOutcome,
    SemanticIssue,
    SemanticReviewResult,
)
from ..ports.contracts import StaticCreativeInput
from ..ports.images import ImageGenerationError
from ..ports.interfaces import SemanticReviewError
from .baml_client import types as baml_types
from .baml_client.async_client import b
from .baml_client.inlinedbaml import get_baml_files
from .image_files import inspect_image, read_local_image


class _BamlSemanticReviewClient(Protocol):
    async def ReviewStaticCreative(
        self,
        instructions: str,
        input_json: str,
        sources: list[baml_types.LabeledReviewImage],
        baml_options: dict[str, object],
    ) -> baml_types.StaticCreativeReview: ...


class _EvidenceOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    region: tuple[Decimal, Decimal, Decimal, Decimal] | None = None

    @model_validator(mode="after")
    def validate_region(self) -> Self:
        if self.region is not None and any(value < 0 or value > 1 for value in self.region):
            raise ValueError("evidence region values must be between 0 and 1")
        return self


class _IssueOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    severity: IssueSeverity
    repair_action: RepairAction
    description: str = Field(min_length=1)


class _CriterionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(min_length=1)
    status: CriterionStatus
    reason: str = Field(min_length=1)
    score: Decimal | None = Field(default=None, ge=0, le=4)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    evidence: tuple[_EvidenceOutput, ...] = ()
    issue: _IssueOutput | None = None

    @model_validator(mode="after")
    def validate_status_details(self) -> Self:
        if self.status == CriterionStatus.FAIL and self.issue is None:
            raise ValueError("failed criterion requires an issue")
        if self.status != CriterionStatus.FAIL and self.issue is not None:
            raise ValueError("only failed criterion may include an issue")
        if self.status == CriterionStatus.UNKNOWN and self.score is not None:
            raise ValueError("unknown criterion cannot have a score")
        return self


class _ReviewOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: tuple[_CriterionOutput, ...] = Field(min_length=1)
    summary: str = Field(min_length=1)
    warnings: tuple[str, ...] = ()


class BamlSemanticReviewer:
    """Review local candidate/reference images without fetching arbitrary URLs."""

    def __init__(
        self,
        config: SemanticReviewerConfig,
        *,
        api_key: str | None,
        client: _BamlSemanticReviewClient | None = None,
        usage_tracker: AIUsageTracker | None = None,
    ) -> None:
        if config.api_key_env and not api_key:
            raise SemanticReviewError(
                "Configured reviewer credential environment variable is missing"
            )
        self._config = config
        self._usage_tracker = usage_tracker
        set_log_level("OFF")
        self._client = client or b.with_options(
            env={
                "LOCAL_LLM_BASE_URL": config.base_url,
                "LOCAL_LLM_MODEL": config.model,
                "LOCAL_LLM_API_KEY": api_key or "local-no-auth",
            }
        )
        self._baml_source = get_baml_files()["creative_preparation.baml"]
        self._template_hash = hashlib.sha256(self._baml_source.encode()).hexdigest()
        self._prompt_version = f"{config.prompt.version}+baml:{self._template_hash[:12]}"

    async def review(self, session: QASession) -> SemanticReviewResult:
        if not isinstance(session.input_contract, StaticCreativeInput):
            raise SemanticReviewError("Semantic reviewer requires StaticCreativeInput")
        if session.asset.artifact_path is None:
            raise SemanticReviewError("Generated image has no local artifact")
        if session.rubric_version != self._config.rubric_ref:
            raise SemanticReviewError("Review session rubric does not match reviewer config")

        input_data = session.input_contract
        batches = _batched(self._config.criteria, self._config.max_criteria_per_request)
        with observe_ai_call(
            "semantic_review",
            "baml",
            self._config.model,
            model_revision=self._config.model_revision,
            runtime_version=self._config.runtime_version,
            prompt_version=self._prompt_version,
            prompt_hash=self._template_hash,
            config_hash=self._config.config_hash,
            rubric_ref=self._config.rubric_ref,
            policy_ref=session.policy_version,
            job_id=session.asset.version_id.job_id.value,
            version_id=session.asset.version_id.value,
            criterion_count=len(self._config.criteria),
            batch_count=len(batches),
            review_mode=self._config.mode,
        ) as observation:
            try:
                sources = self._load_sources(session.asset.artifact_path, input_data)
                allowed_sources = {label for label, _, _ in sources}
                baml_sources = [
                    baml_types.LabeledReviewImage(
                        label=label,
                        content=Image.from_base64(mime, base64.b64encode(content).decode("ascii")),
                    )
                    for label, content, mime in sources
                ]
                outputs = []
                for index, criteria in enumerate(batches, start=1):
                    context = self._review_context(input_data, session, sources, criteria)
                    input_json = json.dumps(context, ensure_ascii=False, sort_keys=True)
                    prompt_hash = self._prompt_hash(input_json)
                    collector = Collector(name=f"semantic-review-batch-{index}")
                    event_id = None
                    if self._usage_tracker is not None:
                        event_id = await self._usage_tracker.start(
                            AIUsageStart(
                                workstream="creative",
                                operation="semantic_review.batch",
                                backend="baml",
                                model=self._config.model,
                                model_revision=self._config.model_revision,
                                job_id=session.asset.version_id.job_id.value,
                                version_id=session.asset.version_id.value,
                                brand_id=input_data.brand,
                            )
                        )
                    with observe_ai_call(
                        "semantic_review.batch",
                        "baml",
                        self._config.model,
                        prompt_version=self._prompt_version,
                        prompt_hash=prompt_hash,
                        batch_index=index,
                        batch_count=len(batches),
                        criterion_count=len(criteria),
                        version_id=session.asset.version_id.value,
                    ) as batch_observation:
                        try:
                            async with asyncio.timeout(self._config.request_timeout_seconds):
                                raw_output = await self._client.ReviewStaticCreative(
                                    instructions=self._config.prompt.text,
                                    input_json=input_json,
                                    sources=baml_sources,
                                    baml_options={"collector": collector},
                                )
                            output = _ReviewOutput.model_validate(
                                _normalized_review_output(raw_output)
                            )
                            self._validate_batch(output, criteria)
                            outputs.append(output)
                        except (TimeoutError, BamlError, ValidationError, ValueError) as exc:
                            error_code = _review_error_type(exc)
                            if event_id is not None:
                                await self._usage_tracker.fail(
                                    event_id,
                                    AIUsageFailure(
                                        error_code=error_code,
                                        request_count=_request_count(collector),
                                        input_tokens=collector.usage.input_tokens,
                                        output_tokens=collector.usage.output_tokens,
                                    ),
                                )
                            batch_observation.fail(error_code)
                            raise SemanticReviewError(
                                f"Semantic review model failed in batch {index}/{len(batches)}"
                            ) from exc
                        if event_id is not None:
                            await self._usage_tracker.succeed(
                                event_id,
                                AIUsageCompletion(
                                    request_count=_request_count(collector),
                                    input_tokens=collector.usage.input_tokens,
                                    output_tokens=collector.usage.output_tokens,
                                    output_count=1,
                                ),
                            )
                        batch_observation.usage(
                            collector.usage.input_tokens,
                            collector.usage.output_tokens,
                        )
                        batch_observation.succeed()
                output = _merge_outputs(outputs)
                result = self._to_domain(output, allowed_sources)
            except SemanticReviewError:
                observation.fail("semantic_review_error")
                raise
            except (ValidationError, ValueError) as exc:
                reason = type(exc).__name__
                observation.fail(_review_error_type(exc))
                raise SemanticReviewError(f"Semantic review output {reason}") from exc
            observation.semantic_review(result.outcome.value, self._config.mode)
            observation.succeed(
                semantic_score=float(result.score),
                issue_count=len(result.issues),
            )
            return result

    @staticmethod
    def _validate_batch(
        output: _ReviewOutput,
        criteria: tuple[SemanticCriterionSpec, ...],
    ) -> None:
        expected_ids = {item.criterion_id for item in criteria}
        actual_ids = [item.criterion_id for item in output.criteria]
        if len(set(actual_ids)) != len(actual_ids) or set(actual_ids) != expected_ids:
            raise ValueError("review batch must contain every requested criterion exactly once")

    def _prompt_hash(self, input_json: str) -> str:
        payload = json.dumps(
            {
                "baml": self._baml_source,
                "function": "ReviewStaticCreative",
                "instructions": self._config.prompt.text,
                "input": input_json,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def _load_sources(
        self,
        candidate_path: str,
        input_data: StaticCreativeInput,
    ) -> tuple[tuple[str, bytes, str], ...]:
        if len(input_data.product_assets) > self._config.max_product_images:
            raise SemanticReviewError("Product image count exceeds reviewer limit")
        if len(input_data.reference_assets) > self._config.max_reference_images:
            raise SemanticReviewError("Reference image count exceeds reviewer limit")
        paths = [("candidate", candidate_path)]
        paths.extend(
            (f"product:{index}", asset.url) for index, asset in enumerate(input_data.product_assets)
        )
        paths.extend(
            (f"reference:{index}", asset.url)
            for index, asset in enumerate(input_data.reference_assets)
        )
        sources = []
        total_bytes = 0
        try:
            for label, path in paths:
                content = read_local_image(path, self._config.max_image_bytes)
                _, _, file_format = inspect_image(content)
                total_bytes += len(content)
                if total_bytes > self._config.max_total_image_bytes:
                    raise SemanticReviewError("Review images exceed total byte limit")
                mime = "image/jpeg" if file_format == "jpeg" else "image/png"
                sources.append((label, content, mime))
        except ImageGenerationError as exc:
            raise SemanticReviewError("Semantic reviewer cannot read a local image") from exc
        return tuple(sources)

    def _review_context(
        self,
        input_data: StaticCreativeInput,
        session: QASession,
        sources: tuple[tuple[str, bytes, str], ...],
        criteria: tuple[SemanticCriterionSpec, ...],
    ) -> dict[str, object]:
        return {
            "brief": {
                "brand": input_data.brand,
                "sku": input_data.sku,
                "objective": input_data.objective,
                "heading": input_data.heading,
                "subtext": input_data.subtext,
                "visual_direction": input_data.visual_direction,
                "banned_claims": list(input_data.banned_claims),
                "output_spec": {
                    "width": input_data.output_spec.width,
                    "height": input_data.output_spec.height,
                    "file_format": input_data.output_spec.file_format,
                },
            },
            "rubric_ref": session.rubric_version,
            "policy_ref": session.policy_version,
            "criteria": [item.model_dump(mode="json") for item in criteria],
            "image_order": [label for label, _, _ in sources],
        }

    def _to_domain(
        self,
        output: _ReviewOutput,
        allowed_sources: set[str],
    ) -> SemanticReviewResult:
        expected_ids = tuple(item.criterion_id for item in self._config.criteria)
        actual_ids = tuple(item.criterion_id for item in output.criteria)
        if len(set(actual_ids)) != len(actual_ids) or set(actual_ids) != set(expected_ids):
            raise ValueError("review response must contain every configured criterion exactly once")
        ordered = {item.criterion_id: item for item in output.criteria}
        evidence: list[ReviewEvidence] = []
        criteria: list[CriterionReview] = []
        issues: list[SemanticIssue] = []
        for criterion_id in expected_ids:
            item = ordered[criterion_id]
            evidence_refs = []
            for index, observation in enumerate(item.evidence, start=1):
                if observation.source_ref not in allowed_sources:
                    raise ValueError("review response references an unknown image source")
                evidence_id = f"{criterion_id}-evidence-{index}"
                evidence_refs.append(evidence_id)
                evidence.append(
                    ReviewEvidence(
                        evidence_id=evidence_id,
                        description=observation.description,
                        source_ref=observation.source_ref,
                        region=observation.region,
                    )
                )
            criteria.append(
                CriterionReview(
                    criterion_id=criterion_id,
                    status=item.status,
                    reason=item.reason,
                    score=item.score,
                    confidence=item.confidence,
                    evidence_refs=tuple(evidence_refs),
                )
            )
            if item.issue is not None:
                issues.append(
                    SemanticIssue(
                        code=item.issue.code,
                        criterion_id=criterion_id,
                        severity=item.issue.severity,
                        repair_action=item.issue.repair_action,
                        description=item.issue.description,
                        evidence_refs=tuple(evidence_refs),
                    )
                )
        outcome = _derive_outcome(tuple(criteria), tuple(issues))
        score = _weighted_score(self._config, tuple(criteria))
        reviewer_version = (
            f"{self._config.model}@{self._config.model_revision}:"
            f"{self._prompt_version}:{self._config.config_hash[:12]}"
        )
        return SemanticReviewResult(
            outcome=outcome,
            score=score,
            criteria=tuple(criteria),
            reviewer_version=reviewer_version,
            issues=tuple(issues),
            evidence=tuple(evidence),
            warnings=tuple(dict.fromkeys((*output.warnings, "semantic_review_not_calibrated"))),
            summary=output.summary,
            metadata=(
                ("model", self._config.model),
                ("runtime_version", self._config.runtime_version),
                ("prompt_version", self._prompt_version),
                ("rubric_ref", self._config.rubric_ref),
                ("mode", self._config.mode),
            ),
        )


def _batched(
    criteria: tuple[SemanticCriterionSpec, ...],
    size: int,
) -> tuple[tuple[SemanticCriterionSpec, ...], ...]:
    return tuple(criteria[index : index + size] for index in range(0, len(criteria), size))


def _normalized_review_output(
    output: baml_types.StaticCreativeReview,
) -> dict[str, object]:
    payload = output.model_dump(mode="json")
    for criterion in payload["criteria"]:
        criterion["status"] = criterion["status"].lower()
        issue = criterion["issue"]
        if issue is not None:
            issue["severity"] = issue["severity"].lower()
            issue["repair_action"] = issue["repair_action"].lower()
    return payload


def _merge_outputs(outputs: list[_ReviewOutput]) -> _ReviewOutput:
    return _ReviewOutput(
        criteria=tuple(item for output in outputs for item in output.criteria),
        summary=" ".join(output.summary for output in outputs),
        warnings=tuple(dict.fromkeys(warning for output in outputs for warning in output.warnings)),
    )


def _derive_outcome(
    criteria: tuple[CriterionReview, ...],
    issues: tuple[SemanticIssue, ...],
) -> ReviewOutcome:
    if any(item.status == CriterionStatus.UNKNOWN for item in criteria):
        return ReviewOutcome.UNKNOWN
    if any(item.repair_action == RepairAction.REJECT_POLICY for item in issues):
        return ReviewOutcome.REJECT
    if any(item.status == CriterionStatus.FAIL for item in criteria):
        return ReviewOutcome.REVISE
    return ReviewOutcome.PASS


def _weighted_score(
    config: SemanticReviewerConfig,
    criteria: tuple[CriterionReview, ...],
) -> Decimal:
    reviews = {item.criterion_id: item for item in criteria}
    weighted = [item for item in config.criteria if item.weight is not None]
    if not weighted or any(reviews[item.criterion_id].score is None for item in weighted):
        return Decimal("0")
    total_weight = sum((item.weight or Decimal()) for item in weighted)
    return (
        sum(
            (reviews[item.criterion_id].score or Decimal())
            / Decimal(4)
            * (item.weight or Decimal())
            for item in weighted
        )
        / total_weight
        * Decimal(100)
    )


def _review_error_type(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "provider_timeout"
    if isinstance(exc, ValidationError):
        return "invalid_provider_schema"
    if isinstance(exc, ValueError):
        return "invalid_provider_output"
    if isinstance(exc, BamlError):
        return "provider_error"
    return type(exc).__name__


def _request_count(collector: Collector) -> int:
    log = collector.last
    return max(1, len(log.calls)) if log is not None else 1


__all__ = ["BamlSemanticReviewer", "SemanticReviewError"]
