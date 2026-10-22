"""Vision check that a generated image still shows the exact product from its packshot."""

from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path

import httpx
from loguru import logger
from PIL import Image

from ai_content.domains.marketing.creative.ports.media_production import (
    PaidImageGenerationRequest,
    PaidMediaArtifact,
    PaidMediaQualityEvaluation,
    PaidMediaQualityIssue,
)

from .managed_media import ManagedMediaArtifactSink

_INSTRUCTIONS = (
    "You check product fidelity in advertising images. Image 1 is the official product "
    "packshot and is the only product truth. Image 2 is a generated ad. Judge only the "
    "product, not the scene, people, props or style. The product in image 2 must keep the "
    "same product type and silhouette (for example a tube must stay a tube), proportions, "
    "colors and finishes of every part, materials, and visible details. Any text, label, "
    "logo or brand name on the product that is not on the packshot is a failure. A product "
    "that is partly hidden or seen from another angle is fine when what is visible matches. "
    'Return JSON only: {"verdict": "pass" | "fail", "summary": "<one sentence>", '
    '"issues": [{"code": "<snake_case>", "detail": "<what differs>", '
    '"fix": "<instruction for the next image generation>"}]}. Use an empty issues list '
    "when the verdict is pass."
)


class NineRouterProductFidelityEvaluator:
    """Ask a vision model whether the product in a generated image matches its packshot."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        sink: ManagedMediaArtifactSink,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._api_key = api_key
        self._model = model
        self._sink = sink
        self._timeout_seconds = timeout_seconds
        self._client = client

    async def evaluate_image(
        self,
        request: PaidImageGenerationRequest,
        artifact: PaidMediaArtifact,
    ) -> PaidMediaQualityEvaluation:
        product = next(source for source in request.sources if source.role == "product")
        payload = {
            "model": self._model,
            "temperature": 0,
            "stream": False,
            "messages": [
                {"role": "system", "content": _INSTRUCTIONS},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Image 1: official product packshot."},
                        _image_part(self._sink.local_path(product.asset_ref)),
                        {"type": "text", "text": "Image 2: generated advertising image."},
                        _image_part(self._sink.local_path(artifact.artifact_ref)),
                    ],
                },
            ],
        }
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout_seconds)
        try:
            response = await client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            response.raise_for_status()
        finally:
            if owns_client:
                await client.aclose()
        content = response.json()["choices"][0]["message"]["content"]
        try:
            return _evaluation(content)
        except (ValueError, KeyError, TypeError) as error:
            logger.warning("Product fidelity check returned unusable output: {}", error)
            return PaidMediaQualityEvaluation(
                "human_review",
                "Automatic product fidelity check returned no usable verdict.",
            )


def _image_part(path: Path) -> dict[str, object]:
    with Image.open(path) as image:
        image.thumbnail((1024, 1024))
        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=90)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}


def _evaluation(content: str) -> PaidMediaQualityEvaluation:
    data = json.loads(content[content.index("{") : content.rindex("}") + 1])
    summary = str(data.get("summary") or "").strip() or "Product fidelity checked."
    if data["verdict"] == "pass":
        return PaidMediaQualityEvaluation("pass", f"Product fidelity check passed. {summary}")
    if data["verdict"] != "fail":
        raise ValueError(f"Unknown verdict {data['verdict']!r}")
    issues = tuple(
        PaidMediaQualityIssue(
            code=str(item.get("code") or "product_mismatch"),
            detail=str(item.get("detail") or summary),
            severity="major",
            repair_instruction=str(item.get("fix") or "") or None,
        )
        for item in data.get("issues") or ()
    ) or (PaidMediaQualityIssue("product_mismatch", summary, "major", None),)
    if not any(issue.repair_instruction for issue in issues):
        issues = (
            *issues[:-1],
            PaidMediaQualityIssue(
                issues[-1].code,
                issues[-1].detail,
                "major",
                "Show the product exactly as in the packshot.",
            ),
        )
    return PaidMediaQualityEvaluation("revise", f"Product fidelity check failed. {summary}", issues)


__all__ = ["NineRouterProductFidelityEvaluator"]
