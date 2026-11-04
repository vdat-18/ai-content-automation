"""Read each shot's voice-over with a text-to-speech model and lay the readings on one track."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import httpx
from loguru import logger

from .clips import StitchUnavailable, _run

_TIMEOUT = 120
_TRIES = 3
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_RETRY_DELAY = 4.0
_MAX_SPEEDUP = 1.25
_DEFAULT_VOICE = "auto"


class SpeechError(RuntimeError):
    """The text-to-speech service did not return audio."""


class SpeechClient:
    """OpenAI-style /audio/speech: text in, mp3 bytes out."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        voice: str = "",
        http: httpx.AsyncClient | None = None,
        retry_delay: float = _RETRY_DELAY,
    ) -> None:
        self._url = base_url.rstrip("/") + "/audio/speech"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._model = model
        self._voice = voice or _DEFAULT_VOICE
        self._http = http or httpx.AsyncClient(timeout=_TIMEOUT)
        self._retry_delay = retry_delay

    async def speak(self, text: str) -> bytes:
        body = {
            "model": self._model,
            "input": text,
            "voice": self._voice,
            "response_format": "mp3",
        }
        last = "no response"
        for attempt in range(_TRIES):
            try:
                response = await self._http.post(self._url, json=body, headers=self._headers)
            except httpx.HTTPError as error:
                last = f"request failed: {error!r}"[:200]
            else:
                if response.status_code == 200 and response.content[:1] != b"{":
                    return response.content
                last = f"HTTP {response.status_code}: {response.text[:150]}"
                if response.status_code not in _RETRY_STATUSES and response.status_code != 200:
                    raise SpeechError(last)
            logger.warning("Speech attempt {} failed: {}", attempt + 1, last)
            if attempt < _TRIES - 1:
                await asyncio.sleep(self._retry_delay)
        raise SpeechError(last)


async def _probe_seconds(path: Path) -> float:
    process = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )  # fmt: skip
    stdout, _ = await process.communicate()
    try:
        return float(stdout.decode().strip())
    except ValueError as error:
        raise StitchUnavailable("ffprobe could not read the voice-over audio") from error


async def make_voiceover(
    client: SpeechClient, segments: list[tuple[str, float]], output: Path
) -> list[float]:
    """Read each text so it starts with its shot, and join the readings into one mp3.

    A reading longer than its shot is sped up to at most 1.25x and then cut; a shorter one is
    padded with silence, so every shot's words begin where the shot begins. Returns the natural
    length of each reading so a caller can tell which shots need shorter text.
    """
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise StitchUnavailable("ffmpeg is not installed on this machine")
    if not segments:
        raise StitchUnavailable("No shot has a voice-over text")
    output.parent.mkdir(parents=True, exist_ok=True)
    scratch: list[Path] = []
    lengths: list[float] = []
    parts: list[Path] = []
    try:
        for index, (text, seconds) in enumerate(segments):
            part = output.parent / f"voice_part_{index}.wav"
            scratch.append(part)
            parts.append(part)
            if not text.strip():
                lengths.append(0.0)
                await _run(
                    "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=24000:cl=mono", "-t", f"{seconds:.3f}", part.name,
                    cwd=output.parent,
                )  # fmt: skip
                continue
            raw = output.parent / f"voice_raw_{index}.mp3"
            scratch.append(raw)
            raw.write_bytes(await client.speak(text.strip()))
            length = await _probe_seconds(raw)
            lengths.append(length)
            speed = min(max(length / seconds, 1.0), _MAX_SPEEDUP)
            await _run(
                "ffmpeg", "-v", "error", "-y", "-i", raw.name,
                "-af", f"atempo={speed:.4f},apad=whole_dur={seconds:.3f}",
                "-t", f"{seconds:.3f}", "-ar", "24000", "-ac", "1", part.name,
                cwd=output.parent,
            )  # fmt: skip
        listing = output.parent / "voice_parts.txt"
        scratch.append(listing)
        listing.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        await _run(
            "ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing.name,
            "-c:a", "libmp3lame", "-q:a", "3", output.name, cwd=output.parent,
        )  # fmt: skip
    finally:
        for path in scratch:
            path.unlink(missing_ok=True)
    return lengths
