"""Secure source resolution, artifact persistence and managed media adapters."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import shutil
import socket
import subprocess
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from ai_content.domains.marketing.creative.config.managed_media import (
    ManagedImageModelConfig,
    ManagedMediaConfig,
    ManagedVideoModelConfig,
)
from ai_content.domains.marketing.creative.ports.media_production import (
    PaidAssembledVideoRequest,
    PaidImageGenerationRequest,
    PaidImageModelDescriptor,
    PaidMediaArtifact,
    PaidMediaProviderDescriptor,
    PaidMediaSource,
    PaidVideoGenerationRequest,
    PaidVideoModelDescriptor,
    ProductMediaSourceRef,
)
from ai_content.platform.artifacts import (
    ArtifactKind,
    ArtifactService,
    ArtifactStatus,
    ArtifactStore,
)
from ai_content.platform.artifacts.object_storage import iter_download


@dataclass(frozen=True)
class StoredMedia:
    artifact_ref: str
    path: Path
    checksum_sha256: str


class ManagedMediaArtifactSink:
    """Persist provider output locally and publish it to shared storage when available."""

    def __init__(self, store: ArtifactStore, service: ArtifactService | None = None) -> None:
        self._store = store
        self._service = service
        self._paths: dict[str, Path] = {}
        self._checksums: dict[str, str] = {}

    async def write(
        self,
        content: bytes,
        *,
        request_id: str,
        filename: str,
        owner_id: str,
        brand_scope: str | None = None,
        kind: ArtifactKind = ArtifactKind.GENERATED,
    ) -> StoredMedia:
        safe_request = hashlib.sha256(request_id.encode()).hexdigest()[:20]
        path = await asyncio.to_thread(
            self._store.write_bytes,
            content,
            "managed-media",
            safe_request,
            filename,
        )
        checksum = hashlib.sha256(content).hexdigest()
        artifact_ref = path.relative_to(self._store.root.resolve()).as_posix()
        if self._service is not None:
            record = await self._service.publish_file(
                path,
                artifact_ref,
                kind=kind,
                owner_type="marketing_creative_automation",
                owner_id=owner_id,
                brand_scope=brand_scope,
            )
            artifact_ref = f"artifact:{record.artifact_id}"
        self._paths[artifact_ref] = path
        self._checksums[artifact_ref] = checksum
        return StoredMedia(artifact_ref, path, checksum)

    def local_path(self, artifact_ref: str) -> Path:
        path = self._paths.get(artifact_ref)
        if path is not None:
            return path
        candidate = self._store.path(*artifact_ref.split("/"))
        if not candidate.is_file():
            raise ValueError("Managed media artifact is unavailable in this worker")
        return candidate

    async def materialize(
        self, artifact_ref: str, checksum_sha256: str, *, max_bytes: int | None
    ) -> Path:
        cached = self._paths.get(artifact_ref)
        if cached is not None:
            await asyncio.to_thread(_verify_file_checksum, cached, checksum_sha256, max_bytes)
            self._checksums[artifact_ref] = checksum_sha256
            return cached
        artifact_id = artifact_ref.removeprefix("artifact:")
        if not artifact_ref.startswith("artifact:"):
            path = self._store.path(*artifact_ref.split("/"))
            if path.is_file():
                await asyncio.to_thread(_verify_file_checksum, path, checksum_sha256, max_bytes)
                self._paths[artifact_ref] = path
                self._checksums[artifact_ref] = checksum_sha256
                return path
        if self._service is None:
            raise ValueError("Shared artifact storage is required to materialize media")
        record = await self._service.catalog.get(artifact_id)
        if record is None or record.status != ArtifactStatus.AVAILABLE:
            raise ValueError("Frozen media artifact is unavailable")
        if record.sha256 != checksum_sha256 or (
            max_bytes is not None and record.size_bytes > max_bytes
        ):
            raise ValueError("Frozen media artifact metadata does not match")
        content = await asyncio.to_thread(_read_stored_artifact, self._service, record.object_key)
        if (max_bytes is not None and len(content) > max_bytes) or (
            hashlib.sha256(content).hexdigest() != checksum_sha256
        ):
            raise ValueError("Frozen media artifact failed checksum verification")
        filename = Path(record.source_path).name or "product-source"
        path = await asyncio.to_thread(
            self._store.write_bytes,
            content,
            "managed-media",
            "materialized",
            artifact_id,
            filename,
        )
        self._paths[artifact_ref] = path
        self._checksums[artifact_ref] = checksum_sha256
        return path

    def read_materialized(self, artifact_ref: str, *, max_bytes: int | None) -> bytes:
        path = self._paths.get(artifact_ref)
        checksum = self._checksums.get(artifact_ref)
        if path is None or checksum is None:
            raise ValueError("Frozen product media was not materialized by this worker")
        _verify_file_checksum(path, checksum, max_bytes)
        return path.read_bytes()


class ImmutableProductSourceResolver:
    """Download product images once with SSRF, MIME and size boundaries."""

    def __init__(
        self,
        sink: ManagedMediaArtifactSink,
        *,
        allowed_hosts: tuple[str, ...],
        timeout_seconds: float,
        max_bytes: int | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._sink = sink
        self._allowed_hosts = frozenset(host.lower() for host in allowed_hosts)
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes
        self._client = client

    async def resolve_product_sources(
        self,
        *,
        request_id: str,
        sku_id: str,
        source_refs: tuple[ProductMediaSourceRef, ...],
    ) -> tuple[PaidMediaSource, ...]:
        del sku_id
        resolved: list[PaidMediaSource] = []
        for index, source_ref in enumerate(source_refs):
            if source_ref.artifact_ref is not None:
                assert source_ref.checksum_sha256 is not None
                await self._sink.materialize(
                    source_ref.artifact_ref,
                    source_ref.checksum_sha256,
                    max_bytes=self._max_bytes,
                )
                stored_ref = source_ref.artifact_ref
                checksum = source_ref.checksum_sha256
            else:
                assert source_ref.url is not None
                content, content_type = await self._read_source(source_ref.url)
                extension = _image_extension(content_type)
                stored = await self._sink.write(
                    content,
                    request_id=f"{request_id}:source:{index}",
                    filename=f"product-{index}.{extension}",
                    owner_id=request_id,
                    kind=ArtifactKind.SOURCE,
                )
                stored_ref = stored.artifact_ref
                checksum = stored.checksum_sha256
            resolved.append(
                PaidMediaSource(
                    stored_ref,
                    checksum,
                    "product",
                    source_id=source_ref.source_id,
                    product_id=source_ref.product_id,
                    media_id=source_ref.media_id,
                    variant_ids=source_ref.variant_ids,
                )
            )
        return tuple(resolved)

    def read_frozen_source(self, artifact_ref: str, max_bytes: int | None = None) -> bytes:
        """Return a bounded deterministic preview of frozen media for planning input.

        Paid generation must keep reading the exact frozen bytes through
        ``resolve_product_sources``; planning models receive this preview to
        stay within provider request limits.
        """

        content = self._sink.read_materialized(artifact_ref, max_bytes=max_bytes)
        return _planning_preview(content)

    async def resolve_brand_asset(
        self,
        *,
        artifact_ref: str,
        checksum_sha256: str,
    ) -> PaidMediaSource:
        await self._sink.materialize(
            artifact_ref,
            checksum_sha256,
            max_bytes=self._max_bytes,
        )
        return PaidMediaSource(
            asset_ref=artifact_ref,
            checksum_sha256=checksum_sha256,
            role="logo",
        )

    async def resolve_reference_asset(
        self,
        *,
        reference_id: str,
        artifact_ref: str,
        checksum_sha256: str,
        swap_mode: Literal["insert", "replace"] | None = None,
        placement_note: str = "",
    ) -> PaidMediaSource:
        await self._sink.materialize(
            artifact_ref,
            checksum_sha256,
            max_bytes=self._max_bytes,
        )
        return PaidMediaSource(
            asset_ref=artifact_ref,
            checksum_sha256=checksum_sha256,
            role="style",
            media_id=reference_id,
            swap_mode=swap_mode,
            note=placement_note or None,
        )

    async def _read_source(self, source_ref: str) -> tuple[bytes, str]:
        parsed = urlsplit(source_ref)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Product source must be a credential-free HTTPS URL")
        await _validate_public_host(parsed.hostname, self._allowed_hosts)
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._timeout_seconds,
            follow_redirects=False,
        )
        try:
            async with client.stream("GET", source_ref) as response:
                response.raise_for_status()
                if response.is_redirect:
                    raise ValueError("Product source redirects are not allowed")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type not in {"image/png", "image/jpeg", "image/webp"}:
                    raise ValueError("Product source must be PNG, JPEG or WebP")
                content = await _bounded_response_bytes(response, self._max_bytes)
        finally:
            if owns_client:
                await client.aclose()
        await asyncio.to_thread(_verify_image, content)
        return content, content_type


_SOURCE_PRESERVING_PROVIDER_ID = "shopify-source-preserving@1"
_SOURCE_PRESERVING_IMAGE_MODEL = "shopify-source-transform-image-v1"
_SOURCE_PRESERVING_VIDEO_MODEL = "shopify-source-transform-video-v1"
_SOURCE_PRESERVING_CONFIGURATION_VERSION = "shopify-source-preserving@1"


class SourcePreservingImageProvider:
    """Render one frozen Shopify product source without invoking a generative model."""

    def __init__(self, sink: ManagedMediaArtifactSink) -> None:
        self._sink = sink
        self.descriptor = PaidMediaProviderDescriptor(
            provider_id=_SOURCE_PRESERVING_PROVIDER_ID,
            media_kind="image",
            approved=True,
            configuration_version=_SOURCE_PRESERVING_CONFIGURATION_VERSION,
            supported_aspect_ratios=("1:1", "4:5", "9:16", "16:9", "4:3", "3:4", "3:2", "2:3"),
            supported_image_formats=("png", "jpeg", "webp"),
            max_reference_images=1,
            image_models=(
                PaidImageModelDescriptor(
                    model_id=_SOURCE_PRESERVING_IMAGE_MODEL,
                    display_name="Exact Shopify product fidelity (no AI redraw)",
                    supported_modes=("single_image_edit",),
                    supported_aspect_ratios=(
                        "1:1",
                        "4:5",
                        "9:16",
                        "16:9",
                        "4:3",
                        "3:4",
                        "3:2",
                        "2:3",
                    ),
                    supported_resolutions=("1k",),
                    supported_qualities=(),
                    supported_formats=("png", "jpeg", "webp"),
                    max_reference_images=1,
                    supports_text_rendering=False,
                    supports_logo_input=False,
                    fidelity_mode="exact_source_transform",
                ),
            ),
            fidelity_mode="exact_source_transform",
        )

    async def generate(self, request: PaidImageGenerationRequest) -> PaidMediaArtifact:
        source = _require_exact_product_source(request.sources)
        if request.model_id not in {None, _SOURCE_PRESERVING_IMAGE_MODEL}:
            raise ValueError("Exact Shopify image renderer does not support the selected model")
        if request.include_text or request.include_logo or request.logo_source is not None:
            raise ValueError("Exact Shopify image renderer does not support text or logo inputs")
        started = monotonic()
        content = await asyncio.to_thread(
            _render_source_preserving_image,
            self._sink.local_path(source.asset_ref),
            request.width,
            request.height,
            request.file_format,
        )
        stored = await self._sink.write(
            content,
            request_id=request.request_id,
            filename=f"output.{_image_extension(_image_content_type(request.file_format))}",
            owner_id=request.request_id,
        )
        return PaidMediaArtifact(
            artifact_ref=stored.artifact_ref,
            checksum_sha256=stored.checksum_sha256,
            content_type=_image_content_type(request.file_format),
            provider_id=self.descriptor.provider_id,
            provider_job_id=_source_transform_job_id(request.request_id, source.checksum_sha256),
            model=_SOURCE_PRESERVING_IMAGE_MODEL,
            model_revision=_SOURCE_PRESERVING_CONFIGURATION_VERSION,
            elapsed_seconds=monotonic() - started,
            cost=Decimal("0"),
            width=request.width,
            height=request.height,
            configuration_version=_SOURCE_PRESERVING_CONFIGURATION_VERSION,
            requested_model=_SOURCE_PRESERVING_IMAGE_MODEL,
            fidelity_mode="exact_source_transform",
            product_source_checksum_sha256=source.checksum_sha256,
        )


class SourcePreservingVideoProvider:
    """Create a silent motion clip from one frozen Shopify source without product redraw."""

    def __init__(self, sink: ManagedMediaArtifactSink) -> None:
        self._sink = sink
        durations = tuple(range(1, 31))
        self.descriptor = PaidMediaProviderDescriptor(
            provider_id=_SOURCE_PRESERVING_PROVIDER_ID,
            media_kind="video",
            approved=True,
            configuration_version=_SOURCE_PRESERVING_CONFIGURATION_VERSION,
            supported_aspect_ratios=("1:1", "4:5", "9:16", "16:9", "4:3", "3:4", "3:2", "2:3"),
            duration_min_seconds=min(durations),
            duration_max_seconds=max(durations),
            supports_native_voice=False,
            supports_native_music=False,
            max_reference_images=1,
            supported_generation_durations_seconds=durations,
            video_models=(
                PaidVideoModelDescriptor(
                    model_id=_SOURCE_PRESERVING_VIDEO_MODEL,
                    display_name="Exact Shopify motion (no AI redraw)",
                    supported_aspect_ratios=(
                        "1:1",
                        "4:5",
                        "9:16",
                        "16:9",
                        "4:3",
                        "3:4",
                        "3:2",
                        "2:3",
                    ),
                    supported_resolutions=("480p", "720p", "1080p"),
                    supported_generation_durations_seconds=durations,
                    max_reference_images=1,
                    supports_native_voice=False,
                    supports_native_music=False,
                    fidelity_mode="exact_source_transform",
                ),
            ),
            fidelity_mode="exact_source_transform",
        )

    async def generate(self, request: PaidVideoGenerationRequest) -> PaidMediaArtifact:
        source = _require_exact_product_source(request.sources)
        if request.model_id not in {None, _SOURCE_PRESERVING_VIDEO_MODEL}:
            raise ValueError("Exact Shopify video renderer does not support the selected model")
        if request.expects_audio or request.generate_audio is True:
            raise ValueError("Exact Shopify video renderer produces silent clips only")
        width, height = _source_preserving_video_dimensions(
            request.aspect_ratio,
            request.resolution or "720p",
        )
        started = monotonic()
        content, metadata = await asyncio.to_thread(
            _render_source_preserving_video,
            self._sink.local_path(source.asset_ref),
            width,
            height,
            request.duration_seconds,
            request.limits.timeout_seconds,
        )
        stored = await self._sink.write(
            content,
            request_id=request.request_id,
            filename="output.mp4",
            owner_id=request.request_id,
        )
        return PaidMediaArtifact(
            artifact_ref=stored.artifact_ref,
            checksum_sha256=stored.checksum_sha256,
            content_type="video/mp4",
            provider_id=self.descriptor.provider_id,
            provider_job_id=_source_transform_job_id(request.request_id, source.checksum_sha256),
            model=_SOURCE_PRESERVING_VIDEO_MODEL,
            model_revision=_SOURCE_PRESERVING_CONFIGURATION_VERSION,
            elapsed_seconds=monotonic() - started,
            cost=Decimal("0"),
            width=metadata["width"],
            height=metadata["height"],
            duration_seconds=round(metadata["duration_seconds"]),
            has_audio_stream=metadata["has_audio_stream"],
            configuration_version=_SOURCE_PRESERVING_CONFIGURATION_VERSION,
            requested_model=_SOURCE_PRESERVING_VIDEO_MODEL,
            fidelity_mode="exact_source_transform",
            product_source_checksum_sha256=source.checksum_sha256,
        )

    async def assemble(self, request: PaidAssembledVideoRequest) -> PaidMediaArtifact:
        del request
        raise ValueError(
            "Exact Shopify video renderer creates one final clip and does not assemble scenes"
        )

    async def still_frame(
        self, clip: PaidMediaArtifact, at_seconds: float, request_id: str
    ) -> PaidMediaArtifact:
        return await _still_frame(self._sink, clip, at_seconds, request_id)


class NineRouterImageProvider:
    def __init__(
        self,
        config: ManagedMediaConfig,
        model: ManagedImageModelConfig,
        api_key: str,
        sink: ManagedMediaArtifactSink,
        *,
        models: tuple[ManagedImageModelConfig, ...] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._model = model
        self._api_key = api_key
        self._sink = sink
        self._client = client
        self._models = models or (model,)
        ratios = tuple(
            dict.fromkeys(ratio for item in self._models for ratio in item.supported_aspect_ratios)
        )
        formats = tuple(
            dict.fromkeys(value for item in self._models for value in item.supported_formats)
        )
        self.descriptor = PaidMediaProviderDescriptor(
            provider_id=config.profile_id,
            media_kind="image",
            approved=config.approved,
            configuration_version=config.configuration_version,
            supported_aspect_ratios=ratios,
            supported_image_formats=formats,
            max_reference_images=max(item.max_reference_images for item in self._models),
            image_models=tuple(_image_model_descriptor(item) for item in self._models),
            fidelity_mode="generative",
            selected_sku_enabled=config.selected_sku_enabled,
        )

    def _model_for(self, request: PaidImageGenerationRequest) -> ManagedImageModelConfig:
        requested = request.model_id or self._model.model
        try:
            return next(item for item in self._models if item.model == requested)
        except StopIteration as error:
            raise ValueError(
                "Configured image provider does not support the selected model"
            ) from error

    async def generate(self, request: PaidImageGenerationRequest) -> PaidMediaArtifact:
        model = self._model_for(request)
        if request.file_format not in model.supported_formats:
            raise ValueError("Configured image model does not support the requested format")
        if request.image_size is not None and request.image_size not in model.supported_image_sizes:
            raise ValueError("Configured image model does not support the requested size")
        if request.background is not None and request.background not in model.supported_backgrounds:
            raise ValueError("Configured image model does not support the requested background")
        if request.moderation is not None and request.moderation not in model.supported_moderation:
            raise ValueError("Configured image model does not support the requested moderation")
        if (
            request.input_fidelity is not None
            and request.input_fidelity not in model.supported_input_fidelities
        ):
            raise ValueError("Configured image model does not support the requested input fidelity")
        if request.output_compression is not None and (
            not model.supports_output_compression or request.file_format == "png"
        ):
            raise ValueError("Configured image model does not support output compression")
        resolution = request.resolution or model.supported_resolutions[0]
        quality = request.quality or model.default_quality
        cost_per_output = model.cost_rate(resolution, quality)
        model_sources = request.sources + ((request.logo_source,) if request.logo_source else ())
        if len(model_sources) > model.max_reference_images:
            raise ValueError("Image plan selected more sources than the provider supports")
        source_paths = [self._sink.local_path(item.asset_ref) for item in model_sources]
        encoded_sources = [_encoded_source_data_url(path) for path in source_paths]
        payload: dict[str, object] = {
            "model": model.model,
            "prompt": _image_prompt(request),
            "n": 1,
            "size": request.image_size
            or _provider_image_size(model, request.width, request.height),
        }
        if quality is not None:
            payload["quality"] = quality
        if model.send_resolution:
            payload["resolution"] = resolution
        if request.background is not None:
            payload["background"] = request.background
        if request.moderation is not None:
            payload["moderation"] = request.moderation
        if request.output_compression is not None:
            payload["output_compression"] = request.output_compression
        if request.input_fidelity is not None:
            payload["input_fidelity"] = request.input_fidelity
        payload["output_format"] = request.file_format
        endpoint = "images/generations"
        if model.request_mode in {"json_generation", "json_edit"} and encoded_sources:
            payload[model.reference_field] = _reference_payload(model, encoded_sources)
        if model.request_mode == "json_edit":
            if not encoded_sources:
                raise ValueError("Image edit requests require at least one source image")
            endpoint = "images/edits"
        elif model.request_mode == "multipart_edit":
            if not source_paths:
                raise ValueError("Image edit requests require at least one source image")
            endpoint = "images/edits"
        started = monotonic()
        response = await self._post(
            endpoint,
            payload,
            request.request_id,
            source_paths=source_paths if model.request_mode == "multipart_edit" else (),
            reference_field=model.reference_field,
        )
        content, provider_job_id, actual_model = await self._image_content(
            response,
            requested_model=model.model,
        )
        normalized = await asyncio.to_thread(
            _normalize_image,
            content,
            request.width,
            request.height,
            request.file_format,
        )
        stored = await self._sink.write(
            normalized,
            request_id=request.request_id,
            filename=f"output.{_image_extension(_image_content_type(request.file_format))}",
            owner_id=request.request_id,
        )
        return PaidMediaArtifact(
            artifact_ref=stored.artifact_ref,
            checksum_sha256=stored.checksum_sha256,
            content_type=_image_content_type(request.file_format),
            provider_id=self.descriptor.provider_id,
            provider_job_id=provider_job_id,
            model=actual_model,
            model_revision=None,
            elapsed_seconds=monotonic() - started,
            cost=cost_per_output,
            width=request.width,
            height=request.height,
            configuration_version=self._config.configuration_version,
            requested_model=model.model,
            connection_id=response.headers.get("x-9router-connection-id"),
        )

    async def _post(
        self,
        endpoint: str,
        payload: dict[str, object],
        idempotency_key: str,
        *,
        source_paths: list[Path] | tuple[Path, ...] = (),
        reference_field: str = "image",
    ) -> httpx.Response:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._config.request_timeout_seconds)
        try:
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Idempotency-Key": idempotency_key,
            }
            url = f"{self._config.resolved_image_base_url.rstrip('/')}/{endpoint}"
            if source_paths:
                upload_field = (
                    f"{reference_field}[]"
                    if len(source_paths) > 1 and not reference_field.endswith("[]")
                    else reference_field
                )
                files = [
                    (
                        upload_field,
                        (path.name, path.read_bytes(), _source_image_content_type(path)),
                    )
                    for path in source_paths
                ]
                response = await client.post(
                    url,
                    headers=headers,
                    data={key: str(value) for key, value in payload.items()},
                    files=files,
                )
            else:
                response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response
        finally:
            if owns_client:
                await client.aclose()

    async def _image_content(
        self,
        response: httpx.Response,
        *,
        requested_model: str,
    ) -> tuple[bytes, str, str]:
        payload = response.json()
        try:
            item = payload["data"][0]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("Image provider response did not contain an output") from error
        provider_job_id = str(
            payload.get("id") or response.headers.get("x-request-id") or "unreported"
        )
        model = str(payload.get("model") or requested_model)
        if item.get("b64_json"):
            try:
                content = base64.b64decode(item["b64_json"], validate=True)
            except (ValueError, TypeError) as error:
                raise ValueError("Image provider returned invalid base64") from error
            if (
                self._config.max_image_output_bytes is not None
                and len(content) > self._config.max_image_output_bytes
            ):
                raise ValueError("Image provider output exceeds the configured byte limit")
            return content, provider_job_id, model
        url = item.get("url")
        if not isinstance(url, str):
            raise ValueError("Image provider response did not contain image bytes or URL")
        content = await _download_public_url(
            url,
            allowed_hosts=self._config.allowed_output_hosts,
            max_bytes=self._config.max_image_output_bytes,
            timeout_seconds=self._config.request_timeout_seconds,
            client=self._client,
        )
        return content, provider_job_id, model


class NineRouterVideoProvider:
    def __init__(
        self,
        config: ManagedMediaConfig,
        model: ManagedVideoModelConfig,
        api_key: str,
        sink: ManagedMediaArtifactSink,
        *,
        models: tuple[ManagedVideoModelConfig, ...] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._model = model
        configured_models = models or (model,)
        self._models = {item.model: item for item in configured_models}
        self._api_key = api_key
        self._sink = sink
        self._client = client
        durations = tuple(
            sorted(
                {
                    duration
                    for item in configured_models
                    for duration in item.supported_generation_durations_seconds
                }
            )
        )
        ratios = tuple(
            dict.fromkeys(
                ratio for item in configured_models for ratio in item.supported_aspect_ratios
            )
        )
        self.descriptor = PaidMediaProviderDescriptor(
            provider_id=config.profile_id,
            media_kind="video",
            approved=config.approved,
            configuration_version=config.configuration_version,
            supported_aspect_ratios=ratios,
            duration_min_seconds=min(durations),
            duration_max_seconds=max(durations),
            supports_native_voice=any(item.supports_native_voice for item in configured_models),
            supports_native_music=any(item.supports_native_music for item in configured_models),
            max_reference_images=max(item.max_reference_images for item in configured_models),
            supported_generation_durations_seconds=durations,
            video_models=tuple(
                PaidVideoModelDescriptor(
                    model_id=item.model,
                    display_name=item.display_name or item.model,
                    supported_aspect_ratios=item.supported_aspect_ratios,
                    supported_resolutions=item.resolved_resolutions,
                    supported_generation_durations_seconds=tuple(
                        sorted(item.supported_generation_durations_seconds)
                    ),
                    max_reference_images=item.max_reference_images,
                    max_product_images=item.max_product_images,
                    reference_to_video_resolutions=item.reference_to_video_resolutions,
                    supports_native_voice=item.supports_native_voice,
                    supports_native_music=item.supports_native_music,
                    fidelity_mode="generative",
                )
                for item in configured_models
            ),
            fidelity_mode="generative",
            selected_sku_enabled=config.selected_sku_enabled,
        )

    def _model_for(self, request: PaidVideoGenerationRequest) -> ManagedVideoModelConfig:
        model_id = request.model_id or self._model.model
        try:
            model = self._models[model_id]
        except KeyError as error:
            raise ValueError(
                f"Configured video provider does not support model {model_id}"
            ) from error
        if request.aspect_ratio not in model.supported_aspect_ratios:
            raise ValueError(f"Video model {model_id} does not support {request.aspect_ratio}")
        if request.duration_seconds not in model.supported_generation_durations_seconds:
            raise ValueError(f"Video model {model_id} does not support this duration")
        if request.resolution is not None and request.resolution not in model.resolved_resolutions:
            raise ValueError(f"Video model {model_id} does not support {request.resolution}")
        return model

    async def generate(self, request: PaidVideoGenerationRequest) -> PaidMediaArtifact:
        model = self._model_for(request)
        # A keyframe is a generated still that already contains the product; it starts the clip.
        product_sources = tuple(
            item for item in request.sources if item.role in {"product", "keyframe"}
        )
        reference_sources = tuple(item for item in request.sources if item.role == "style")
        if len(request.sources) > model.max_reference_images:
            raise ValueError("Video plan selected more sources than the provider supports")
        if len(product_sources) > model.max_product_images:
            raise ValueError("Video plan selected more product images than the provider supports")
        resolution = request.resolution or model.resolution
        use_reference_to_video = bool(
            resolution in model.reference_to_video_resolutions
            and (len(product_sources) > 1 or reference_sources)
        )
        if not use_reference_to_video and (len(product_sources) != 1 or reference_sources):
            raise ValueError(
                "Image-to-video requires exactly one product image and no Research references"
            )
        payload = {
            "model": model.model,
            "prompt": _video_prompt(request),
            "duration": request.duration_seconds,
            "aspect_ratio": request.aspect_ratio,
            "resolution": resolution,
        }
        if use_reference_to_video:
            payload["reference_images"] = [
                {
                    "url": _encoded_video_source_data_url(
                        self._sink.local_path(source.asset_ref), request.aspect_ratio
                    )
                }
                for source in request.sources
            ]
        else:
            payload["image"] = {
                "url": _encoded_video_source_data_url(
                    self._sink.local_path(product_sources[0].asset_ref),
                    request.aspect_ratio,
                )
            }
        if request.generate_audio is not None:
            payload["generate_audio"] = request.generate_audio
        started = monotonic()
        response = await self._request(
            "POST",
            "videos/generations",
            json_payload=payload,
            idempotency_key=request.request_id,
        )
        body = response.json()
        request_id = body.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("Video provider did not return a request_id")
        connection_id = response.headers.get("x-9router-connection-id")
        deadline = monotonic() + min(
            request.limits.timeout_seconds,
            self._config.generation_timeout_seconds,
        )
        completed = None
        while monotonic() < deadline:
            poll = await self._request(
                "GET",
                f"videos/{request_id}",
                connection_id=connection_id,
            )
            payload = poll.json()
            status = str(payload.get("status", "")).lower()
            if status == "done":
                completed = payload
                break
            if status in {"failed", "error", "cancelled", "expired"}:
                raise ValueError("Video provider generation failed")
            await asyncio.sleep(_poll_delay(poll, self._config.poll_interval_seconds))
        if completed is None:
            raise TimeoutError("Video provider generation timed out")
        video = completed.get("video")
        if not isinstance(video, dict) or not isinstance(video.get("url"), str):
            raise ValueError("Video provider completed without an output URL")
        content = await _download_public_url(
            video["url"],
            allowed_hosts=self._config.allowed_output_hosts,
            max_bytes=self._config.max_video_output_bytes,
            timeout_seconds=self._config.request_timeout_seconds,
            client=self._client,
        )
        stored = await self._sink.write(
            content,
            request_id=request.request_id,
            filename="source.mp4",
            owner_id=request.request_id,
        )
        metadata = await asyncio.to_thread(_probe_video, stored.path)
        return PaidMediaArtifact(
            artifact_ref=stored.artifact_ref,
            checksum_sha256=stored.checksum_sha256,
            content_type="video/mp4",
            provider_id=self.descriptor.provider_id,
            provider_job_id=request_id,
            model=str(completed.get("model") or model.model),
            model_revision=None,
            elapsed_seconds=monotonic() - started,
            cost=model.cost_rate(request.resolution or model.resolution)
            * Decimal(request.duration_seconds)
            + model.input_image_cost * Decimal(len(request.sources)),
            width=metadata["width"],
            height=metadata["height"],
            duration_seconds=round(metadata["duration_seconds"]),
            has_audio_stream=metadata["has_audio_stream"],
            connection_id=connection_id,
            configuration_version=self._config.configuration_version,
            requested_model=model.model,
        )

    async def assemble(self, request: PaidAssembledVideoRequest) -> PaidMediaArtifact:
        started = monotonic()
        durations = request.scene_usable_durations_seconds or tuple(
            item.duration_seconds or 0 for item in request.scene_artifacts
        )
        width, height = _ratio_dimensions(request.aspect_ratio)
        paths = tuple(self._sink.local_path(item.artifact_ref) for item in request.scene_artifacts)
        content, metadata = await asyncio.to_thread(
            _assemble_video,
            paths,
            durations,
            width,
            height,
            request.expects_audio,
            request.limits.timeout_seconds,
        )
        stored = await self._sink.write(
            content,
            request_id=request.request_id,
            filename="final.mp4",
            owner_id=request.request_id,
        )
        digest = hashlib.sha256(
            ":".join(item.provider_job_id for item in request.scene_artifacts).encode()
        ).hexdigest()[:20]
        return PaidMediaArtifact(
            artifact_ref=stored.artifact_ref,
            checksum_sha256=stored.checksum_sha256,
            content_type="video/mp4",
            provider_id=self.descriptor.provider_id,
            provider_job_id=f"assembled-{digest}",
            model="ffmpeg",
            model_revision=None,
            elapsed_seconds=monotonic() - started,
            cost=Decimal("0"),
            width=metadata["width"],
            height=metadata["height"],
            duration_seconds=round(metadata["duration_seconds"]),
            has_audio_stream=metadata["has_audio_stream"],
            configuration_version=self._config.configuration_version,
            requested_model=self._model.model,
        )

    async def still_frame(
        self, clip: PaidMediaArtifact, at_seconds: float, request_id: str
    ) -> PaidMediaArtifact:
        return await _still_frame(self._sink, clip, at_seconds, request_id)

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        json_payload: dict[str, object] | None = None,
        connection_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._config.request_timeout_seconds)
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if method == "POST" and json_payload is not None:
            if idempotency_key is None:
                raise ValueError("Video creation requires an idempotency key")
            headers["Idempotency-Key"] = hashlib.sha256(
                (
                    idempotency_key
                    + ":"
                    + json.dumps(json_payload, sort_keys=True, separators=(",", ":"))
                ).encode()
            ).hexdigest()
        if connection_id is not None:
            headers["x-connection-id"] = connection_id
        try:
            response = await client.request(
                method,
                f"{self._config.resolved_video_base_url.rstrip('/')}/{endpoint}",
                headers=headers,
                json=json_payload,
            )
            response.raise_for_status()
            return response
        finally:
            if owns_client:
                await client.aclose()


def _require_exact_product_source(sources: tuple[PaidMediaSource, ...]) -> PaidMediaSource:
    if len(sources) != 1 or sources[0].role != "product":
        raise ValueError(
            "Exact Shopify source transform requires exactly one product source and no other inputs"
        )
    return sources[0]


def _source_transform_job_id(request_id: str, product_checksum_sha256: str) -> str:
    digest = hashlib.sha256(f"{request_id}:{product_checksum_sha256}".encode()).hexdigest()[:20]
    return f"source-transform-{digest}"


def _source_preserving_video_dimensions(aspect_ratio: str, resolution: str) -> tuple[int, int]:
    try:
        scale = {"480p": 4 / 9, "720p": 2 / 3, "1080p": 1}[resolution]
    except KeyError as error:
        raise ValueError(
            "Exact Shopify video renderer does not support the selected resolution"
        ) from error
    width, height = _ratio_dimensions(aspect_ratio)
    return _even(round(width * scale)), _even(round(height * scale))


def _even(value: int) -> int:
    return value if value % 2 == 0 else value + 1


def _render_source_preserving_image(
    source_path: Path,
    width: int,
    height: int,
    file_format: str,
) -> bytes:
    with Image.open(source_path) as source:
        source.load()
        converted = source.convert("RGB")
    crop = _focus_crop_box(converted, width, height)
    rendered = converted.crop(crop).resize((width, height), Image.Resampling.LANCZOS)
    output = BytesIO()
    if file_format == "jpeg":
        rendered.save(output, format="JPEG", quality=95, subsampling=0)
    elif file_format == "webp":
        rendered.save(output, format="WEBP", quality=95, method=6)
    elif file_format == "png":
        rendered.save(output, format="PNG")
    else:
        raise ValueError("Exact Shopify image renderer supports PNG, JPEG and WebP only")
    return output.getvalue()


def _focus_crop_box(
    source: Image.Image, target_width: int, target_height: int
) -> tuple[int, int, int, int]:
    source_ratio = source.width / source.height
    target_ratio = target_width / target_height
    if source_ratio > target_ratio:
        crop_width = min(source.width, round(source.height * target_ratio))
        left = _focus_crop_origin(source, crop_width, axis="x")
        return left, 0, left + crop_width, source.height
    if source_ratio < target_ratio:
        crop_height = min(source.height, round(source.width / target_ratio))
        top = _focus_crop_origin(source, crop_height, axis="y")
        return 0, top, source.width, top + crop_height
    return 0, 0, source.width, source.height


def _focus_crop_origin(source: Image.Image, crop_length: int, *, axis: str) -> int:
    full_length = source.width if axis == "x" else source.height
    available = full_length - crop_length
    if available <= 0:
        return 0
    analysis = source.copy()
    analysis.thumbnail((256, 256), Image.Resampling.BILINEAR)
    analysis_length = analysis.width if axis == "x" else analysis.height
    analysis_crop = max(1, round(crop_length / full_length * analysis_length))
    if analysis_crop >= analysis_length:
        return available // 2
    scores = [0.0] * analysis_length
    pixels = analysis.load()
    for y in range(analysis.height):
        for x in range(analysis.width):
            red, green, blue = pixels[x, y]
            brightness = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
            saturation = (max(red, green, blue) - min(red, green, blue)) / 255
            importance = (1 - brightness) * 0.75 + saturation * 0.25
            scores[x if axis == "x" else y] += importance
    running = sum(scores[:analysis_crop])
    best_score = running
    best_start = 0
    for start in range(1, analysis_length - analysis_crop + 1):
        running += scores[start + analysis_crop - 1] - scores[start - 1]
        if running > best_score:
            best_score = running
            best_start = start
    maximum_start = analysis_length - analysis_crop
    if maximum_start <= 0:
        return available // 2
    return round(best_start / maximum_start * available)


def _render_source_preserving_video(
    source_path: Path,
    width: int,
    height: int,
    duration_seconds: int,
    timeout_seconds: int,
) -> tuple[bytes, dict[str, object]]:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("ffmpeg and ffprobe are required for exact Shopify video rendering")
    frames = duration_seconds * 24
    with tempfile.TemporaryDirectory(prefix="shopify-source-transform-") as temporary:
        directory = Path(temporary)
        still = directory / "source.png"
        output = directory / "output.mp4"
        still.write_bytes(_render_source_preserving_image(source_path, width, height, "png"))
        video_filter = (
            "zoompan="
            "z='min(zoom+0.00025,1.03)':"
            "x='iw/2-iw/zoom/2':"
            "y='ih/2-ih/zoom/2':"
            f"d={frames}:s={width}x{height}:fps=24,format=yuv420p"
        )
        result = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-loop",
                "1",
                "-framerate",
                "24",
                "-i",
                str(still),
                "-vf",
                video_filter,
                "-frames:v",
                str(frames),
                "-an",
                "-c:v",
                "libx264",
                "-crf",
                "18",
                "-movflags",
                "+faststart",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        if result.returncode != 0:
            raise RuntimeError("Exact Shopify video rendering failed")
        metadata = _probe_video(output)
        return output.read_bytes(), metadata


def _read_stored_artifact(service: ArtifactService, object_key: str) -> bytes:
    with service.storage.open(object_key) as download:
        return b"".join(iter_download(download))


def _verify_file_checksum(path: Path, checksum_sha256: str, max_bytes: int | None) -> None:
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise ValueError("Frozen product media exceeds the configured byte limit")
    if hashlib.sha256(path.read_bytes()).hexdigest() != checksum_sha256:
        raise ValueError("Frozen product media failed checksum verification")


def _image_prompt(request: PaidImageGenerationRequest) -> str:
    sources = request.sources + ((request.logo_source,) if request.logo_source else ())
    text_direction = _text_direction(request)
    logo_direction = (
        " The final supplied reference image is the approved logo asset. Render that exact logo "
        "clearly in the finished image without redesigning, replacing, or inventing it."
        if request.include_logo
        else " The image contains no logo."
    )
    product = _positions(sources, "product")
    product_identity = (
        f"The product must look exactly like product image{'s' if len(product) > 1 else ''} "
        f"{', '.join(product)}: same shape, proportions, colors, materials and visible details."
    )
    draft = next((item for item in sources if item.role == "draft"), None)
    if draft is not None:
        return (
            f"Edit image {_positions(sources, 'draft')[0]}: {request.visual_direction}. "
            "Everything else stays identical: composition, crop, lighting, props, people and "
            f"background. {product_identity}{text_direction}{logo_direction}"
        )
    scene = next((item for item in sources if item.role == "style" and item.swap_mode), None)
    if scene is not None:
        position = _positions(sources, "style")[0]
        action = (
            f"Replace the matching product in the scene with the product from image"
            f"{'s' if len(product) > 1 else ''} {', '.join(product)}."
            if scene.swap_mode == "replace"
            else f"Add the product from image{'s' if len(product) > 1 else ''} "
            f"{', '.join(product)} to the scene."
        )
        placement = f" Placement: {scene.note}." if scene.note else ""
        return (
            f"Edit the photograph in image {position}. {action}{placement} Keep the people, room, "
            "composition, camera angle, framing, lens perspective and lighting of image "
            f"{position} unchanged. {product_identity} Relight the product to match the scene, "
            "with natural contact shadows, believable scale and correct perspective. "
            f"{request.visual_direction}.{text_direction}{logo_direction}"
        )
    style = _positions(sources, "style")
    style_direction = (
        f" Image{'s' if len(style) > 1 else ''} {', '.join(style)} show the intended layout, "
        "lighting and mood: borrow the look and feel only, and leave out their product, brand, "
        "logo and text."
        if style
        else ""
    )
    return (
        f"{request.visual_direction}. A photograph in a natural, contemporary American setting. "
        f"{product_identity}{style_direction}{text_direction}{logo_direction}"
    )


def _text_direction(request: PaidImageGenerationRequest) -> str:
    copy = []
    if request.headline:
        copy.append(f'headline: "{request.headline}"')
    if request.subtext:
        copy.append(f'supporting text: "{request.subtext}"')
    if request.cta_text:
        copy.append(f'CTA: "{request.cta_text}"')
    if request.include_text:
        return (
            " Render the following approved copy directly in the finished image, exactly as "
            f"written, with legible professional typography: {'; '.join(copy)}. "
            "Add no other text."
        )
    return " The image contains no text, captions, labels, watermarks or borders."


def _positions(sources: tuple[PaidMediaSource, ...], role: str) -> list[str]:
    return [str(index) for index, item in enumerate(sources, start=1) if item.role == role]


def _reference_payload(model: ManagedImageModelConfig, encoded_sources: list[str]):
    if model.reference_encoding == "data_url":
        return encoded_sources[0] if model.reference_field == "image" else list(encoded_sources)
    if model.reference_field == "image":
        return {"image_url": encoded_sources[0]}
    if model.request_mode == "json_edit":
        # xAI's /images/edits takes typed entries: {"type": "image_url", "url": ...}.
        return [{"type": "image_url", "url": item} for item in encoded_sources]
    return [{"image_url": item} for item in encoded_sources]


def _image_model_descriptor(model: ManagedImageModelConfig) -> PaidImageModelDescriptor:
    costs = model.cost_per_output_by_setting
    if not costs and model.cost_per_output is not None:
        costs = {
            f"default:{resolution}": model.cost_per_output
            for resolution in model.supported_resolutions
        }
    return PaidImageModelDescriptor(
        model_id=model.model,
        display_name=model.display_name or model.model,
        supported_modes=model.supported_modes,
        supported_aspect_ratios=model.supported_aspect_ratios,
        supported_resolutions=model.supported_resolutions,
        supported_qualities=model.supported_qualities,
        supported_formats=model.supported_formats,
        supported_image_sizes=model.supported_image_sizes,
        supported_backgrounds=model.supported_backgrounds,
        supported_moderation=model.supported_moderation,
        supported_input_fidelities=model.supported_input_fidelities,
        supports_output_compression=model.supports_output_compression,
        max_reference_images=model.max_reference_images,
        supports_text_rendering=model.supports_text_rendering,
        supports_logo_input=model.supports_logo_input,
        cost_per_output_by_setting=tuple(sorted(costs.items())),
        input_image_cost=model.input_image_cost,
    )


def _provider_image_size(model: ManagedImageModelConfig, width: int, height: int) -> str:
    """Map the requested canvas onto a size the provider accepts, keeping the ratio."""

    requested = f"{width}x{height}"
    if not model.supported_image_sizes:
        return requested
    if requested in model.supported_image_sizes:
        return requested
    same_ratio = [
        value
        for value in model.supported_image_sizes
        if _image_size_ratio(value) == _image_size_ratio(requested)
    ]
    if not same_ratio:
        raise ValueError("Image provider has no supported size with the requested aspect ratio")
    return min(same_ratio, key=lambda value: abs(_image_size_area(value) - width * height))


def _image_size_parts(value: str) -> tuple[int, int]:
    width, _, height = value.lower().partition("x")
    return int(width), int(height)


def _image_size_ratio(value: str) -> float:
    width, height = _image_size_parts(value)
    return width / height


def _image_size_area(value: str) -> int:
    width, height = _image_size_parts(value)
    return width * height


def _video_prompt(request: PaidVideoGenerationRequest) -> str:
    audio_parts = [request.audio_direction or ""]
    if request.voice_direction:
        audio_parts.append(f"Voice: {request.voice_direction}")
    if request.music_direction:
        audio_parts.append(f"Music: {request.music_direction}")
    audio = " ".join(part for part in audio_parts if part).strip() or "Near silence."
    source_roles = _source_role_legend(request.sources)
    return (
        f"{request.visual_direction}. Continuity: {request.continuity_direction}. "
        f"Sound: {audio}. {source_roles} "
        "The product keeps the exact shape, label, color and material of its input image for "
        "the whole clip, and people keep a stable identity. One continuous shot with smooth, "
        "believable motion. Input images set the look; borrow the look of style references "
        "only, never their product, brand, logo or text. The footage is clean, with no "
        "captions, logos or overlays."
    )


def _source_role_legend(sources: tuple[PaidMediaSource, ...]) -> str:
    """Describe the exact provider input order so role semantics are not ambiguous."""

    positions: dict[str, list[str]] = {"product": [], "style": [], "logo": [], "draft": []}
    for index, source in enumerate(sources, start=1):
        positions.setdefault(source.role, []).append(str(index))
    labels = []
    if positions["product"]:
        labels.append(f"Product input positions: {', '.join(positions['product'])}")
    if positions["style"]:
        labels.append("Research/style reference input positions: " + ", ".join(positions["style"]))
    if positions["logo"]:
        labels.append(f"Approved logo input positions: {', '.join(positions['logo'])}")
    if positions["draft"]:
        labels.append(f"Image to edit input positions: {', '.join(positions['draft'])}")
    if positions.get("keyframe"):
        labels.append(
            "Opening keyframe input positions (start the clip from this exact frame): "
            + ", ".join(positions["keyframe"])
        )
    return "; ".join(labels) + "."


async def _validate_public_host(host: str, allowed_hosts: frozenset[str]) -> None:
    normalized = host.rstrip(".").lower()
    if allowed_hosts and normalized not in allowed_hosts:
        raise ValueError("Media URL host is not allowlisted")
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo, normalized, 443, type=socket.SOCK_STREAM
        )
    except socket.gaierror as error:
        raise ValueError("Media URL host could not be resolved") from error
    for address in {item[4][0] for item in addresses}:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Media URL resolves to a non-public address")


async def _bounded_response_bytes(response: httpx.Response, max_bytes: int | None) -> bytes:
    declared = response.headers.get("content-length")
    if max_bytes is not None and declared is not None and int(declared) > max_bytes:
        raise ValueError("Media response exceeds the configured byte limit")
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if max_bytes is not None and size > max_bytes:
            raise ValueError("Media response exceeds the configured byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


async def _download_public_url(
    url: str,
    *,
    allowed_hosts: tuple[str, ...],
    max_bytes: int | None,
    timeout_seconds: float,
    client: httpx.AsyncClient | None,
) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Provider output must be a credential-free HTTPS URL")
    await _validate_public_host(parsed.hostname, frozenset(host.lower() for host in allowed_hosts))
    owns_client = client is None
    timeout = httpx.Timeout(timeout_seconds, read=min(timeout_seconds, 20))
    active_client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
    try:
        try:
            async with active_client.stream("GET", url) as response:
                response.raise_for_status()
                if response.is_redirect:
                    raise ValueError("Provider output redirects are not allowed")
                return await _bounded_response_bytes(response, max_bytes)
        except httpx.ReadTimeout:
            return await _download_public_url_by_ranges(active_client, url, max_bytes)
    finally:
        if owns_client:
            await active_client.aclose()


async def _download_public_url_by_ranges(
    client: httpx.AsyncClient,
    url: str,
    max_bytes: int | None,
) -> bytes:
    chunk_size = 64 * 1024
    max_chunk_attempts = 3
    chunks: list[bytes] = []
    offset = 0
    total_size: int | None = None
    while total_size is None or offset < total_size:
        end = offset + chunk_size - 1
        for attempt in range(max_chunk_attempts):
            try:
                async with client.stream(
                    "GET",
                    url,
                    headers={
                        "Range": f"bytes={offset}-{end}",
                        "Accept-Encoding": "identity",
                        "Connection": "close",
                    },
                ) as response:
                    response.raise_for_status()
                    if response.status_code != httpx.codes.PARTIAL_CONTENT:
                        raise ValueError("Provider output does not support bounded range downloads")
                    content_range = response.headers.get("content-range", "")
                    unit, separator, value = content_range.partition(" ")
                    bounds, slash, declared_total = value.partition("/")
                    declared_start, dash, declared_end = bounds.partition("-")
                    if (
                        unit.lower() != "bytes"
                        or not separator
                        or not slash
                        or not dash
                        or not declared_start.isdigit()
                        or not declared_end.isdigit()
                        or not declared_total.isdigit()
                        or int(declared_start) != offset
                    ):
                        raise ValueError("Provider output returned an invalid byte range")
                    response_total = int(declared_total)
                    if total_size is not None and response_total != total_size:
                        raise ValueError("Provider output size changed during download")
                    total_size = response_total
                    if max_bytes is not None and total_size > max_bytes:
                        raise ValueError("Media response exceeds the configured byte limit")
                    content = await _bounded_response_bytes(response, chunk_size)
                    expected_length = int(declared_end) - int(declared_start) + 1
                    if not content or len(content) != expected_length:
                        raise ValueError("Provider output returned an incomplete byte range")
                break
            except httpx.ReadTimeout:
                if attempt + 1 == max_chunk_attempts:
                    raise
        else:  # pragma: no cover - the bounded loop always breaks or raises
            raise RuntimeError("Provider output range download did not complete")
        chunks.append(content)
        offset += len(content)
    if offset != total_size:
        raise ValueError("Provider output range download was incomplete")
    return b"".join(chunks)


def _verify_image(content: bytes) -> None:
    with Image.open(BytesIO(content)) as image:
        image.verify()


def _normalize_image(content: bytes, width: int, height: int, file_format: str) -> bytes:
    with Image.open(BytesIO(content)) as image:
        image.load()
        converted = image.convert("RGBA" if file_format in {"png", "webp"} else "RGB")
        source_ratio = converted.width / converted.height
        target_ratio = width / height
        if source_ratio > target_ratio:
            crop_width = round(converted.height * target_ratio)
            left = (converted.width - crop_width) // 2
            converted = converted.crop((left, 0, left + crop_width, converted.height))
        elif source_ratio < target_ratio:
            crop_height = round(converted.width / target_ratio)
            top = (converted.height - crop_height) // 2
            converted = converted.crop((0, top, converted.width, top + crop_height))
        converted = converted.resize((width, height), Image.Resampling.LANCZOS)
        output = BytesIO()
        converted.save(output, format={"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}[file_format])
        return output.getvalue()


_PLANNING_PREVIEW_MAX_EDGE = 1024
_PLANNING_PREVIEW_JPEG_QUALITY = 85
_REFERENCE_ENCODING_MAX_EDGE = 1536
_REFERENCE_ENCODING_JPEG_QUALITY = 90


def _bounded_jpeg(content: bytes, max_edge: int, quality: int) -> bytes:
    """Render an image into a small deterministic JPEG bounded by ``max_edge``."""

    try:
        with Image.open(BytesIO(content)) as source:
            source.load()
            converted = (
                source.convert("RGBA")
                if source.mode in {"RGBA", "LA", "P"}
                else source.convert("RGB")
            )
            if converted.mode == "RGBA":
                flattened = Image.new("RGB", converted.size, (255, 255, 255))
                flattened.paste(converted, mask=converted.getchannel("A"))
                converted = flattened
            converted.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            output = BytesIO()
            converted.save(output, format="JPEG", quality=quality)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ValueError("Managed media cannot render a bounded JPEG") from error


def _planning_preview(content: bytes) -> bytes:
    """Render frozen media into a small deterministic JPEG for planning input."""

    return _bounded_jpeg(content, _PLANNING_PREVIEW_MAX_EDGE, _PLANNING_PREVIEW_JPEG_QUALITY)


def _reference_encoding(content: bytes) -> bytes:
    """Encode a frozen source as a bounded reference for paid provider requests."""

    return _bounded_jpeg(content, _REFERENCE_ENCODING_MAX_EDGE, _REFERENCE_ENCODING_JPEG_QUALITY)


def _encoded_source_data_url(path: Path) -> str:
    encoded = _reference_encoding(path.read_bytes())
    return "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")


def _source_image_content_type(path: Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "application/octet-stream")


def _encoded_video_source_data_url(path: Path, aspect_ratio: str) -> str:
    """Preserve the requested canvas ratio for image-conditioned video models."""

    encoded = _video_reference_encoding(path.read_bytes(), aspect_ratio)
    return "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")


def _video_reference_encoding(content: bytes, aspect_ratio: str) -> bytes:
    """Render a full-bleed bounded canvas for image-conditioned video models."""

    try:
        with Image.open(BytesIO(content)) as source:
            source.load()
            converted = (
                source.convert("RGBA")
                if source.mode in {"RGBA", "LA", "P"}
                else source.convert("RGB")
            )
            if converted.mode == "RGBA":
                flattened = Image.new("RGB", converted.size, (255, 255, 255))
                flattened.paste(converted, mask=converted.getchannel("A"))
                converted = flattened
            width, height = _ratio_dimensions(aspect_ratio)
            scale = min(1, _REFERENCE_ENCODING_MAX_EDGE / max(width, height))
            canvas_size = (round(width * scale), round(height * scale))
            canvas = ImageOps.fit(
                converted,
                canvas_size,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            output = BytesIO()
            canvas.save(output, format="JPEG", quality=_REFERENCE_ENCODING_JPEG_QUALITY)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ValueError("Managed media cannot render a video reference canvas") from error


def _image_content_type(file_format: str) -> str:
    return {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}[file_format]


def _image_extension(content_type: str) -> str:
    return {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[content_type]


def _poll_delay(response: httpx.Response, fallback: float) -> float:
    try:
        return max(0.1, min(float(response.headers.get("retry-after", fallback)), 60.0))
    except ValueError:
        return fallback


def _ratio_dimensions(aspect_ratio: str) -> tuple[int, int]:
    return {
        "1:1": (1080, 1080),
        "4:5": (1080, 1350),
        "9:16": (1080, 1920),
        "16:9": (1920, 1080),
        "4:3": (1440, 1080),
        "3:4": (1080, 1440),
        "3:2": (1620, 1080),
        "2:3": (1080, 1620),
    }[aspect_ratio]


async def _still_frame(
    sink: ManagedMediaArtifactSink, clip: PaidMediaArtifact, at_seconds: float, request_id: str
) -> PaidMediaArtifact:
    """Save the clip's frame at the cut point so the next scene can start from it."""

    started = monotonic()
    content = await asyncio.to_thread(
        _extract_frame, sink.local_path(clip.artifact_ref), at_seconds
    )
    stored = await sink.write(
        content, request_id=request_id, filename="frame.png", owner_id=request_id
    )
    with Image.open(BytesIO(content)) as image:
        width, height = image.size
    return PaidMediaArtifact(
        artifact_ref=stored.artifact_ref,
        checksum_sha256=stored.checksum_sha256,
        content_type="image/png",
        provider_id=clip.provider_id,
        provider_job_id=f"frame-{clip.provider_job_id}",
        model="ffmpeg",
        model_revision=None,
        elapsed_seconds=monotonic() - started,
        cost=Decimal("0"),
        width=width,
        height=height,
    )


def _extract_frame(path: Path, at_seconds: float) -> bytes:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to continue a video from its last frame")
    with tempfile.TemporaryDirectory(prefix="creative-frame-") as temporary:
        output = Path(temporary) / "frame.png"
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{max(at_seconds, 0):.3f}", "-i", str(path)]
            + ["-frames:v", "1", str(output)],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if result.returncode != 0 or not output.exists():
            # Seeking past the end yields nothing; fall back to the clip's final frame.
            result = subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-sseof", "-0.1", "-i", str(path)]
                + ["-frames:v", "1", "-update", "1", str(output)],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
        if result.returncode != 0 or not output.exists():
            raise RuntimeError("Could not extract the video frame to continue from")
        return output.read_bytes()


def _probe_video(path: Path) -> dict[str, object]:
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe is required for managed video production")
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("Managed video is not a valid decodable MP4")
    payload = json.loads(result.stdout)
    video = next(item for item in payload["streams"] if item.get("codec_type") == "video")
    return {
        "width": int(video["width"]),
        "height": int(video["height"]),
        "duration_seconds": float(payload["format"]["duration"]),
        "has_audio_stream": any(item.get("codec_type") == "audio" for item in payload["streams"]),
    }


def _assemble_video(
    paths: tuple[Path, ...],
    durations: tuple[int, ...],
    width: int,
    height: int,
    expects_audio: bool,
    timeout_seconds: int,
) -> tuple[bytes, dict[str, object]]:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("ffmpeg and ffprobe are required for managed video assembly")
    with tempfile.TemporaryDirectory(prefix="creative-assembly-") as temporary:
        output = Path(temporary) / "final.mp4"
        command = ["ffmpeg", "-v", "error", "-y"]
        for path in paths:
            command.extend(["-i", str(path)])
        filters: list[str] = []
        concat: list[str] = []
        for index, duration in enumerate(durations):
            filters.append(
                f"[{index}:v]trim=duration={duration},setpts=PTS-STARTPTS,"
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=24[v{index}]"
            )
            if expects_audio:
                metadata = _probe_video(paths[index])
                if metadata["has_audio_stream"]:
                    filters.append(
                        f"[{index}:a]atrim=duration={duration},asetpts=PTS-STARTPTS,"
                        f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]"
                    )
                else:
                    filters.append(
                        f"anullsrc=r=48000:cl=stereo,atrim=duration={duration},"
                        f"asetpts=PTS-STARTPTS[a{index}]"
                    )
                concat.append(f"[v{index}][a{index}]")
            else:
                concat.append(f"[v{index}]")
        if expects_audio:
            filters.append("".join(concat) + f"concat=n={len(paths)}:v=1:a=1[vout][aout]")
        else:
            filters.append("".join(concat) + f"concat=n={len(paths)}:v=1:a=0[vout]")
        command.extend(["-filter_complex", ";".join(filters), "-map", "[vout]"])
        if expects_audio:
            command.extend(["-map", "[aout]"])
        command.extend(
            [
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        if result.returncode != 0:
            raise RuntimeError("Managed video assembly failed")
        metadata = _probe_video(output)
        return output.read_bytes(), metadata


__all__ = [
    "ImmutableProductSourceResolver",
    "ManagedMediaArtifactSink",
    "SourcePreservingImageProvider",
    "SourcePreservingVideoProvider",
    "NineRouterImageProvider",
    "NineRouterVideoProvider",
]
