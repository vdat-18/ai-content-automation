"""HTTP boundary for the isolated GPU video verification service."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ai_content.platform.runpod_serverless import (
    RunpodServerlessClient,
    RunpodServerlessError,
)

from ..config.orchestration import MediaLabVideoVerifierConfig
from ..domain.video_models import (
    VideoQualityIssueSeverity,
    VideoVerificationObservation,
    VideoVerificationReport,
    VideoVerificationStage,
    VideoVerificationStageResult,
    VideoVerificationStatus,
)
from ..ports.video_interfaces import (
    IVideoEvidenceVerifier,
    MediaLabVideoQualityReviewError,
    VideoEvidenceVerificationRequest,
)


class _VerificationObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(min_length=1)
    stage: VideoVerificationStage
    category: str = Field(min_length=1)
    status: VideoVerificationStatus
    severity: VideoQualityIssueSeverity
    description: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    start_timestamp_milliseconds: int | None = Field(default=None, ge=0)
    end_timestamp_milliseconds: int | None = Field(default=None, ge=0)
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_timestamp_range(self) -> _VerificationObservation:
        if (
            self.start_timestamp_milliseconds is not None
            and self.end_timestamp_milliseconds is not None
            and self.end_timestamp_milliseconds < self.start_timestamp_milliseconds
        ):
            raise ValueError("Video verifier observation timestamp range is invalid")
        return self


class _VerificationStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: VideoVerificationStage
    status: VideoVerificationStatus
    model: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    observations: list[_VerificationObservation] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class _VerificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: VideoVerificationStatus
    verifier_version: str = Field(min_length=1)
    config_hash: str = Field(min_length=1)
    request_hash: str = Field(min_length=64, max_length=64)
    stages: list[_VerificationStage] = Field(min_length=1)
    suspicious_timestamps_milliseconds: list[int] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    report_hash: str = Field(min_length=64, max_length=64)


class HttpVideoEvidenceVerifier(IVideoEvidenceVerifier):
    def __init__(
        self,
        config: MediaLabVideoVerifierConfig,
        *,
        runpod_endpoint_id: str | None = None,
        runpod_api_key: str | None = None,
        runpod_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._runpod = (
            RunpodServerlessClient(
                runpod_endpoint_id,
                runpod_api_key,
                timeout_seconds=config.request_timeout_seconds,
                transport=runpod_transport,
            )
            if runpod_endpoint_id is not None and runpod_api_key is not None
            else None
        )

    @property
    def verifier_version(self) -> str:
        return self._config.verifier_version

    async def verify(self, request: VideoEvidenceVerificationRequest) -> VideoVerificationReport:
        video = await _read_bounded(request.video_path, self._config.max_video_bytes)
        sources = []
        total_source_image_bytes = 0
        for source in request.sources:
            if len(source.image.content) > self._config.max_source_image_bytes:
                raise MediaLabVideoQualityReviewError(
                    "Video verifier source image exceeds the configured size limit",
                    code="verifier_source_too_large",
                )
            total_source_image_bytes += len(source.image.content)
            sources.append(
                {
                    "source_id": source.source_id,
                    "role": source.role.value,
                    "checksum_sha256": source.checksum_sha256,
                    "must_preserve": list(source.must_preserve),
                    "artifact_ref": source.artifact_ref,
                    "source_origin": source.source_origin.value,
                    "identity_group": source.identity_group,
                    "is_primary_identity": source.is_primary_identity,
                    "content_type": source.image.content_type,
                    "image_base64": base64.b64encode(source.image.content).decode("ascii"),
                }
            )
        if total_source_image_bytes > self._config.max_total_source_image_bytes:
            raise MediaLabVideoQualityReviewError(
                "Video verifier sources exceed the configured total size limit",
                code="verifier_sources_too_large",
            )
        payload = {
            "run_id": request.run_id,
            "video_checksum_sha256": request.video_checksum_sha256,
            "production_prompt": request.production_prompt,
            "expected_duration_seconds": request.expected_duration_seconds,
            "video_content_type": "video/mp4",
            "video_base64": base64.b64encode(video).decode("ascii"),
            "sources": sources,
            "selected_stages": [stage.value for stage in request.selected_stages],
        }
        try:
            if self._runpod is not None:
                output = await self._runpod.invoke(
                    {"operation": "video_verification", "payload": payload}
                )
                if output.get("operation") != "video_verification":
                    raise ValueError("Runpod verifier returned the wrong operation")
                parsed = _VerificationResponse.model_validate(output.get("result"))
            else:
                async with httpx.AsyncClient(
                    base_url=self._config.base_url.rstrip("/"),
                    timeout=httpx.Timeout(self._config.request_timeout_seconds, connect=10),
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    response = await client.post("/v1/video-verifications", json=payload)
                    response.raise_for_status()
                    parsed = _VerificationResponse.model_validate_json(response.content)
            _validate_response_contract(parsed, request, self._config.verifier_version)
            report = _report_from_payload(parsed)
        except (
            httpx.HTTPError,
            RunpodServerlessError,
            OSError,
            ValidationError,
            ValueError,
        ) as error:
            raise MediaLabVideoQualityReviewError(
                "The isolated video verifier did not return a valid report",
                code="verifier_unavailable",
            ) from error
        return report


async def _read_bounded(path: Path, maximum: int) -> bytes:
    content = await __import__("asyncio").to_thread(path.read_bytes)
    if len(content) > maximum:
        raise MediaLabVideoQualityReviewError(
            "Generated video exceeds the verifier size limit",
            code="verifier_video_too_large",
        )
    return content


def _report_from_payload(payload: _VerificationResponse) -> VideoVerificationReport:
    stages = tuple(
        VideoVerificationStageResult(
            stage=stage.stage,
            status=stage.status,
            model=stage.model,
            model_version=stage.model_version,
            observations=tuple(
                VideoVerificationObservation(
                    observation_id=observation.observation_id,
                    stage=observation.stage,
                    category=observation.category,
                    status=observation.status,
                    severity=observation.severity,
                    description=observation.description,
                    confidence=observation.confidence,
                    start_timestamp_milliseconds=observation.start_timestamp_milliseconds,
                    end_timestamp_milliseconds=observation.end_timestamp_milliseconds,
                    evidence_refs=tuple(observation.evidence_refs),
                )
                for observation in stage.observations
            ),
            metadata=tuple(stage.metadata.items()),
        )
        for stage in payload.stages
    )
    return VideoVerificationReport(
        status=payload.status,
        verifier_version=payload.verifier_version,
        config_hash=payload.config_hash,
        request_hash=payload.request_hash,
        stages=stages,
        suspicious_timestamps_milliseconds=tuple(payload.suspicious_timestamps_milliseconds),
        uncertainties=tuple(payload.uncertainties),
        report_hash=payload.report_hash,
    )


def _validate_response_contract(
    payload: _VerificationResponse,
    request: VideoEvidenceVerificationRequest,
    expected_verifier_version: str,
) -> None:
    canonical_specialized = (
        VideoVerificationStage.TRACKING,
        VideoVerificationStage.PRODUCT_FIDELITY,
        VideoVerificationStage.TEMPORAL_QUALITY,
    )
    selected = set(request.selected_stages)
    expected_stages = (
        VideoVerificationStage.TECHNICAL,
        *(stage for stage in canonical_specialized if stage in selected),
    )
    actual_stages = tuple(stage.stage for stage in payload.stages)
    technical_gate_failed = (
        len(payload.stages) == 1
        and payload.stages[0].stage == VideoVerificationStage.TECHNICAL
        and payload.stages[0].status == VideoVerificationStatus.FAIL
    )
    if payload.verifier_version != expected_verifier_version or (
        actual_stages != expected_stages and not technical_gate_failed
    ):
        raise ValueError("Video verifier response does not match the requested contract")
    if payload.request_hash != request_checksum(request):
        raise ValueError("Video verifier response is not bound to the exact request")
    if any(
        observation.stage != stage.stage
        for stage in payload.stages
        for observation in stage.observations
    ):
        raise ValueError("Video verifier observation stage is inconsistent")
    maximum_timestamp = request.expected_duration_seconds * 1_000 + 500
    observation_timestamps = sorted(
        {
            timestamp
            for stage in payload.stages
            for observation in stage.observations
            for timestamp in (
                observation.start_timestamp_milliseconds,
                observation.end_timestamp_milliseconds,
            )
            if timestamp is not None
        }
    )
    if (
        payload.suspicious_timestamps_milliseconds
        != sorted(set(payload.suspicious_timestamps_milliseconds))
        or payload.suspicious_timestamps_milliseconds != observation_timestamps
        or any(timestamp > maximum_timestamp for timestamp in observation_timestamps)
    ):
        raise ValueError("Video verifier timestamps do not match the requested clip")

    aggregate = VideoVerificationStatus.PASS
    for stage in payload.stages:
        if stage.status == VideoVerificationStatus.FAIL:
            aggregate = VideoVerificationStatus.FAIL
        elif (
            stage.status
            in {
                VideoVerificationStatus.UNKNOWN,
                VideoVerificationStatus.UNAVAILABLE,
            }
            and aggregate != VideoVerificationStatus.FAIL
        ):
            aggregate = VideoVerificationStatus.UNKNOWN
        for observation in stage.observations:
            if observation.status == VideoVerificationStatus.FAIL:
                aggregate = VideoVerificationStatus.FAIL
            elif (
                observation.status
                in {
                    VideoVerificationStatus.UNKNOWN,
                    VideoVerificationStatus.UNAVAILABLE,
                }
                and observation.severity
                in {VideoQualityIssueSeverity.MAJOR, VideoQualityIssueSeverity.CRITICAL}
                and aggregate != VideoVerificationStatus.FAIL
            ):
                aggregate = VideoVerificationStatus.UNKNOWN
    if payload.status != aggregate:
        raise ValueError("Video verifier aggregate status is inconsistent")
    hash_payload = payload.model_dump(mode="json", exclude={"report_hash"})
    expected_report_hash = hashlib.sha256(
        json.dumps(hash_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if payload.report_hash != expected_report_hash:
        raise ValueError("Video verifier report hash is inconsistent")


def request_checksum(request: VideoEvidenceVerificationRequest) -> str:
    payload = {
        "run_id": request.run_id,
        "video_checksum_sha256": request.video_checksum_sha256,
        "production_prompt": request.production_prompt,
        "expected_duration_seconds": request.expected_duration_seconds,
        "selected_stages": [stage.value for stage in request.selected_stages],
        "sources": [
            {
                "source_id": source.source_id,
                "checksum_sha256": source.checksum_sha256,
                "role": source.role.value,
                "must_preserve": list(source.must_preserve),
                "artifact_ref": source.artifact_ref,
                "source_origin": source.source_origin.value,
                "identity_group": source.identity_group,
                "is_primary_identity": source.is_primary_identity,
                "content_type": source.image.content_type,
            }
            for source in request.sources
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = ["HttpVideoEvidenceVerifier", "request_checksum"]
