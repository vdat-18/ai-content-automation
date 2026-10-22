"""ComfyUI adapter for the pinned LTX-2.5 text-to-video API export."""

import asyncio
import hashlib
import json
import secrets
from copy import deepcopy
from pathlib import Path
from time import monotonic
from typing import Literal

import httpx
from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError

from ..config.videos import VideoBackendConfig
from ..ports.videos import GeneratedVideo, VideoGenerationError, VideoGenerationRequest


class _WorkflowNode(BaseModel):
    class_type: str
    inputs: dict[str, JsonValue]


class _SubmitResponse(BaseModel):
    prompt_id: str = Field(pattern=r"^[A-Za-z0-9-]+$")


class _OutputVideo(BaseModel):
    filename: str = Field(min_length=1)
    subfolder: str = ""
    type: Literal["output"] = "output"


class _NodeOutput(BaseModel):
    videos: list[_OutputVideo] = Field(default_factory=list)
    images: list[_OutputVideo] = Field(default_factory=list)


class _JobResponse(BaseModel):
    status: str = Field(min_length=1)
    outputs: dict[str, _NodeOutput] = Field(default_factory=dict)


_WORKFLOW = TypeAdapter(dict[str, _WorkflowNode])
_NODES = {
    "75": "SaveVideo",
    "405:376": "PrimitiveStringMultiline",
    "405:383": "PrimitiveBoolean",
    "405:362": "PrimitiveInt",
    "405:361": "PrimitiveInt",
    "409": "ResolutionSelector",
    "405:339": "RandomNoise",
    "405:338": "RandomNoise",
    "405:384": "UNETLoader",
}


def _load_workflow(path: Path, model: str) -> dict[str, _WorkflowNode]:
    try:
        workflow = _WORKFLOW.validate_json(path.read_text(encoding="utf-8"))
        if any(
            workflow.get(node_id) is None or workflow[node_id].class_type != node_type
            for node_id, node_type in _NODES.items()
        ):
            raise ValueError("Required LTX-2.5 nodes are missing")
        if workflow["75"].inputs.get("video") != ["405:370", 0]:
            raise ValueError("SaveVideo is not connected to the expected final video")
        if workflow["405:384"].inputs.get("unet_name") != model:
            raise ValueError("LTX-2.5 checkpoint does not match the config")
        return workflow
    except (OSError, ValueError, ValidationError) as exc:
        raise VideoGenerationError(
            "ComfyUI LTX-2.5 API workflow is missing or does not match the expected export"
        ) from exc


class ComfyUIVideoBackend:
    """Submit one LTX-2.5 T2V job without retrying an ambiguous enqueue."""

    def __init__(
        self,
        config: VideoBackendConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if config.workflow_path is None or config.megapixels is None:
            raise VideoGenerationError("ComfyUI video workflow configuration is incomplete")
        self._config = config
        self._transport = transport
        self._workflow = _load_workflow(config.workflow_path, config.model)
        self._workflow_hash = hashlib.sha256(
            json.dumps(
                {node_id: node.model_dump() for node_id, node in self._workflow.items()},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    async def generate(self, request: VideoGenerationRequest) -> GeneratedVideo:
        self._validate_request(request)
        seed = request.seed if request.seed is not None else secrets.randbits(63)
        if not 0 <= seed < 2**64:
            raise VideoGenerationError("Video seed must be between 0 and 2^64 - 1")
        workflow = deepcopy(self._workflow)
        workflow["405:376"].inputs["value"] = request.prompt
        workflow["405:383"].inputs["value"] = self._config.prompt_enhance
        workflow["405:362"].inputs["value"] = request.seconds
        workflow["409"].inputs["megapixels"] = self._config.megapixels
        for node_id in ("405:339", "405:338"):
            workflow[node_id].inputs["noise_seed"] = seed
        graph = {node_id: node.model_dump() for node_id, node in workflow.items()}

        started = monotonic()
        submitted = False
        job_id: str | None = None
        try:
            async with httpx.AsyncClient(
                base_url=self._config.base_url.rstrip("/"),
                timeout=self._config.request_timeout_seconds,
                transport=self._transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with asyncio.timeout(self._config.generation_timeout_seconds):
                    submitted = True
                    response = await client.post("/api/prompt", json={"prompt": graph})
                    response.raise_for_status()
                    job_id = _SubmitResponse.model_validate_json(response.content).prompt_id
                    job = await self._wait(client, job_id)
                    output = job.outputs.get("75", _NodeOutput())
                    videos = output.videos + output.images
                    if len(videos) != 1 or Path(videos[0].filename).suffix.lower() != ".mp4":
                        raise VideoGenerationError(
                            "ComfyUI final SaveVideo node must return exactly one MP4"
                        )
                    content = await self._download(client, videos[0])
        except (
            TimeoutError,
            httpx.HTTPError,
            ValidationError,
            ValueError,
            VideoGenerationError,
        ) as exc:
            if isinstance(exc, httpx.HTTPStatusError):
                reason = f"HTTP {exc.response.status_code}"
            elif isinstance(exc, ValidationError):
                reason = "invalid response schema"
            elif isinstance(exc, VideoGenerationError):
                reason = str(exc)
            else:
                reason = type(exc).__name__
            status = (
                "unknown_check_service"
                if submitted and job_id is None
                else ("submitted" if submitted else "not_submitted")
            )
            raise VideoGenerationError(
                f"ComfyUI video {reason}; job={job_id or 'unknown'}; submission={status}"
            ) from exc

        return GeneratedVideo(
            content=content,
            model=self._config.model,
            model_revision=self._config.model_revision,
            runtime_version=self._config.runtime_version,
            service_job_id=job_id,
            prompt=request.prompt,
            seconds=request.seconds,
            size=request.size,
            quality=self._config.default_quality,
            elapsed_seconds=monotonic() - started,
            seed=seed,
            workflow_hash=self._workflow_hash,
        )

    def _validate_request(self, request: VideoGenerationRequest) -> None:
        if request.mode != "text_to_video" or request.input_path is not None:
            raise VideoGenerationError("ComfyUI LTX-2.5 workflow supports text_to_video only")
        if not request.prompt.strip():
            raise VideoGenerationError("Video prompt must not be empty")
        if request.seconds not in self._config.supported_seconds:
            raise VideoGenerationError("Video duration is not supported by this workflow")
        if request.size not in self._config.supported_sizes:
            raise VideoGenerationError("Video size is not supported by this workflow")
        if request.quality not in {None, self._config.default_quality}:
            raise VideoGenerationError("Video quality is fixed by the ComfyUI workflow")

    async def _wait(self, client: httpx.AsyncClient, job_id: str) -> _JobResponse:
        while True:
            response = await client.get(f"/api/jobs/{job_id}")
            response.raise_for_status()
            job = _JobResponse.model_validate_json(response.content)
            if job.status == "completed":
                return job
            if job.status in {"failed", "cancelled", "error"}:
                raise VideoGenerationError(f"job ended with status {job.status}")
            if job.status not in {"pending", "running", "queued", "in_progress"}:
                raise VideoGenerationError("job has an unknown status")
            await asyncio.sleep(self._config.poll_interval_seconds)

    async def _download(self, client: httpx.AsyncClient, video: _OutputVideo) -> bytes:
        content = bytearray()
        async with client.stream(
            "GET",
            "/api/view",
            params={"filename": video.filename, "subfolder": video.subfolder, "type": video.type},
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > self._config.max_video_bytes:
                    raise VideoGenerationError("generated video exceeds configured byte limit")
        result = bytes(content)
        if len(result) < 12 or result[4:8] != b"ftyp":
            raise VideoGenerationError("ComfyUI output is not a valid MP4 container")
        return result


__all__ = ["ComfyUIVideoBackend"]
