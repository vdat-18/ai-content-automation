"""ComfyUI API adapter for pinned FLUX.2 Dev image-edit workflows."""

import asyncio
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from time import monotonic
from typing import Literal

import httpx
from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError

from ..config.images import ImageBackendConfig, render_image_prompt
from ..ports.images import GeneratedImage, ImageGenerationError, ImageGenerationRequest
from .image_files import inspect_image, read_local_image


class _WorkflowNode(BaseModel):
    class_type: str
    inputs: dict[str, JsonValue]


class _UploadResponse(BaseModel):
    name: str = Field(min_length=1)


class _SubmitResponse(BaseModel):
    prompt_id: str = Field(pattern=r"^[A-Za-z0-9-]+$")


class _OutputImage(BaseModel):
    filename: str = Field(min_length=1)
    subfolder: str = ""
    type: Literal["output"] = "output"


class _NodeOutput(BaseModel):
    images: list[_OutputImage] = Field(default_factory=list)


class _JobResponse(BaseModel):
    status: str = Field(min_length=1)
    outputs: dict[str, _NodeOutput] = Field(default_factory=dict)


_WORKFLOW = TypeAdapter(dict[str, _WorkflowNode])
_SINGLE_NODES = {
    "140": "LoadImage",
    "139:123": "CLIPTextEncode",
    "139:125": "RandomNoise",
    "139:135": "GetImageSize",
    "139:134": "EmptyFlux2LatentImage",
    "139:118": "Flux2Scheduler",
    "141": "SaveImage",
    "139:129": "UNETLoader",
}
_DOUBLE_NODES = {
    "46": "LoadImage",
    "42": "LoadImage",
    "6": "CLIPTextEncode",
    "25": "RandomNoise",
    "45": "ImageScaleToTotalPixels",
    "41": "ImageScaleToTotalPixels",
    "47": "EmptyFlux2LatentImage",
    "48": "Flux2Scheduler",
    "9": "SaveImage",
    "12": "UNETLoader",
}


def _generation_dimension(value: int) -> int:
    """Round up so FLUX does not return a canvas smaller than delivery."""
    return ((value + 15) // 16) * 16


def _load_workflow(path: Path, model: str, *, two_images: bool) -> dict[str, _WorkflowNode]:
    try:
        workflow = _WORKFLOW.validate_json(path.read_text(encoding="utf-8"))
        expected = _DOUBLE_NODES if two_images else _SINGLE_NODES
        if any(
            workflow.get(node_id) is None or workflow[node_id].class_type != node_type
            for node_id, node_type in expected.items()
        ):
            raise ValueError("Required FLUX.2 Dev nodes are missing")
        links = (
            (
                ("45", "image", ["46", 0]),
                ("41", "image", ["42", 0]),
                ("9", "images", ["8", 0]),
            )
            if two_images
            else (("139:135", "image", ["140", 0]), ("141", "images", ["139:126", 0]))
        )
        if any(workflow[node_id].inputs.get(field) != value for node_id, field, value in links):
            raise ValueError("FLUX.2 Dev image or output links do not match")
        model_node = "12" if two_images else "139:129"
        if workflow[model_node].inputs.get("unet_name") != model:
            raise ValueError("FLUX.2 Dev checkpoint does not match the config")
        return workflow
    except (OSError, ValueError, ValidationError) as exc:
        raise ImageGenerationError(
            "ComfyUI API workflow is missing or does not match the expected export",
            code="invalid_workflow",
        ) from exc


def _load_background_workflow(
    path: Path, model: str
) -> tuple[dict[str, _WorkflowNode], dict[str, str]]:
    try:
        workflow = _WORKFLOW.validate_json(path.read_text(encoding="utf-8"))
        required = {
            "prompt": "CLIPTextEncode",
            "seed": "RandomNoise",
            "latent": "EmptyFlux2LatentImage",
            "scheduler": "Flux2Scheduler",
            "save": "SaveImage",
            "model": "UNETLoader",
        }
        nodes: dict[str, str] = {}
        for role, class_type in required.items():
            matches = [
                node_id for node_id, node in workflow.items() if node.class_type == class_type
            ]
            if len(matches) != 1:
                raise ValueError(f"Background workflow needs one {class_type} node")
            nodes[role] = matches[0]
        if workflow[nodes["model"]].inputs.get("unet_name") != model:
            raise ValueError("FLUX.2 Dev checkpoint does not match the config")
        save_images = workflow[nodes["save"]].inputs.get("images")
        if not isinstance(save_images, list) or len(save_images) != 2:
            raise ValueError("Background SaveImage output link is invalid")
        reachable = {nodes["save"]}
        pending = [nodes["save"]]
        while pending:
            node_id = pending.pop()
            for value in workflow[node_id].inputs.values():
                if (
                    isinstance(value, list)
                    and len(value) == 2
                    and isinstance(value[0], str)
                    and value[0] in workflow
                    and value[0] not in reachable
                ):
                    reachable.add(value[0])
                    pending.append(value[0])
        if not set(nodes.values()).issubset(reachable):
            raise ValueError("Background workflow contains disconnected required nodes")
        return workflow, nodes
    except (OSError, ValueError, ValidationError) as exc:
        raise ImageGenerationError(
            "ComfyUI background workflow is missing or does not match the expected export",
            code="invalid_workflow",
        ) from exc


class ComfyUIBackend:
    """Submit one image to a pinned local ComfyUI workflow without retrying enqueue."""

    def __init__(
        self,
        config: ImageBackendConfig,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        if config.one_image_workflow_path is None or config.two_image_workflow_path is None:
            raise ImageGenerationError(
                "ComfyUI workflow paths are required", code="invalid_workflow"
            )
        self._workflows = {
            1: _load_workflow(config.one_image_workflow_path, config.model, two_images=False),
            2: _load_workflow(config.two_image_workflow_path, config.model, two_images=True),
        }
        self._background_nodes: dict[str, str] | None = None
        if config.background_workflow_path is not None:
            background, self._background_nodes = _load_background_workflow(
                config.background_workflow_path, config.model
            )
            self._workflows["background"] = background
        self._hashes = {
            count: hashlib.sha256(
                json.dumps(
                    {node_id: node.model_dump() for node_id, node in workflow.items()},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            for count, workflow in self._workflows.items()
        }

    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        background = request.generation_target == "background"
        if background:
            if self._background_nodes is None or "background" not in self._workflows:
                raise ImageGenerationError(
                    "ComfyUI background workflow is not configured", code="invalid_workflow"
                )
            sources: list[tuple[str, str]] = []
            workflow_key: int | str = "background"
            nodes = self._background_nodes
            prompt_node = nodes["prompt"]
            seed_node = nodes["seed"]
            latent_node = nodes["latent"]
            scheduler_node = nodes["scheduler"]
            save_node = nodes["save"]
        else:
            sources = self._sources(request)
            workflow_key = len(sources)
            prompt_node = "6" if workflow_key == 2 else "139:123"
            seed_node = "25" if workflow_key == 2 else "139:125"
            latent_node = "47" if workflow_key == 2 else "139:134"
            scheduler_node = "48" if workflow_key == 2 else "139:118"
            save_node = "9" if workflow_key == 2 else "141"
        workflow = deepcopy(self._workflows[workflow_key])
        prompt = render_image_prompt(
            self._config,
            request.input,
            request.revision,
            generation_target=request.generation_target,
        )
        if request.revision is not None and not background:
            prompt += "\nImage 1 is the original product; image 2 is the previous visual to revise."
        elif len(sources) == 2:
            second_role = (
                "reference" if sources[1][0].startswith("reference_") else "second product"
            )
            prompt += f"\nImage 1 is the product; image 2 is the {second_role}."
        spec = request.input.output_spec
        generation_width = _generation_dimension(spec.width)
        generation_height = _generation_dimension(spec.height)
        workflow[prompt_node].inputs["text"] = prompt
        workflow[seed_node].inputs["noise_seed"] = request.seed
        for node_id in (latent_node, scheduler_node):
            workflow[node_id].inputs["width"] = generation_width
            workflow[node_id].inputs["height"] = generation_height
        for node_id in ("45", "41") if workflow_key == 2 else ():
            workflow[node_id].inputs["megapixels"] = min(
                4.0, max(1.0, spec.width * spec.height / 1_000_000)
            )

        start = monotonic()
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
                    # The pinned Dev edit graph expects the original product first.
                    ordered_sources = sources[::-1] if request.revision is not None else sources
                    load_nodes = ("46", "42") if workflow_key == 2 else ("140",)
                    for index, (role, source) in enumerate(ordered_sources):
                        node_id = load_nodes[index]
                        workflow[node_id].inputs["image"] = await self._upload(client, role, source)
                    graph = {node_id: node.model_dump() for node_id, node in workflow.items()}
                    submitted = True
                    response = await client.post("/api/prompt", json={"prompt": graph})
                    response.raise_for_status()
                    job_id = _SubmitResponse.model_validate_json(response.content).prompt_id
                    job = await self._wait(client, job_id)
                    images = job.outputs.get(save_node, _NodeOutput()).images
                    if len(images) != 1:
                        raise ImageGenerationError(
                            "ComfyUI final SaveImage node must return exactly one image",
                            code="invalid_provider_response",
                        )
                    image = images[0]
                    content = await self._download(client, image)
                    inspect_image(content)
            return GeneratedImage(
                content=content,
                model=self._config.model,
                model_revision=self._config.model_revision,
                runtime_version=self._config.runtime_version,
                workflow_hash=self._hashes[workflow_key],
                prompt=prompt,
                seed=request.seed,
                elapsed_seconds=monotonic() - start,
                service_job_id=job_id,
                execution_graph=json.dumps(graph, ensure_ascii=False, sort_keys=True),
            )
        except (
            TimeoutError,
            httpx.HTTPError,
            ValidationError,
            ValueError,
            ImageGenerationError,
        ) as exc:
            if isinstance(exc, ImageGenerationError):
                reason, code = str(exc), exc.code
            elif isinstance(exc, httpx.HTTPStatusError):
                reason, code = f"HTTP {exc.response.status_code}", "provider_http_error"
            elif isinstance(exc, TimeoutError | httpx.TimeoutException):
                reason, code = type(exc).__name__, "provider_timeout"
            elif isinstance(exc, ValidationError):
                reason, code = "invalid response schema", "invalid_provider_response"
            else:
                reason, code = type(exc).__name__, "provider_error"
            status = (
                "unknown_check_service"
                if submitted and job_id is None
                else ("submitted" if submitted else "not_submitted")
            )
            raise ImageGenerationError(
                f"ComfyUI {reason}; job={job_id or 'unknown'}; submission={status}", code=code
            ) from exc

    @staticmethod
    def _sources(request: ImageGenerationRequest) -> list[tuple[str, str]]:
        products = request.input.product_assets
        references = request.input.reference_assets
        if request.revision is not None:
            if request.revision_image_ref is None:
                raise ImageGenerationError(
                    "Revision requires the previous image version", code="revision_source_missing"
                )
            if len(products) != 1 or references:
                raise ImageGenerationError(
                    "ComfyUI revision supports one original product and the previous visual",
                    code="unsupported_input_count",
                )
            return [("revision_source", request.revision_image_ref), ("product_0", products[0].url)]
        sources = [(f"product_{index}", asset.url) for index, asset in enumerate(products)]
        sources.extend((f"reference_{index}", asset.url) for index, asset in enumerate(references))
        if len(sources) not in {1, 2}:
            raise ImageGenerationError(
                "ComfyUI backend supports one or two input images", code="unsupported_input_count"
            )
        return sources

    async def _upload(self, client: httpx.AsyncClient, role: str, source: str) -> str:
        content = read_local_image(source, self._config.max_image_bytes)
        _, _, image_format = inspect_image(content)
        response = await client.post(
            "/upload/image",
            files={"image": (f"{role}.{image_format}", content, f"image/{image_format}")},
            data={"type": "input", "overwrite": "false"},
        )
        response.raise_for_status()
        return _UploadResponse.model_validate_json(response.content).name

    async def _wait(self, client: httpx.AsyncClient, job_id: str) -> _JobResponse:
        while True:
            response = await client.get(f"/api/jobs/{job_id}")
            response.raise_for_status()
            job = _JobResponse.model_validate_json(response.content)
            if job.status == "completed":
                return job
            if job.status in {"failed", "cancelled", "error"}:
                raise ImageGenerationError(
                    f"ComfyUI job ended with status {job.status}", code="provider_job_failed"
                )
            if job.status not in {"pending", "running", "queued", "in_progress"}:
                raise ImageGenerationError(
                    "ComfyUI job has an unknown status", code="invalid_provider_response"
                )
            await asyncio.sleep(self._config.poll_interval_seconds)

    async def _download(self, client: httpx.AsyncClient, image: _OutputImage) -> bytes:
        content = bytearray()
        async with client.stream(
            "GET",
            "/api/view",
            params={"filename": image.filename, "subfolder": image.subfolder, "type": image.type},
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > self._config.max_image_bytes:
                    raise ImageGenerationError(
                        "ComfyUI image exceeds configured byte limit", code="image_too_large"
                    )
        return bytes(content)
