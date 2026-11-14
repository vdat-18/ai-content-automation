import shutil
import subprocess

import pytest

from ai_content.domains.marketing.products import service as service_module
from ai_content.domains.marketing.products.repositories import SqliteProductRepository
from ai_content.domains.marketing.products.service import ProductCatalogService
from ai_content.domains.marketing.products.shortening import VoiceShortener, words_that_fit
from ai_content.domains.marketing.products.word_timing import Timing

PRODUCT_ID = "1730000000000000001"
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
PRODUCT = {"title": "Áo", "price": {"sale": "199000"}}
LONG = " ".join(["Áo cotton mềm mát,"] * 5 + ["giá chỉ 199k"])  # 22 words


class _Answer:
    def __init__(self, text: str) -> None:
        self.text = text


class _Model:
    def __init__(self, text: str) -> None:
        self.text = text
        self.asked: list[tuple[str, int]] = []

    async def ShortenVoiceover(self, line: str, max_words: int, rules: str) -> _Answer:
        self.asked.append((line, max_words))
        return _Answer(self.text)


def _tone(seconds: float) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}", "-f", "mp3", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip


def test_the_words_that_fit_follow_the_fastest_speed_a_shot_can_take() -> None:
    # 20 words read in 20 s for a 10 s shot: at 1.5x 15 s would still be too long, aim at 90 %
    assert words_that_fit(" ".join(["a"] * 20), 20.0, 10.0) == 13
    assert words_that_fit("một", 100.0, 1.0) == 1  # never fewer than one word


async def test_a_shorter_line_with_the_same_figures_is_accepted() -> None:
    model = _Model("Áo cotton mềm mát, giá chỉ 199k")
    shortener = VoiceShortener(model)  # type: ignore[arg-type]
    assert await shortener.shorten(PRODUCT, LONG, 8) == "Áo cotton mềm mát, giá chỉ 199k"
    assert model.asked == [(LONG, 8)]


@pytest.mark.parametrize(
    "answer",
    [
        "Áo cotton mềm mát, giá chỉ 99k",  # a different price
        "Áo cotton mềm mát lắm",  # the price is gone
        "Áo cotton mềm mát, tốt nhất, giá chỉ 199k",  # an absolute claim
        "Áo cotton mềm mát, giá chỉ 199k, mua ngay đi bạn ơi",  # over the word limit
        " ".join([LONG, "nữa"]),  # longer than the original
        "",
    ],
)
async def test_a_line_that_breaks_a_rule_is_refused(answer: str) -> None:
    shortener = VoiceShortener(_Model(answer))  # type: ignore[arg-type]
    assert await shortener.shorten(PRODUCT, LONG, 10) is None


class _Speaker:
    """Reads a long line in 40 s and a short one in 3 s."""

    def __init__(self) -> None:
        self.read: list[str] = []

    async def speak(self, text, voice=None):
        self.read.append(text)
        return _tone(40.0 if len(text.split()) > 10 else 3.0)


class _Shortener:
    def __init__(self, text: str | None) -> None:
        self.text = text
        self.calls = 0

    async def shorten(self, product, text, max_words, rules=""):
        self.calls += 1
        return self.text


async def _ready(tmp_path, monkeypatch) -> tuple[SqliteProductRepository, _Speaker]:
    async def heard(audio, text, model_dir):
        return Timing([0.0], 1.0)

    monkeypatch.setattr(service_module, "word_starts", heard)
    repository = SqliteProductRepository(tmp_path / "s.db")
    await repository.upsert_detail({"product_id": PRODUCT_ID, "title": "Áo", "images": ["u"]})
    shots = [{"voiceover": LONG, "duration_seconds": 15}]
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
    return repository, _Speaker()


@needs_ffmpeg
async def test_a_line_too_long_for_its_shot_is_shortened_saved_and_read_again(
    tmp_path, monkeypatch
) -> None:
    repository, speaker = await _ready(tmp_path, monkeypatch)
    shortener = _Shortener("Áo cotton mềm mát, giá chỉ 199k")
    service = ProductCatalogService(
        repository,
        speaker=speaker,  # type: ignore[arg-type]
        voice_shortener=shortener,  # type: ignore[arg-type]
    )
    made = await service.create_voiceover(PRODUCT_ID, tmp_path)
    assert made["too_long_shots"] == []
    assert shortener.calls == 1 and len(speaker.read) == 2  # the long line, then the short one
    record = await repository.get_brief(PRODUCT_ID)
    assert record["brief"]["shots"][0]["voiceover"] == "Áo cotton mềm mát, giá chỉ 199k"


@needs_ffmpeg
async def test_a_refused_shortening_leaves_the_line_and_the_warning(tmp_path, monkeypatch) -> None:
    repository, speaker = await _ready(tmp_path, monkeypatch)
    service = ProductCatalogService(
        repository,
        speaker=speaker,  # type: ignore[arg-type]
        voice_shortener=_Shortener(None),  # type: ignore[arg-type]
    )
    made = await service.create_voiceover(PRODUCT_ID, tmp_path)
    assert made["too_long_shots"] == [1] and len(speaker.read) == 1
    assert (await repository.get_brief(PRODUCT_ID))["brief"]["shots"][0]["voiceover"] == LONG


@needs_ffmpeg
async def test_without_a_shortener_the_long_line_is_only_reported(tmp_path, monkeypatch) -> None:
    repository, speaker = await _ready(tmp_path, monkeypatch)
    service = ProductCatalogService(repository, speaker=speaker)  # type: ignore[arg-type]
    assert (await service.create_voiceover(PRODUCT_ID, tmp_path))["too_long_shots"] == [1]
