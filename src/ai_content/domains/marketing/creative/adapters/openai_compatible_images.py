"""OpenAI-compatible Images API adapter for product-conditioned generation."""

import base64
import binascii
import hashlib
import json
from time import monotonic

import httpx
from pydantic import BaseModel, Field, ValidationError

from ..config.images import ImageBackendConfig, render_image_prompt
from ..ports.images import GeneratedImage, ImageGenerationError, ImageGenerationRequest
from .image_files import inspect_image, read_local_image


class _ImageData(BaseModel):
    b64_json: str = Field(min_length=1)


class _ImagesResponse(BaseModel):
    data: list[_ImageData] = Field(min_length=1, max_length=1)


class OpenAICompatibleImageBackend:
    """Call one OpenAI-compatible ``images/edits`` endpoint without retrying."""

    def __init__(
        self,
        config: ImageBackendConfig,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        api_key: str | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._api_key = api_key
        workflow = {
            "backend": config.backend,
            "base_url": config.base_url,
            "endpoint": "images/edits",
            "model": config.model,
            "model_revision": config.model_revision,
            "prompt_template": config.prompt_template,
            "response_encoding": "base64",
            "runtime_version": config.runtime_version,
        }
        serialized = json.dumps(workflow, sort_keys=True, separators=(",", ":"))
        self._workflow_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        if request.generation_target == "background":
            raise ImageGenerationError(
                "This image backend cannot generate a verified background-only artifact",
                code="background_generation_unsupported",
            )
        headers = {}
        if self._config.api_key_env:
            if not self._api_key:
                raise ImageGenerationError(
                    "Configured image API credential environment variable is missing",
                    code="credentials_missing",
                )
            headers["Authorization"] = f"Bearer {self._api_key}"

        start = monotonic()
        prompt = render_image_prompt(self._config, request.input, request.revision)
        spec = request.input.output_spec
        requested_format = spec.file_format.lower()
        if requested_format not in {"jpg", "jpeg", "png"}:
            raise ImageGenerationError(
                "Image pilot output format must be PNG or JPEG",
                code="unsupported_output_format",
            )
        output_format = "jpeg" if requested_format in {"jpg", "jpeg"} else "png"
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        for role, assets in (
            ("product", request.input.product_assets),
            ("reference", request.input.reference_assets),
        ):
            for index, asset in enumerate(assets):
                content = read_local_image(asset.url, self._config.max_image_bytes)
                _, _, file_format = inspect_image(content)
                files.append(
                    (
                        "image",
                        (f"{role}_{index}.{file_format}", content, f"image/{file_format}"),
                    )
                )
        if request.revision is not None:
            if request.revision_image_ref is None:
                raise ImageGenerationError(
                    "Revision requires the previous image version",
                    code="revision_source_missing",
                )
            content = read_local_image(request.revision_image_ref, self._config.max_image_bytes)
            _, _, file_format = inspect_image(content)
            files.append(
                (
                    "image",
                    (f"revision_source.{file_format}", content, f"image/{file_format}"),
                )
            )

        try:
            async with httpx.AsyncClient(
                base_url=f"{self._config.base_url.rstrip('/')}/",
                headers=headers,
                timeout=httpx.Timeout(
                    self._config.generation_timeout_seconds,
                    connect=self._config.request_timeout_seconds,
                ),
                transport=self._transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "POST",
                    "images/edits",
                    data={
                        "model": self._config.model,
                        "prompt": prompt,
                        "n": "1",
                        "output_format": output_format,
                        "size": f"{spec.width}x{spec.height}",
                    },
                    files=files,
                ) as response:
                    response.raise_for_status()
                    body = bytearray()
                    max_response_bytes = 4 * ((self._config.max_image_bytes + 2) // 3) + 65_536
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_response_bytes:
                            raise ImageGenerationError(
                                "Image API response exceeds configured byte limit"
                            )
                    parsed = _ImagesResponse.model_validate_json(body)
                encoded = parsed.data[0].b64_json
                max_encoded_bytes = 4 * ((self._config.max_image_bytes + 2) // 3)
                if len(encoded) > max_encoded_bytes:
                    raise ImageGenerationError("Generated image exceeds configured byte limit")
                content = base64.b64decode(encoded, validate=True)
                if len(content) > self._config.max_image_bytes:
                    raise ImageGenerationError("Generated image exceeds configured byte limit")
                inspect_image(content)
        except (
            httpx.HTTPError,
            ValidationError,
            ValueError,
            binascii.Error,
            ImageGenerationError,
        ) as exc:
            reason = str(exc) if isinstance(exc, ImageGenerationError) else type(exc).__name__
            if isinstance(exc, httpx.HTTPStatusError):
                reason = f"HTTP {exc.response.status_code}"
            if isinstance(exc, ImageGenerationError):
                code = exc.code
            elif isinstance(exc, httpx.TimeoutException):
                code = "provider_timeout"
            elif isinstance(exc, httpx.HTTPStatusError):
                code = f"provider_http_{exc.response.status_code // 100}xx"
            elif isinstance(exc, ValidationError):
                code = "invalid_provider_schema"
            elif isinstance(exc, (binascii.Error, ValueError)):
                code = "invalid_provider_response"
            else:
                code = "invalid_generated_image"
            raise ImageGenerationError(f"Image API {reason}", code=code) from exc

        execution = {
            "endpoint": "images/edits",
            "input_count": len(files),
            "revision_of": (request.revision.previous_version_ref if request.revision else None),
            "model": self._config.model,
            "output_format": output_format,
            "response_encoding": "base64",
            "size": f"{spec.width}x{spec.height}",
        }
        return GeneratedImage(
            content=content,
            model=self._config.model,
            model_revision=self._config.model_revision,
            runtime_version=self._config.runtime_version,
            workflow_hash=self._workflow_hash,
            prompt=prompt,
            seed=request.seed,
            seed_applied=False,
            elapsed_seconds=monotonic() - start,
            service_job_id=response.headers.get("x-request-id"),
            execution_graph=json.dumps(execution, sort_keys=True),
        )
