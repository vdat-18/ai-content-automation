"""Generate still keyframe images for storyboard shots through an OpenAI-compatible endpoint."""

from __future__ import annotations

import asyncio
import base64
import re
from typing import Any

import httpx
from loguru import logger

ASPECT_SIZE = "1024x1792"
_REQUEST_TIMEOUT = 240
_TRIES = 3
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_RETRY_DELAY = 5.0
_DOWNLOAD_TIMEOUT = 40

_PRODUCT_RULE = (
    "The product photos show the real product: keep its exact shape, color, proportions, "
    "material, label and details, and never add features it does not have. Do not copy text, "
    "logos, prices or overlays from the photos. Vertical 9:16 photo."
)
_NO_PEOPLE = "Do not show any human face; hands, the product and the space are enough."
_PERSONA_RULE = (
    "is the person in the ad. Copy her face, hair length and colour, skin tone, body and clothes "
    "exactly from this image in every shot and ignore any other description of her looks in the "
    "text below; she must be recognisable as the same real person. Natural hands, no extra fingers."
)
_REAL_PHOTO = (
    "Make it look like an ordinary photo taken with a phone: natural light, a little grain, "
    "natural skin with pores, everyday details of a lived-in home. Not glossy, retouched, studio "
    "or 3D-render looking."
)


def _size_note(shot: dict[str, Any]) -> str:
    size = str(shot.get("product_size") or "").strip()
    return (
        f"Real size of the product, keep this scale next to the person and the room: {size}."
        if size
        else ""
    )


def _variant_note(shot: dict[str, Any]) -> str:
    variant = str(shot.get("product_variant") or "").strip()
    return (
        f"The product comes in several versions; show only this one: {variant}. Ignore the "
        "other versions in the photos."
        if variant
        else ""
    )


def _fix_note(problem: str) -> str:
    return f"A previous attempt had this problem; fix it: {problem}"


class KeyframeGenerationError(RuntimeError):
    """The image model did not return a usable image."""


def _media_type(content: bytes) -> str:
    if content[:4] == b"\x89PNG":
        return "image/png"
    if content[:4] == b"RIFF":
        return "image/webp"
    return "image/jpeg"


def _data_url(content: bytes) -> str:
    return f"data:{_media_type(content)};base64,{base64.b64encode(content).decode()}"


class KeyframeImageClient:
    """Send a prompt plus input images to a chat-style image model and return the image bytes."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        http: httpx.AsyncClient | None = None,
        retry_delay: float = _RETRY_DELAY,
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._http = http or httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True)
        self._retry_delay = retry_delay

    async def generate(self, prompt: str, images: list[bytes]) -> bytes:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content += [{"type": "image_url", "image_url": {"url": _data_url(i)}} for i in images]
        body = {
            "model": self._model,
            "size": ASPECT_SIZE,
            "messages": [{"role": "user", "content": content}],
        }
        last = "no response"
        for attempt in range(_TRIES):
            try:
                response = await self._http.post(self._url, json=body, headers=self._headers)
            except httpx.HTTPError as error:
                last = f"request failed: {error!r}"[:200]
            else:
                if response.status_code == 200:
                    image = await self._extract(response.text)
                    if image:
                        return image
                    last = "no image in the response"
                elif response.status_code in _RETRY_STATUSES:
                    last = f"HTTP {response.status_code}: {response.text[:150]}"
                else:
                    raise KeyframeGenerationError(
                        f"HTTP {response.status_code}: {response.text[:200]}"
                    )
            logger.warning("Keyframe request attempt {} failed: {}", attempt + 1, last)
            if attempt < _TRIES - 1:
                await asyncio.sleep(self._retry_delay)
        raise KeyframeGenerationError(last)

    async def _extract(self, text: str) -> bytes | None:
        inline = re.search(r"data:image/\w+;base64,([A-Za-z0-9+/=]+)", text)
        if inline:
            return base64.b64decode(inline.group(1))
        link = re.search(r"https?://[^\s)\"'\\]+\.(?:jpe?g|png|webp)", text)
        if not link:
            return None
        try:
            response = await self._http.get(link.group(0), timeout=_DOWNLOAD_TIMEOUT)
            response.raise_for_status()
        except httpx.HTTPError as error:
            logger.warning("Keyframe download failed: {}", str(error)[:200])
            return None
        return response.content


class KeyframeGenerator:
    """Build the prompt and inputs for a master or follow-up keyframe and call the model."""

    def __init__(self, client: KeyframeImageClient) -> None:
        self._client = client

    async def persona(self, description: str, fix: str = "") -> bytes:
        """A reference portrait of the recurring person; every keyframe is built around it."""
        parts = [
            "A natural, candid phone photo of a synthetic person who does not exist and does not "
            "resemble any real or famous person, in a relaxed pose, waist-up, in soft daylight "
            "against a plain light wall, facing the camera with a friendly neutral expression, "
            "natural skin with pores, not retouched. Vertical 9:16 photo.",
            f"The person: {description}",
        ]
        if fix:
            parts.append(_fix_note(fix))
        return await self._client.generate("\n".join(parts), [])

    async def master(
        self,
        shot: dict[str, Any],
        product_photos: list[bytes],
        scene: bytes | None,
        fix: str = "",
        persona: bytes | None = None,
    ) -> bytes:
        parts = [f"Images 1 to {len(product_photos)} are the real product photos."]
        images = list(product_photos)
        if persona is not None:
            images.append(persona)
            parts.append(f"Image {len(images)} {_PERSONA_RULE}")
        if scene is not None:
            images.append(scene)
            parts.append(
                f"Image {len(images)} is a scene reference: borrow only its setting, light and "
                "styling, never its objects, brand, text or people."
            )
        parts += [_PRODUCT_RULE, "" if persona is not None else _NO_PEOPLE]
        parts += [_variant_note(shot), _size_note(shot), _REAL_PHOTO]
        parts += ["Shot to create:", str(shot["keyframe_prompt"])]
        if fix:
            parts.append(_fix_note(fix))
        return await self._client.generate("\n".join(p for p in parts if p), images)

    async def follow_up(
        self,
        shot: dict[str, Any],
        master: bytes,
        product_photos: list[bytes],
        fix: str = "",
        persona: bytes | None = None,
    ) -> bytes:
        images = [master]
        parts = [
            "Image 1 is the approved master keyframe: keep the same product, light, colors and "
            "the same style of place."
        ]
        if persona is not None:
            images.append(persona)
            parts.append(f"Image {len(images)} {_PERSONA_RULE}")
        images += product_photos
        parts.append("The remaining images are the real product photos.")
        parts += [_PRODUCT_RULE, "" if persona is not None else _NO_PEOPLE]
        parts += [
            _variant_note(shot),
            _size_note(shot),
            _REAL_PHOTO,
            "Change the camera angle, framing, action and, when the shot says so, the spot in "
            "the same home. Shot to create:",
            str(shot["keyframe_prompt"]),
        ]
        if fix:
            parts.append(_fix_note(fix))
        return await self._client.generate("\n".join(p for p in parts if p), images)


async def fetch_images(urls: list[str], http: httpx.AsyncClient | None = None) -> list[bytes]:
    """Download images, dropping failures and byte-identical duplicates."""
    owned = http is None
    http = http or httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True)
    found: list[bytes] = []
    try:
        for url in urls:
            try:
                response = await http.get(url)
                response.raise_for_status()
            except httpx.HTTPError as error:
                logger.warning("Keyframe input download failed: {}", str(error)[:200])
                continue
            if response.content not in found:
                found.append(response.content)
    finally:
        if owned:
            await http.aclose()
    return found
