"""InvokeAI executable-graph API. One request enqueues exactly one output.

API reference: https://invoke.ai/development/guides/workflow-api/
Graph placeholders bind whole JSON values, never interpolated JSON strings.
"""

import asyncio
import hashlib
import json
import re
from time import monotonic
from typing import Literal
from urllib.parse import quote
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field, JsonValue, ValidationError

from ..config.images import ImageBackendConfig, render_image_prompt
from ..ports.images import GeneratedImage, ImageGenerationError, ImageGenerationRequest
from .image_files import inspect_image, read_local_image


class ImageReference(BaseModel):
    image_name: str = Field(min_length=1)


class ExecutableGraph(BaseModel):
    id: str
    nodes: dict[str, dict[str, JsonValue]]
    edges: list[dict[str, JsonValue]]


def graph_placeholders(value: JsonValue) -> set[str]:
    if isinstance(value, str) and ("{{" in value or "}}" in value):
        match = re.fullmatch(r"\{\{([a-z0-9_]+)\}\}", value)
        if match is None:
            raise ImageGenerationError("Graph placeholders must occupy a whole JSON value")
        return {match.group(1)}
    children = (
        value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    )
    return {key for child in children for key in graph_placeholders(child)}


class EnqueuedBatch(BaseModel):
    item_ids: list[int] = Field(min_length=1, max_length=1)
    enqueued: int = Field(ge=1, le=1)


class CanceledBatch(BaseModel):
    canceled: int = Field(ge=0)


class NodeResult(BaseModel):
    image: ImageReference | None = None


class GraphSession(BaseModel):
    results: dict[str, NodeResult] = Field(default_factory=dict)
    source_prepared_mapping: dict[str, list[str]] = Field(default_factory=dict)


class QueueItem(BaseModel):
    item_id: int
    batch_id: str
    status: Literal["pending", "in_progress", "waiting", "completed", "failed", "canceled"]
    session: GraphSession


def bind_graph(value: JsonValue, bindings: dict[str, JsonValue]) -> JsonValue:
    if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
        key = value[2:-2]
        if key not in bindings:
            raise ImageGenerationError(f"Unknown graph binding: {key}")
        return bindings[key]
    if isinstance(value, dict):
        return {key: bind_graph(item, bindings) for key, item in value.items()}
    if isinstance(value, list):
        return [bind_graph(item, bindings) for item in value]
    return value


class InvokeAIBackend:
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
        if config.graph_path is None:
            raise ImageGenerationError("Missing InvokeAI graph file")
        self._graph_text = config.graph_path.read_text(encoding="utf-8")
        self._graph = json.loads(self._graph_text)
        graph = ExecutableGraph.model_validate(self._graph)
        if config.output_node not in graph.nodes:
            raise ImageGenerationError("Graph must contain the configured output node")
        self._placeholders = graph_placeholders(self._graph)
        self._workflow_hash = hashlib.sha256(self._graph_text.encode()).hexdigest()

    async def generate(self, request: ImageGenerationRequest) -> GeneratedImage:
        if request.generation_target == "background":
            raise ImageGenerationError(
                "This image backend cannot generate a verified background-only artifact",
                code="background_generation_unsupported",
            )
        headers = {}
        if self._config.token_env:
            if not self._api_key:
                raise ImageGenerationError(
                    "Configured InvokeAI token environment variable is missing"
                )
            headers["Authorization"] = f"Bearer {self._api_key}"
        batch_id = str(uuid4())
        submitted = False
        start = monotonic()
        async with httpx.AsyncClient(
            base_url=self._config.base_url.rstrip("/"),
            headers=headers,
            timeout=self._config.request_timeout_seconds,
            transport=self._transport,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            try:
                async with asyncio.timeout(self._config.generation_timeout_seconds):
                    graph, prompt = await self._prepare_graph(client, request)
                    # Mark before POST: a lost response may still mean the batch was accepted.
                    submitted = True
                    response = await client.post(
                        "/api/v1/queue/default/enqueue_batch",
                        json={"batch": {"batch_id": batch_id, "graph": graph, "runs": 1}},
                    )
                    response.raise_for_status()
                    queued = EnqueuedBatch.model_validate(response.json())
                    item_id = queued.item_ids[0]
                    item = await self._wait(client, item_id, batch_id)
                    image_name = self._output_image(item)
                    content = await self._download(client, image_name)
                    inspect_image(content)
                    return GeneratedImage(
                        content=content,
                        model=self._config.model,
                        model_revision=self._config.model_revision,
                        runtime_version=self._config.runtime_version,
                        workflow_hash=self._workflow_hash,
                        prompt=prompt,
                        seed=request.seed,
                        elapsed_seconds=monotonic() - start,
                        service_job_id=str(item_id),
                        execution_graph=json.dumps(graph, ensure_ascii=False, sort_keys=True),
                    )
            except (
                TimeoutError,
                httpx.HTTPError,
                ValidationError,
                ValueError,
                ImageGenerationError,
            ) as exc:
                cancellation = "not_submitted"
                if submitted:
                    cancellation = await self._cancel(client, batch_id)
                # Never persist server bodies, tokens, full URLs or raw exception text.
                reason = str(exc) if isinstance(exc, ImageGenerationError) else type(exc).__name__
                if isinstance(exc, httpx.HTTPStatusError):
                    reason = f"HTTP {exc.response.status_code}"
                raise ImageGenerationError(
                    f"InvokeAI {reason}; batch={batch_id}; cancellation={cancellation}"
                ) from exc
            except asyncio.CancelledError:
                if submitted:
                    await self._cancel(client, batch_id)
                raise

    async def _prepare_graph(
        self, client: httpx.AsyncClient, request: ImageGenerationRequest
    ) -> tuple[JsonValue, str]:
        data = request.input
        prompt = render_image_prompt(self._config, data, request.revision)
        bindings: dict[str, JsonValue] = {
            "prompt": prompt,
            "seed": request.seed,
            "width": data.output_spec.width,
            "height": data.output_spec.height,
        }
        asset_keys = {
            f"{role}_{index}"
            for role, assets in (
                ("product", data.product_assets),
                ("reference", data.reference_assets),
            )
            for index in range(len(assets))
        }
        if request.revision is not None:
            if request.revision_image_ref is None:
                raise ImageGenerationError(
                    "Revision requires the previous image version",
                    code="revision_source_missing",
                )
            asset_keys.add("revision_source")
        required_keys = set(bindings) | asset_keys
        if required_keys != self._placeholders:
            missing = sorted(required_keys - self._placeholders)
            unknown = sorted(self._placeholders - required_keys)
            raise ImageGenerationError(
                f"Graph bindings mismatch; missing={missing}, unknown={unknown}"
            )
        for role, assets in (
            ("product", data.product_assets),
            ("reference", data.reference_assets),
        ):
            for index, asset in enumerate(assets):
                key = f"{role}_{index}"
                content = read_local_image(asset.url, self._config.max_image_bytes)
                _, _, file_format = inspect_image(content)
                response = await client.post(
                    "/api/v1/images/upload",
                    params={"image_category": "user", "is_intermediate": "true"},
                    files={"file": (f"{key}.{file_format}", content, f"image/{file_format}")},
                )
                response.raise_for_status()
                image = ImageReference.model_validate(response.json())
                bindings[key] = {"image_name": image.image_name}
        if request.revision_image_ref is not None:
            content = read_local_image(request.revision_image_ref, self._config.max_image_bytes)
            _, _, file_format = inspect_image(content)
            response = await client.post(
                "/api/v1/images/upload",
                params={"image_category": "user", "is_intermediate": "true"},
                files={
                    "file": (
                        f"revision_source.{file_format}",
                        content,
                        f"image/{file_format}",
                    )
                },
            )
            response.raise_for_status()
            image = ImageReference.model_validate(response.json())
            bindings["revision_source"] = {"image_name": image.image_name}
        return bind_graph(self._graph, bindings), prompt

    async def _wait(self, client: httpx.AsyncClient, item_id: int, batch_id: str) -> QueueItem:
        while True:
            response = await client.get(f"/api/v1/queue/default/i/{item_id}")
            response.raise_for_status()
            item = QueueItem.model_validate(response.json())
            if item.item_id != item_id or item.batch_id != batch_id:
                raise ImageGenerationError("Queue result does not match this submission")
            if item.status == "completed":
                return item
            if item.status in {"failed", "canceled"}:
                raise ImageGenerationError(f"Queue item {item_id} {item.status}")
            await asyncio.sleep(self._config.poll_interval_seconds)

    def _output_image(self, item: QueueItem) -> str:
        session = item.session
        node = self._config.output_node
        prepared_ids = session.source_prepared_mapping.get(node, [node])
        outputs = [session.results[key].image for key in prepared_ids if key in session.results]
        images = [output for output in outputs if output is not None]
        if len(images) != 1:
            raise ImageGenerationError("Expected one image from configured output node")
        return images[0].image_name

    async def _download(self, client: httpx.AsyncClient, image_name: str) -> bytes:
        async with client.stream(
            "GET", f"/api/v1/images/i/{quote(image_name, safe='')}/full"
        ) as response:
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > self._config.max_image_bytes:
                    raise ImageGenerationError("Generated image exceeds configured byte limit")
            return bytes(content)

    async def _cancel(self, client: httpx.AsyncClient, batch_id: str) -> str:
        try:
            async with asyncio.timeout(self._config.request_timeout_seconds):
                response = await client.put(
                    "/api/v1/queue/default/cancel_by_batch_ids", json={"batch_ids": [batch_id]}
                )
                response.raise_for_status()
                result = CanceledBatch.model_validate(response.json())
            # A timed-out enqueue may still insert the batch after this cancel request.
            return "requested" if result.canceled else "unknown_check_service"
        except (TimeoutError, httpx.HTTPError, ValidationError, ValueError):
            return "unknown_check_service"
