"""9Router multimodal usability analysis for public research references."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, Self
from urllib.parse import urlsplit

import httpx
from baml_py import Collector
from baml_py import Image as BamlImage
from baml_py.baml_py import BamlClientError, BamlError
from baml_py.logging import set_log_level
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ai_content.domains.marketing.creative.adapters.baml_client import types as baml_types
from ai_content.domains.marketing.creative.adapters.baml_client.async_client import b
from ai_content.domains.marketing.creative.adapters.baml_model_profile import (
    build_creative_orchestrator_registry,
)
from ai_content.platform.ai_usage import (
    AIUsageCompletion,
    AIUsageFailure,
    AIUsageStart,
    AIUsageTracker,
)
from ai_content.platform.observability import observe_ai_call

from .artifacts import ResearchCrawlArtifactWriter
from .models import (
    ResearchBrandContext,
    ResearchReferenceProfile,
    ResearchScreening,
    StoredResearchRecord,
)


class ResearchScreeningConfig(BaseModel):
    """Versioned OpenAI-compatible 9Router profile for reference analysis."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    name: str = Field(min_length=1)
    model: str = Field(min_length=1)
    base_url: str
    api_key_env: str = "VILAO_API_KEY"
    prompt_version: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    request_timeout_seconds: float = Field(default=60, gt=0, le=180)
    max_concurrency: int = Field(default=5, ge=1, le=12)
    max_preview_images: int = Field(default=2, ge=0, le=3)
    max_preview_image_bytes: int = Field(default=4_000_000, ge=64_000, le=4_000_000)
    max_preview_videos: int = Field(default=2, ge=0, le=3)
    max_preview_video_bytes: int = Field(default=40_000_000, ge=1_000_000, le=80_000_000)
    video_frames_per_preview: int = Field(default=6, ge=1, le=10)
    video_probe_timeout_seconds: float = Field(default=15, gt=0, le=60)
    max_input_text_bytes: int = Field(default=128_000, ge=1_000, le=128_000)
    max_output_tokens: int = Field(default=32_000, ge=600, le=32_000)
    max_attempts: int = Field(default=2, ge=1, le=3)
    retry_base_delay_seconds: float = Field(default=1, ge=0, le=10)

    @field_validator("base_url")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("base_url must be an HTTP endpoint without credentials or query")
        return value.rstrip("/")

    @field_validator("api_key_env")
    @classmethod
    def validate_api_key_env(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("api_key_env must be an environment variable name")
        return value

    @property
    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


class _ScreeningOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    usable: bool
    materially_blurry: bool
    reason_code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    reason: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)
    profile: ResearchReferenceProfile | None = None

    @model_validator(mode="after")
    def require_conservative_rejection(self) -> Self:
        if not self.usable and not self.reason.strip():
            raise ValueError("unusable references require a reason")
        if self.usable and self.profile is None:
            raise ValueError("usable references require a semantic profile")
        return self


class _PreviewMedia(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    content_type: str
    content: bytes


class _BamlResearchScreeningClient(Protocol):
    async def ScreenResearchReference(
        self,
        instructions: str,
        input_json: str,
        sources: list[baml_types.LabeledReviewImage],
        baml_options: dict[str, object],
    ) -> baml_types.ResearchScreeningDraft: ...


class NineRouterResearchScreener:
    """Fail-closed analysis of bounded image previews and sampled video frames."""

    def __init__(
        self,
        config: ResearchScreeningConfig,
        *,
        api_key: str,
        usage_tracker: AIUsageTracker | None = None,
        artifact_reader: ResearchCrawlArtifactWriter | None = None,
        client: httpx.AsyncClient | None = None,
        baml_client: _BamlResearchScreeningClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Research screening requires the configured 9Router API key")
        self._config = config
        self._api_key = api_key
        self._usage_tracker = usage_tracker
        self._artifact_reader = artifact_reader
        self._client = client
        self._custom_baml_client = baml_client is not None
        set_log_level("OFF")
        self._baml_client = baml_client or self._build_baml_client(config)
        self._semaphore = asyncio.Semaphore(config.max_concurrency)

    @property
    def max_concurrency(self) -> int:
        return self._config.max_concurrency

    def can_reuse(
        self,
        screening: ResearchScreening,
        record: StoredResearchRecord,
        brand_context: ResearchBrandContext | None,
    ) -> bool:
        return (
            screening.status == "completed"
            and screening.content_hash == _analysis_content_hash(record)
            and screening.config_hash == self._config.config_hash
            and screening.context_version == _context_version(brand_context, record)
        )

    async def screen(
        self,
        record: StoredResearchRecord,
        *,
        brand_context: ResearchBrandContext | None,
    ) -> ResearchScreening:
        event_id = None
        if self._usage_tracker is not None:
            event_id = await self._usage_tracker.start(
                AIUsageStart(
                    workstream="research",
                    operation="analyze_reference",
                    backend="nine_router",
                    model=self._config.model,
                    source_run_id=record.latest_run_id,
                    version_id=record.content_hash,
                    brand_id=record.brand_id,
                )
            )
        collector = Collector(name=f"research-screening-{record.record_key}")
        with observe_ai_call(
            "research_screening",
            "baml",
            self._config.model,
            prompt_version=self._config.prompt_version,
            config_hash=self._config.config_hash,
            job_id=record.latest_run_id,
            version_id=record.content_hash,
        ) as observation:
            try:
                async with self._semaphore:
                    previews, _ = await self._load_previews(record)
                    if not previews:
                        raise ValueError("Research media preview is unavailable")
                    output = await self._call_model(
                        record,
                        brand_context,
                        previews,
                        collector,
                    )
            except (
                BamlError,
                httpx.HTTPError,
                OSError,
                TimeoutError,
                ValidationError,
                ValueError,
                KeyError,
                TypeError,
            ) as error:
                request_count, input_tokens, output_tokens = _collector_usage(collector)
                observation.usage(input_tokens, output_tokens)
                observation.fail(_screening_error_code(error))
                if event_id is not None and self._usage_tracker is not None:
                    await self._usage_tracker.fail(
                        event_id,
                        AIUsageFailure(
                            error_code="RESEARCH_ANALYSIS_UNAVAILABLE",
                            request_count=request_count,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                        ),
                    )
                return _unavailable_screening(record, brand_context, self._config, error)
            request_count, input_tokens, output_tokens = _collector_usage(collector)
            observation.usage(input_tokens, output_tokens)
            observation.semantic_review("kept" if output.usable else "filtered", "research")
            observation.succeed(reason_present=bool(output.reason))

        if event_id is not None and self._usage_tracker is not None:
            await self._usage_tracker.succeed(
                event_id,
                AIUsageCompletion(
                    request_count=request_count,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    output_count=1,
                ),
            )
        return ResearchScreening(
            status="completed",
            prompt_version=self._config.prompt_version,
            model=self._config.model,
            content_hash=_analysis_content_hash(record),
            config_hash=self._config.config_hash,
            context_version=_context_version(brand_context, record),
            usable=output.usable,
            reason_code=output.reason_code,
            reason=output.reason,
            confidence=output.confidence,
            profile=output.profile,
            attempt_count=(record.screening.attempt_count + 1 if record.screening else 1),
            last_attempted_at=datetime.now(UTC),
        )

    def _build_baml_client(
        self,
        config: ResearchScreeningConfig,
    ) -> _BamlResearchScreeningClient:
        return b.with_options(
            client_registry=build_creative_orchestrator_registry(
                name="ResearchScreening",
                base_url=config.base_url,
                model=config.model,
                api_key=self._api_key,
                reasoning_effort=None,
                temperature=0,
                max_output_tokens=config.max_output_tokens,
            )
        )

    async def _call_model(
        self,
        record: StoredResearchRecord,
        brand_context: ResearchBrandContext | None,
        previews: list[_PreviewMedia],
        collector: Collector,
    ) -> _ScreeningOutput:
        sources = [
            baml_types.LabeledReviewImage(
                label=preview.label,
                content=BamlImage.from_base64(
                    preview.content_type,
                    base64.b64encode(preview.content).decode("ascii"),
                ),
            )
            for preview in previews
        ]
        payload = self._request_input(record, brand_context)
        last_error: Exception | None = None
        for attempt in range(1, self._config.max_attempts + 1):
            try:
                raw = await asyncio.wait_for(
                    self._baml_client.ScreenResearchReference(
                        instructions=self._config.instructions,
                        input_json=payload,
                        sources=sources,
                        baml_options={"collector": collector},
                    ),
                    timeout=self._config.request_timeout_seconds,
                )
                normalized = raw.model_dump(mode="json")
                if normalized.get("materially_blurry"):
                    normalized.update(
                        usable=False,
                        reason_code="blurry_media",
                        reason=(
                            "The main visual evidence is too blurry to use as a reliable "
                            "Creative reference."
                        ),
                        profile=None,
                    )
                profile = normalized.get("profile")
                if isinstance(profile, dict):
                    profile["audio"] = profile.pop("audio_observations", [])
                return _ScreeningOutput.model_validate(normalized)
            except (BamlError, TimeoutError) as error:
                last_error = error
                if attempt >= self._config.max_attempts or not _is_retryable(error):
                    raise
                await asyncio.sleep(self._config.retry_base_delay_seconds * (2 ** (attempt - 1)))
        assert last_error is not None
        raise last_error

    async def _load_previews(
        self, record: StoredResearchRecord
    ) -> tuple[list[_PreviewMedia], bool]:
        if self._artifact_reader is not None:
            return await self._load_artifact_previews(record)
        previews: list[_PreviewMedia] = []
        failed = False
        for index, url in enumerate(record.image_urls[: self._config.max_preview_images], 1):
            try:
                preview = await self._download_image(url)
            except (ValueError, httpx.HTTPError, OSError):
                failed = True
                continue
            previews.append(preview.model_copy(update={"label": f"image {index}"}))
        for index, url in enumerate(record.video_urls[: self._config.max_preview_videos], 1):
            try:
                frames = await self._sample_video(url, index)
            except (ValueError, httpx.HTTPError, OSError, TimeoutError):
                failed = True
                continue
            previews.extend(frames)
        return previews, failed

    async def _load_artifact_previews(
        self, record: StoredResearchRecord
    ) -> tuple[list[_PreviewMedia], bool]:
        previews: list[_PreviewMedia] = []
        failed = False
        images = [
            asset
            for asset in record.media_assets
            if asset.media_kind == "image" and asset.status == "available" and asset.artifact_ref
        ][: self._config.max_preview_images]
        videos = [
            asset
            for asset in record.media_assets
            if asset.media_kind == "video" and asset.status == "available" and asset.artifact_ref
        ][: self._config.max_preview_videos]
        for index, asset in enumerate(images, 1):
            try:
                content, stored_type = await self._artifact_reader.read_media(
                    asset.artifact_ref or "",
                    max_bytes=self._config.max_preview_image_bytes,
                )
                content_type = asset.content_type or stored_type
                preview_type, preview_content = _compact_preview(content, content_type)
                previews.append(
                    _PreviewMedia(
                        label=f"image {index}",
                        content_type=preview_type,
                        content=preview_content,
                    )
                )
            except (ValueError, OSError):
                failed = True
        for index, asset in enumerate(videos, 1):
            try:
                content, stored_type = await self._artifact_reader.read_media(
                    asset.artifact_ref or "",
                    max_bytes=self._config.max_preview_video_bytes,
                )
                previews.extend(
                    await self._sample_video_content(
                        content,
                        asset.content_type or stored_type,
                        index,
                    )
                )
            except (ValueError, OSError, TimeoutError):
                failed = True
        return previews, failed

    async def _download_image(self, url: str) -> _PreviewMedia:
        content, content_type = await self._download_media(url)
        preview = _compact_preview(content, content_type)
        return _PreviewMedia(label="image", content_type=preview[0], content=preview[1])

    async def _sample_video(self, url: str, video_index: int) -> list[_PreviewMedia]:
        content, content_type = await self._download_media(url)
        return await self._sample_video_content(content, content_type, video_index)

    async def _sample_video_content(
        self,
        content: bytes,
        content_type: str,
        video_index: int,
    ) -> list[_PreviewMedia]:
        suffix = ".webm" if content_type == "video/webm" else ".mp4"
        with tempfile.TemporaryDirectory(prefix="research-video-") as directory:
            source = Path(directory) / f"source{suffix}"
            source.write_bytes(content)
            duration = await self._probe_duration(source)
            timestamps = _sample_timestamps(duration, self._config.video_frames_per_preview)
            frames: list[_PreviewMedia] = []
            for frame_index, timestamp in enumerate(timestamps, 1):
                output = Path(directory) / f"frame-{frame_index}.jpg"
                await self._extract_frame(source, output, timestamp)
                frames.append(
                    _PreviewMedia(
                        label=f"video {video_index} frame {frame_index} at {timestamp:.2f}s",
                        content_type="image/jpeg",
                        content=output.read_bytes(),
                    )
                )
            return frames

    async def _download_media(self, url: str) -> tuple[bytes, str]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._config.request_timeout_seconds, follow_redirects=True
        )
        try:
            response = await client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            return response.content, content_type
        finally:
            if owns_client:
                await client.aclose()

    async def _probe_duration(self, source: Path) -> float:
        stdout = await _run_media_command(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source),
            timeout=self._config.video_probe_timeout_seconds,
        )
        duration = float(stdout.decode().strip())
        if duration <= 0:
            raise ValueError("Video duration is invalid")
        return duration

    async def _extract_frame(self, source: Path, output: Path, timestamp: float) -> None:
        await _run_media_command(
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "scale=min(1280\\,iw):-2",
            "-q:v",
            "3",
            "-y",
            str(output),
            timeout=self._config.video_probe_timeout_seconds,
        )
        if not output.exists() or output.stat().st_size == 0:
            raise ValueError("Video frame extraction produced no image")

    def _request_input(
        self,
        record: StoredResearchRecord,
        brand_context: ResearchBrandContext | None,
    ) -> str:
        candidate = {
            "project_context": _brand_payload(record.brand_id, brand_context),
            "candidate": {
                "platform": record.platform,
                "media_type": "video" if record.video_urls else "image",
                "source_url": record.source_url or "",
                "research_focus": str(record.metadata.get("research_focus") or ""),
                "image_count": len(record.image_urls),
                "video_count": len(record.video_urls),
            },
        }
        encoded = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) > self._config.max_input_text_bytes:
            raise ValueError("Research screening input exceeds the configured byte limit")
        return encoded


def load_research_screening_config(path: Path) -> ResearchScreeningConfig:
    return ResearchScreeningConfig.model_validate_json(path.read_text(encoding="utf-8"))


def _unavailable_screening(
    record: StoredResearchRecord,
    brand_context: ResearchBrandContext | None,
    config: ResearchScreeningConfig,
    error: Exception,
) -> ResearchScreening:
    return ResearchScreening(
        status="failed",
        prompt_version=config.prompt_version,
        model=config.model,
        content_hash=_analysis_content_hash(record),
        config_hash=config.config_hash,
        context_version=_context_version(brand_context, record),
        usable=False,
        reason_code="analysis_unavailable",
        reason="The media could not be analyzed, so it was not admitted to the reference library.",
        confidence=0,
        error_code=type(error).__name__.upper(),
        attempt_count=(record.screening.attempt_count + 1 if record.screening else 1),
        last_attempted_at=datetime.now(UTC),
    )


async def _run_media_command(*args: str, timeout: float) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise
    if process.returncode != 0:
        raise ValueError(f"Media preview command failed: {stderr.decode(errors='ignore')[:200]}")
    return stdout


def _sample_timestamps(duration: float, count: int) -> list[float]:
    return [duration * index / (count + 1) for index in range(1, count + 1)]


def _brand_payload(brand_id: str, context: ResearchBrandContext | None) -> dict[str, object]:
    if context is None:
        return {
            "project_id": brand_id,
            "context_version": "unavailable",
            "product_facts": [],
            "supporting_facts": [],
        }
    return {
        "project_id": context.brand_id,
        "context_version": context.version,
        "product_facts": [_truncate_utf8(fact, 240) for fact in context.product_facts[:12]],
        "supporting_facts": [_truncate_utf8(fact, 240) for fact in context.supporting_facts[:12]],
    }


def _context_version(
    context: ResearchBrandContext | None,
    record: StoredResearchRecord,
) -> str:
    context_version = context.version if context is not None else "unavailable"
    research_focus = str(record.metadata.get("research_focus") or "").strip()
    if not research_focus:
        return context_version
    focus_hash = hashlib.sha256(research_focus.encode()).hexdigest()[:12]
    return f"{context_version}:focus:{focus_hash}"


def _analysis_content_hash(record: StoredResearchRecord) -> str:
    """Bind an analysis decision to both metadata and captured media bytes."""
    value = "\n".join((record.content_hash, record.media_content_hash))
    return hashlib.sha256(value.encode()).hexdigest()


def _compact_preview(content: bytes, content_type: str) -> tuple[str, bytes]:
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.thumbnail((1280, 1280))
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=85, optimize=True)
            return "image/jpeg", output.getvalue()
    except OSError:
        return content_type, content


def _truncate_utf8(value: str, max_bytes: int) -> str:
    return value.encode()[:max_bytes].decode(errors="ignore")


def _collector_usage(collector: Collector) -> tuple[int, int | None, int | None]:
    log = collector.last
    request_count = max(1, len(log.calls)) if log is not None else 1
    return request_count, collector.usage.input_tokens, collector.usage.output_tokens


def _is_retryable(error: Exception) -> bool:
    if isinstance(error, TimeoutError):
        return True
    if not isinstance(error, BamlClientError):
        return False
    return bool(re.search(r"(?:status(?:_code)?\D*)?(429|5\d\d)\b", str(error), re.IGNORECASE))


def _screening_error_code(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "provider_timeout"
    if isinstance(error, ValidationError):
        return "invalid_provider_schema"
    if isinstance(error, BamlError):
        return "provider_error"
    if isinstance(error, ValueError):
        return "invalid_media_or_output"
    return type(error).__name__.lower()


__all__ = [
    "NineRouterResearchScreener",
    "ResearchScreeningConfig",
    "load_research_screening_config",
]
