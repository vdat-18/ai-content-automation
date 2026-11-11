import shutil
import subprocess
from pathlib import Path

import pytest

from ai_content.domains.marketing.creative_knowledge.models import KnowledgeStatus
from ai_content.domains.marketing.creative_knowledge.repositories import (
    SqliteCreativeKnowledgeRepository,
)
from ai_content.domains.marketing.creative_knowledge.service import CreativeKnowledgeService
from ai_content.domains.marketing.products.reference_ad import (
    FRAME_COUNT,
    ReferenceAdUnavailable,
    sample,
)
from ai_content.domains.marketing.products.repositories import SqliteProductRepository
from ai_content.domains.marketing.products.service import (
    KeyframeUnavailable,
    ProductCatalogService,
)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


class _Analyzer:
    def __init__(self, rules: list[str] | None) -> None:
        self.rules = rules
        self.seen: list[int] = []

    async def analyze(self, video: Path) -> list[str] | None:
        self.seen.append(video.stat().st_size)
        assert video.exists()
        self.video = video
        return self.rules


def _service(tmp_path, analyzer) -> tuple[ProductCatalogService, CreativeKnowledgeService]:
    knowledge = CreativeKnowledgeService(SqliteCreativeKnowledgeRepository(tmp_path / "k.db"))
    service = ProductCatalogService(
        SqliteProductRepository(tmp_path / "s.db"), knowledge=knowledge, ad_analyzer=analyzer
    )  # type: ignore[arg-type]
    return service, knowledge


async def test_the_structure_of_an_example_ad_becomes_proposed_rules_and_the_video_is_dropped(
    tmp_path,
) -> None:
    analyzer = _Analyzer(["Open with a question.", "Cut every 2 seconds."])
    service, knowledge = _service(tmp_path, analyzer)
    result = await service.learn_from_reference_ad(b"video-bytes")
    assert [r["text"] for r in result] == ["Open with a question.", "Cut every 2 seconds."]
    assert {r["status"] for r in result} == {"proposed"}
    assert analyzer.seen == [len(b"video-bytes")]
    assert not analyzer.video.exists()
    item = await knowledge.repository.get(result[0]["knowledge_id"])
    assert item.contributor == "reference-ad" and item.scope.asset_type == "brief"


async def test_a_rule_already_decided_is_not_put_back_to_proposed(tmp_path) -> None:
    service, knowledge = _service(tmp_path, _Analyzer(["Open with a question."]))
    [first] = await service.learn_from_reference_ad(b"x")
    await knowledge.decide(first["knowledge_id"], status=KnowledgeStatus.REJECTED, reviewer="user")
    [again] = await service.learn_from_reference_ad(b"x")
    assert again["status"] == "rejected"


async def test_it_needs_the_model_and_an_answer(tmp_path) -> None:
    service, _ = _service(tmp_path, None)
    with pytest.raises(KeyframeUnavailable, match="not configured"):
        await service.learn_from_reference_ad(b"x")
    service, _ = _service(tmp_path, _Analyzer(None))
    with pytest.raises(KeyframeUnavailable, match="try again"):
        await service.learn_from_reference_ad(b"x")


@needs_ffmpeg
async def test_frames_and_cuts_are_measured(tmp_path) -> None:
    video = tmp_path / "ad.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=360x640:d=2",
         "-f", "lavfi", "-i", "color=blue:s=360x640:d=2", "-filter_complex", "concat=n=2:v=1:a=0",
         str(video)], check=True,
    )  # fmt: skip
    frames, times, cuts = await sample(video, tmp_path)
    assert len(frames) == len(times) and 30 <= len(frames) <= FRAME_COUNT
    assert len(cuts) == 1 and 1.8 < cuts[0] < 2.2
    with pytest.raises(ReferenceAdUnavailable):
        await sample(tmp_path / "missing.mp4", tmp_path)
