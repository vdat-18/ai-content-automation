"""Choose the voice-over voice from the brief and the photos of the person."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from baml_py import Image as BamlImage
from baml_py.baml_py import BamlError
from loguru import logger

from ai_content.domains.marketing.products.adapters.baml_client import types as baml_types
from ai_content.domains.marketing.products.adapters.baml_client.async_client import b
from ai_content.domains.marketing.products.adapters.baml_registry import build_client_registry

CATALOG = Path("config/voices.json")  # relative to the working directory, like config/creative_knowledge


@dataclass(frozen=True)
class VoiceChoice:
    voice: str
    reason: str


class _BamlVoiceClient(Protocol):
    async def PickVoice(
        self, brief_json: str, voices_json: str, person_photos: list[BamlImage]
    ) -> baml_types.VoicePick: ...


def load_catalog() -> list[dict[str, Any]]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _image(content: bytes) -> BamlImage:
    media_type = "image/png" if content[:4] == b"\x89PNG" else "image/jpeg"
    return BamlImage.from_base64(media_type, base64.b64encode(content).decode("ascii"))


def settle(gender: str, voice: str, reason: str, catalog: list[dict[str, Any]]) -> VoiceChoice:
    """Keep the model's voice only when it exists and matches the person's gender."""
    by_id = {entry["id"]: entry for entry in catalog}
    wanted = gender.strip().lower()
    picked = by_id.get(voice.strip())
    if picked is not None and wanted in ("male", "female") and picked["gender"] != wanted:
        picked = None
    if picked is None:
        pool = [e for e in catalog if wanted not in ("male", "female") or e["gender"] == wanted]
        picked = (pool or catalog)[0]
        reason = "Default voice for this gender."
    return VoiceChoice(picked["id"], reason.strip())


class VoicePicker:
    """Ask the BAML screening model which voice fits the brief and the person."""

    def __init__(self, client: _BamlVoiceClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, *, base_url: str, api_key: str, model: str) -> VoicePicker:
        registry = build_client_registry(
            name="VoicePick",
            base_url=base_url,
            model=model,
            api_key=api_key,
            reasoning_effort=None,
            temperature=0,
        )
        return cls(b.with_options(client_registry=registry))

    async def pick(self, brief: dict[str, Any], photos: list[bytes]) -> VoiceChoice | None:
        """Return the chosen voice, or None when the model did not answer."""
        catalog = load_catalog()
        story = {
            "title": brief.get("title"),
            "with_person": brief.get("with_person"),
            "script": [shot.get("voiceover") for shot in brief.get("shots") or []],
        }
        try:
            result = await self._client.PickVoice(
                json.dumps(story, ensure_ascii=False),
                json.dumps(catalog, ensure_ascii=False),
                [_image(photo) for photo in photos],
            )
        except BamlError as error:
            logger.warning("Voice pick failed: {}", str(error)[:300])
            return None
        return settle(result.gender, result.voice, result.reason, catalog)
