"""Generate still keyframe images for storyboard shots through an OpenAI-compatible endpoint."""

from __future__ import annotations

import asyncio
import base64
import io
import re
from typing import Any

import httpx
from loguru import logger
from PIL import Image

ASPECT_SIZE = "1024x1792"
ASPECT_RATIO = "9:16"
_REQUEST_TIMEOUT = 240
_TRIES = 3
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_RETRY_DELAY = 5.0
_DOWNLOAD_TIMEOUT = 40
_MAX_INPUT_SIDE = 1792  # the long side of the generated keyframes

_PRODUCT_RULE = (
    "The product photos show the real product: keep its exact shape, color, proportions, "
    "material, label and details, and never add features it does not have. Do not copy text, "
    "logos, prices or overlays from the photos. Vertical 9:16 photo."
)
_NO_PEOPLE = "Do not show any human face; hands, the product and the space are enough."
_PERSONA_RULE = (
    "the person in the ad. Copy their face, hair length and colour, skin tone and body exactly "
    "from these images in every shot and ignore any other description of their looks in the text "
    "below; they must be recognisable as the same real person. Give the face clear, even skin: "
    "remove any acne, pimples, spots, scars and blemishes seen in the images, but keep the "
    "natural pores and every other feature unchanged. Wear the clothes the shot asks "
    "for (the product, when it is clothing), otherwise the clothes seen in the images."
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


def _persona_note(first: int, last: int) -> str:
    which = f"Image {first} shows" if first == last else f"Images {first} to {last} show"
    return f"{which} {_PERSONA_RULE}"


def story_note(brief: dict[str, Any], index: int) -> str:
    """The whole video as context for one shot: its place, look and the order of the shots."""
    shots = brief.get("shots") or []
    return "\n".join(
        [
            f"This is shot {index + 1} of {len(shots)} of one video: {brief.get('title', '')}.",
            f"Selling angle: {brief.get('selling_angle', '')}. "
            f"Audience: {brief.get('target_audience', '')}.",
            f"Every shot happens in this place: {brief.get('scene', '')}. "
            f"Where the product sits: {brief.get('product_placement', '')}.",
            f"Style: {', '.join(brief.get('style') or [])}. "
            f"Colors: {', '.join(brief.get('colors') or [])}.",
            f"What is said over this shot: {shots[index].get('voiceover', '')}",
            "The shots in order:",
            *(
                f"{i + 1}. {s.get('role', '')}: {s.get('description', '')}"
                for i, s in enumerate(shots)
            ),
        ]
    )


def _story_part(shot: dict[str, Any]) -> str:
    story = str(shot.get("story") or "")
    return f"The whole video, for context:\n{story}" if story else ""


def _rules_part(shot: dict[str, Any]) -> str:
    rules = str(shot.get("rules") or "")
    return f"Rules to follow in the picture:\n{rules}" if rules else ""


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


def _shrink(content: bytes) -> bytes:
    """Re-encode an input image that is larger than the output keyframe; others pass through."""
    try:
        with Image.open(io.BytesIO(content)) as image:
            if max(image.size) <= _MAX_INPUT_SIDE:
                return content
            image.thumbnail((_MAX_INPUT_SIDE, _MAX_INPUT_SIDE))
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, "JPEG", quality=90)
    except OSError:  # a format Pillow cannot read: send it unchanged
        return content
    return buffer.getvalue()


def _data_url(content: bytes) -> str:
    content = _shrink(content)
    return f"data:{_media_type(content)};base64,{base64.b64encode(content).decode()}"


class KeyframeImageClient:
    """Send a prompt plus input images to a chat-style image model and return the image bytes."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        api: str = "chat",
        http: httpx.AsyncClient | None = None,
        retry_delay: float = _RETRY_DELAY,
    ) -> None:
        """`api` is "chat" (chat completions) or "edits" (the images/edits endpoint)."""
        path = "/images/edits" if api == "edits" else "/chat/completions"
        self._edits = api == "edits"
        self._url = base_url.rstrip("/") + path
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._http = http or httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True)
        self._retry_delay = retry_delay

    async def generate(self, prompt: str, images: list[bytes]) -> bytes:
        urls = [_data_url(i) for i in images]
        body: dict[str, Any]
        if self._edits:
            body = {
                "model": self._model,
                "prompt": prompt,
                "image": urls,
                "aspect_ratio": ASPECT_RATIO,
            }
        else:
            content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            content += [{"type": "image_url", "image_url": {"url": url}} for url in urls]
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

    async def master(
        self,
        shot: dict[str, Any],
        product_photos: list[bytes],
        scene: bytes | None,
        fix: str = "",
        persona: list[bytes] | None = None,
    ) -> bytes:
        parts = [f"Images 1 to {len(product_photos)} are the real product photos."]
        images = list(product_photos)
        if persona:
            images += persona
            parts.append(_persona_note(len(images) - len(persona) + 1, len(images)))
        if scene is not None:
            images.append(scene)
            parts.append(
                f"Image {len(images)} is a scene reference: borrow only its setting, light and "
                "styling, never its objects, brand, text or people."
            )
        parts += [_PRODUCT_RULE, "" if persona else _NO_PEOPLE]
        parts += [_variant_note(shot), _size_note(shot), _rules_part(shot)]
        parts += [_story_part(shot), "Shot to create:", str(shot["keyframe_prompt"])]
        if fix:
            parts.append(_fix_note(fix))
        return await self._client.generate("\n".join(p for p in parts if p), images)

    async def follow_up(
        self,
        shot: dict[str, Any],
        master: bytes,
        product_photos: list[bytes],
        fix: str = "",
        persona: list[bytes] | None = None,
        reference: bytes | None = None,
    ) -> bytes:
        images = [master]
        parts = [
            "Image 1 is the approved master keyframe: keep the same product, light, colors and "
            "the same style of place."
        ]
        if persona:
            images += persona
            parts.append(_persona_note(len(images) - len(persona) + 1, len(images)))
        if reference is not None:
            images.append(reference)
            parts.append(
                f"Image {len(images)} is a loose reference for the pose, framing and camera angle "
                "only: keep the room, light, person and product exactly as in the other images and "
                "never copy its objects, brand, text or people."
            )
        images += product_photos
        parts.append("The remaining images are the real product photos.")
        parts += [_PRODUCT_RULE, "" if persona else _NO_PEOPLE]
        parts += [
            _variant_note(shot),
            _size_note(shot),
            _rules_part(shot),
            _story_part(shot),
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

    async def download(url: str) -> bytes | None:
        try:
            response = await http.get(url)
            response.raise_for_status()
        except httpx.HTTPError as error:
            logger.warning("Keyframe input download failed: {}", str(error)[:200])
            return None
        return response.content

    found: list[bytes] = []
    try:
        for content in await asyncio.gather(*(download(url) for url in urls)):
            if content is not None and content not in found:
                found.append(content)
    finally:
        if owned:
            await http.aclose()
    return found
