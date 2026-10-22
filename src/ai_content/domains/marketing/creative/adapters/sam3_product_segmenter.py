"""HTTP adapter for extracting an exact product cutout with SAM 3.1."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import io

import httpx
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_content.platform.runpod_serverless import (
    RunpodServerlessClient,
    RunpodServerlessError,
)

from ..config.segmentation import ProductSegmenterConfig
from ..ports.images import ImageGenerationError, ProductCutout
from .image_files import inspect_image, read_local_image


class _SegmentationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    mask_png_base64: str = Field(min_length=4)
    cutout_png_base64: str = Field(min_length=4)
    bounding_box: tuple[int, int, int, int]
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)


class Sam3ProductSegmenter:
    def __init__(
        self,
        config: ProductSegmenterConfig,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        runpod_endpoint_id: str | None = None,
        runpod_api_key: str | None = None,
        runpod_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
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

    async def extract(self, source_ref: str, prompt: str) -> ProductCutout:
        if not prompt.strip():
            raise ImageGenerationError(
                "Product segmentation prompt is required", "segmentation_prompt_missing"
            )
        source = read_local_image(source_ref, self._config.max_image_bytes)
        width, height, image_format = inspect_image(source)
        content_type = "image/jpeg" if image_format == "jpeg" else f"image/{image_format}"
        try:
            request_payload = {
                "prompt": prompt.strip(),
                "image_content_type": content_type,
                "image_base64": base64.b64encode(source).decode("ascii"),
            }
            if self._runpod is not None:
                output = await self._runpod.invoke(
                    {"operation": "image_segmentation", "payload": request_payload}
                )
                if output.get("operation") != "image_segmentation":
                    raise ValueError("Runpod verifier returned the wrong operation")
                payload = _SegmentationResponse.model_validate(output.get("result"))
            else:
                async with (
                    httpx.AsyncClient(
                        base_url=self._config.base_url.rstrip("/"),
                        timeout=self._config.request_timeout_seconds,
                        transport=self._transport,
                        follow_redirects=False,
                        trust_env=False,
                    ) as client,
                    asyncio.timeout(self._config.request_timeout_seconds),
                ):
                    response = await client.post(
                        "/v1/image-segmentations",
                        json=request_payload,
                    )
                    response.raise_for_status()
                    if len(response.content) > self._config.max_response_bytes:
                        raise ImageGenerationError(
                            "Product segmentation response exceeds configured byte limit",
                            "segmentation_response_too_large",
                        )
                    payload = _SegmentationResponse.model_validate_json(response.content)
            if (
                payload.model != self._config.model
                or payload.model_version != self._config.model_version
            ):
                raise ImageGenerationError(
                    "Product segmentation model does not match the pinned config",
                    "segmentation_model_mismatch",
                )
            mask = base64.b64decode(payload.mask_png_base64, validate=True)
            service_cutout = base64.b64decode(payload.cutout_png_base64, validate=True)
            cutout = self._validate_artifacts(
                source, mask, service_cutout, width, height, payload.bounding_box
            )
        except ImageGenerationError:
            raise
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ImageGenerationError(
                "Product segmentation service timed out", "segmentation_timeout"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise ImageGenerationError(
                f"Product segmentation service returned HTTP {exc.response.status_code}",
                "segmentation_http_error",
            ) from exc
        except (
            httpx.HTTPError,
            RunpodServerlessError,
            ValidationError,
            ValueError,
            binascii.Error,
        ) as exc:
            raise ImageGenerationError(
                "Product segmentation response is invalid", "invalid_segmentation_response"
            ) from exc
        return ProductCutout(
            rgba_png=cutout,
            mask_png=mask,
            source_checksum=hashlib.sha256(source).hexdigest(),
            model=payload.model,
            model_version=payload.model_version,
            prompt=prompt.strip(),
            bounding_box=payload.bounding_box,
            source_width=payload.source_width,
            source_height=payload.source_height,
        )

    @staticmethod
    def _validate_artifacts(
        source: bytes,
        mask: bytes,
        service_cutout: bytes,
        width: int,
        height: int,
        bounding_box: tuple[int, int, int, int],
    ) -> bytes:
        mask_width, mask_height, mask_format = inspect_image(mask)
        cutout_width, cutout_height, cutout_format = inspect_image(service_cutout)
        if mask_format != "png" or cutout_format != "png":
            raise ImageGenerationError(
                "Product mask and cutout must be PNG", "invalid_segmentation_response"
            )
        if (mask_width, mask_height) != (width, height) or (
            cutout_width,
            cutout_height,
        ) != (width, height):
            raise ImageGenerationError(
                "Product mask and cutout dimensions must match the source",
                "invalid_segmentation_response",
            )
        left, top, right, bottom = bounding_box
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise ImageGenerationError(
                "Product segmentation bounding box is invalid", "invalid_segmentation_response"
            )
        with Image.open(io.BytesIO(mask)) as opened_mask:
            mask_image = opened_mask.convert("L")
        if mask_image.getbbox() is None:
            raise ImageGenerationError(
                "Product segmentation mask is empty", "empty_segmentation_mask"
            )
        if mask_image.getbbox() != bounding_box:
            raise ImageGenerationError(
                "Product segmentation bounding box does not match the mask",
                "invalid_segmentation_response",
            )
        with Image.open(io.BytesIO(source)) as opened_source:
            expected_cutout = opened_source.convert("RGBA")
        expected_cutout.putalpha(mask_image)
        with Image.open(io.BytesIO(service_cutout)) as opened_cutout:
            returned_cutout = opened_cutout.convert("RGBA")
        if returned_cutout.tobytes() != expected_cutout.tobytes():
            raise ImageGenerationError(
                "Product cutout does not preserve the exact source pixels and mask",
                "invalid_segmentation_response",
            )
        stream = io.BytesIO()
        expected_cutout.save(stream, format="PNG")
        return stream.getvalue()


__all__ = ["Sam3ProductSegmenter"]
