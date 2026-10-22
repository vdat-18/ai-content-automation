"""Provider-neutral adapter for an asynchronous OpenAI-style Videos API."""

import asyncio
from time import monotonic
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config.videos import VideoBackendConfig
from ..ports.videos import GeneratedVideo, VideoGenerationError, VideoGenerationRequest


class _VideoJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    status: str = Field(min_length=1)


class OpenAICompatibleVideoBackend:
    """Submit, poll and download one bounded clip without ambiguous retries."""

    def __init__(
        self,
        config: VideoBackendConfig,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        api_key: str | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._api_key = api_key

    async def generate(self, request: VideoGenerationRequest) -> GeneratedVideo:
        self._validate_request(request)
        if self._config.api_key_env and not self._api_key:
            raise VideoGenerationError(
                "Configured video API credential environment variable is missing"
            )
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        quality = request.quality or self._config.default_quality
        started = monotonic()
        try:
            async with httpx.AsyncClient(
                base_url=f"{self._config.base_url.rstrip('/')}/",
                headers=headers,
                timeout=httpx.Timeout(
                    self._config.request_timeout_seconds,
                    connect=self._config.request_timeout_seconds,
                ),
                transport=self._transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(
                    "videos",
                    json={
                        "model": self._config.model,
                        "prompt": request.prompt,
                        "seconds": request.seconds,
                        "size": request.size,
                        "quality": quality,
                    },
                )
                response.raise_for_status()
                job = _VideoJob.model_validate_json(response.content)
                async with asyncio.timeout(self._config.generation_timeout_seconds):
                    job = await self._wait_for_completion(client, job)
                    content = await self._download(client, job.id)
        except TimeoutError as exc:
            raise VideoGenerationError("Video API generation timed out") from exc
        except (httpx.HTTPError, ValidationError, VideoGenerationError) as exc:
            if isinstance(exc, VideoGenerationError):
                reason = str(exc)
            elif isinstance(exc, httpx.HTTPStatusError):
                reason = f"HTTP {exc.response.status_code}"
            else:
                reason = type(exc).__name__
            raise VideoGenerationError(f"Video API {reason}") from exc

        return GeneratedVideo(
            content=content,
            model=self._config.model,
            model_revision=self._config.model_revision,
            runtime_version=self._config.runtime_version,
            service_job_id=job.id,
            prompt=request.prompt,
            seconds=request.seconds,
            size=request.size,
            quality=quality,
            elapsed_seconds=monotonic() - started,
        )

    def _validate_request(self, request: VideoGenerationRequest) -> None:
        if request.mode != "text_to_video":
            raise VideoGenerationError("Video mode is not supported by this provider adapter")
        if request.input_path is not None:
            raise VideoGenerationError("Text-to-video does not accept input media")
        if not request.prompt.strip():
            raise VideoGenerationError("Video prompt must not be empty")
        if request.seconds not in self._config.supported_seconds:
            raise VideoGenerationError("Video duration is not supported by this model config")
        if request.size not in self._config.supported_sizes:
            raise VideoGenerationError("Video size is not supported by this model config")

    async def _wait_for_completion(self, client: httpx.AsyncClient, job: _VideoJob) -> _VideoJob:
        completed = {"completed", "succeeded"}
        failed = {"failed", "canceled", "cancelled"}
        while job.status.lower() not in completed:
            if job.status.lower() in failed:
                raise VideoGenerationError(f"generation ended with status {job.status.lower()}")
            await asyncio.sleep(self._config.poll_interval_seconds)
            response = await client.get(f"videos/{quote(job.id, safe='')}")
            response.raise_for_status()
            job = _VideoJob.model_validate_json(response.content)
        return job

    async def _download(self, client: httpx.AsyncClient, job_id: str) -> bytes:
        async with client.stream("GET", f"videos/{quote(job_id, safe='')}/content") as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0]
            if content_type and content_type not in {"video/mp4", "application/octet-stream"}:
                raise VideoGenerationError("provider returned an unsupported video content type")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > self._config.max_video_bytes:
                    raise VideoGenerationError("generated video exceeds configured byte limit")
        content = bytes(body)
        if len(content) < 12 or content[4:8] != b"ftyp":
            raise VideoGenerationError("provider output is not a valid MP4 container")
        return content


__all__ = ["OpenAICompatibleVideoBackend"]
