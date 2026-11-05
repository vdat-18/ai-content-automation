import shutil
import subprocess

import httpx
import pytest

from ai_content.domains.marketing.products.repositories import SqliteProductRepository
from ai_content.domains.marketing.products.service import (
    KeyframeUnavailable,
    ProductCatalogService,
)
from ai_content.domains.marketing.products.speech import (
    Reading,
    SpeechClient,
    SpeechError,
    make_voiceover,
)

PRODUCT_ID = "1730000000000000001"
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


def _tone(seconds: float) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}", "-f", "mp3", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip


def _write_wav(path, bursts, seconds: float) -> None:
    """Silence with a harmonic tone burst for each (start, end, pitch)."""
    import wave

    import numpy as np

    rate = 16_000
    samples = np.zeros(int(seconds * rate))
    for start, end, pitch in bursts:
        t = np.arange(int((end - start) * rate)) / rate
        tone = sum(np.sin(2 * np.pi * pitch * k * t) / k for k in (1, 2, 3, 4))
        samples[int(start * rate) : int(start * rate) + len(t)] = 0.2 * tone * np.hanning(len(t))
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((samples * 32767).astype(np.int16).tobytes())


def _client(handler) -> SpeechClient:
    return SpeechClient(
        base_url="https://api.example/v1",
        api_key="k",
        model="bh2/tts-1",
        voice="kimoanh.mp3",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        retry_delay=0,
    )


async def test_speech_client_sends_the_voice_and_returns_the_audio() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"ID3audio")

    assert await _client(handler).speak("Xin chào") == b"ID3audio"
    body = seen[0].content.decode()
    assert '"voice":"kimoanh.mp3"' in body and '"model":"bh2/tts-1"' in body
    assert seen[0].url.path.endswith("/audio/speech")


async def test_speech_client_retries_overload_and_rejects_other_errors() -> None:
    attempts = []

    def flaky(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return (
            httpx.Response(503, text="busy")
            if len(attempts) < 3
            else httpx.Response(200, content=b"ok")
        )

    assert await _client(flaky).speak("a") == b"ok"
    with pytest.raises(SpeechError, match="HTTP 403"):
        await _client(lambda request: httpx.Response(403, text="subscribe")).speak("a")
    with pytest.raises(SpeechError, match="HTTP 503"):
        await _client(lambda request: httpx.Response(503, text="busy")).speak("a")
    json_error = _client(lambda request: httpx.Response(200, content=b'{"error":"x"}'))
    with pytest.raises(SpeechError):
        await json_error.speak("a")


@needs_ffmpeg
async def test_each_reading_is_fitted_to_its_shot(tmp_path) -> None:
    lengths = {"ngắn": 1.0, "dài": 6.0}

    class _Fake:
        async def speak(self, text, voice=None):
            return _tone(lengths[text])

    output = tmp_path / "videos" / "voiceover.mp3"
    readings = [Reading("ngắn", 3.0), Reading("", 2.0), Reading("dài", 4.0)]
    result = await make_voiceover(_Fake(), readings, output)  # type: ignore[arg-type]
    assert [round(n) for n in result] == [1, 0, 6]
    duration = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(output)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert 8.8 < float(duration) < 9.4
    assert sorted(p.name for p in output.parent.iterdir()) == ["voiceover.mp3"]


@needs_ffmpeg
async def test_a_talking_shot_follows_the_speech_of_its_clip(tmp_path) -> None:
    guide = tmp_path / "guide.wav"
    _write_wav(guide, [(0.5, 1.3, 150), (2.2, 3.2, 220), (4.0, 4.6, 300)], 5.5)

    class _Fake:
        async def speak(self, text, voice=None):
            return _tone(3.0)

    output = tmp_path / "videos" / "voiceover.mp3"
    readings = [Reading("nói", 4.0, guide), Reading("kể", 2.0)]
    await make_voiceover(_Fake(), readings, output)  # type: ignore[arg-type]
    duration = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(output)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert 5.8 < float(duration) < 6.3
    assert sorted(p.name for p in output.parent.iterdir()) == ["voiceover.mp3"]


async def test_a_talking_shot_needs_its_clip_before_the_voice(tmp_path) -> None:
    repository = SqliteProductRepository(tmp_path / "s.db")
    shots = [{"voiceover": "Xin chào", "duration_seconds": 15, "delivery": "talking"}]
    await repository.save_brief(PRODUCT_ID, "", {"shots": shots}, "approved")
    await repository.save_keyframe(
        {
            "product_id": PRODUCT_ID,
            "shot_index": 0,
            "status": "approved",
            "prompt": "p",
            "image_path": "k.jpg",
            "attempts": 1,
            "error": None,
            "qa_problem": "",
        }
    )
    service = ProductCatalogService(repository, speaker=object())  # type: ignore[arg-type]
    with pytest.raises(KeyframeUnavailable, match="Make the clip for shot 1 first"):
        await service.create_voiceover(PRODUCT_ID, tmp_path)


@needs_ffmpeg
async def test_a_clip_without_speech_is_reported_not_crashed(tmp_path) -> None:
    repository = SqliteProductRepository(tmp_path / "s.db")
    shots = [{"voiceover": "Xin chào", "duration_seconds": 15, "delivery": "talking"}]
    await repository.save_brief(PRODUCT_ID, "", {"shots": shots}, "approved")
    keyframe = {
        "product_id": PRODUCT_ID,
        "shot_index": 0,
        "status": "approved",
        "prompt": "p",
        "image_path": "k.jpg",
        "attempts": 1,
        "error": None,
        "qa_problem": "",
    }
    await repository.save_keyframe(keyframe)
    silent = tmp_path / "clips" / PRODUCT_ID / "shot_0.wav"
    silent.parent.mkdir(parents=True)
    _write_wav(silent, [], 3.0)
    await repository.save_clip(
        {
            "product_id": PRODUCT_ID,
            "shot_index": 0,
            "status": "ready",
            "job_id": "j",
            "job_model": "m",
            "video_path": f"clips/{PRODUCT_ID}/shot_0.wav",
            "seconds": 15,
            "attempts": 1,
            "error": None,
        }
    )

    class _Fake:
        async def speak(self, text, voice=None):
            return _tone(3.0)

    service = ProductCatalogService(repository, speaker=_Fake())  # type: ignore[arg-type]
    with pytest.raises(KeyframeUnavailable, match="no speech to follow"):
        await service.create_voiceover(PRODUCT_ID, tmp_path)


async def test_service_needs_the_speaker_and_an_approved_keyframe(tmp_path) -> None:
    repository = SqliteProductRepository(tmp_path / "s.db")
    shots = [{"voiceover": "Xin chào", "duration_seconds": 15}]
    await repository.save_brief(PRODUCT_ID, "", {"shots": shots}, "approved")
    assert await ProductCatalogService(repository).create_voiceover("missing", tmp_path) is None
    with pytest.raises(KeyframeUnavailable, match="not configured"):
        await ProductCatalogService(repository).create_voiceover(PRODUCT_ID, tmp_path)
    service = ProductCatalogService(repository, speaker=object())  # type: ignore[arg-type]
    with pytest.raises(KeyframeUnavailable, match="Approve at least one keyframe"):
        await service.create_voiceover(PRODUCT_ID, tmp_path)


async def test_speech_client_uses_the_voice_it_is_asked_for() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"ID3audio")

    await _client(handler).speak("a", "maichi.mp3")
    assert '"voice":"maichi.mp3"' in seen[0].content.decode()


async def test_voice_sample_is_made_once_and_unknown_voices_are_refused(tmp_path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.content.decode())
        return httpx.Response(200, content=b"ID3audio")

    service = ProductCatalogService(
        SqliteProductRepository(tmp_path / "s.db"), speaker=_client(handler)
    )
    first = await service.voice_sample("hamy.mp3", tmp_path)
    second = await service.voice_sample("hamy.mp3", tmp_path)
    assert first == second and first.read_bytes() == b"ID3audio"
    assert len(calls) == 1 and '"voice":"hamy.mp3"' in calls[0]
    with pytest.raises(KeyframeUnavailable, match="Unknown voice"):
        await service.voice_sample("../evil", tmp_path)
