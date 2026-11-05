import pytest

from ai_content.domains.marketing.products.brief_quality import brief_quality_problems
from ai_content.domains.marketing.products.repositories import SqliteProductRepository
from ai_content.domains.marketing.products.service import ProductCatalogService

VOICE = "Căn hộ nhỏ mà quần áo bừa bãi thì ai cũng mệt, sọt lưới gấp gọn này cất vừa trong góc phòng giặt."


def _shot(size: str, move: str, action: str, voice: str = VOICE) -> dict:
    return {
        "keyframe_prompt": f"{size} of the woman from the character image holding the basket",
        "motion_prompt": (
            f"0 to 3s: {move} as she {action}; 3 to 6s: she lifts the basket up; "
            "6 to 9s: she presses it flat on the floor; 9 to 12s: she smiles at the camera"
        ),
        "voiceover": voice,
    }


GOOD = {
    "shots": [
        _shot("Close-up", "slow push-in", "grabs the handle"),
        _shot("Wide shot", "tracking move", "carries it to the shelf"),
        _shot("Medium shot", "quick pan", "drops clothes inside"),
    ]
}


def test_a_varied_storyboard_passes() -> None:
    assert brief_quality_problems(GOOD) == []


def test_no_storyboard_means_nothing_to_check() -> None:
    assert brief_quality_problems({"title": "t"}) == []


def test_every_shot_framed_and_moved_the_same_way_is_flagged() -> None:
    brief = {
        "shots": [
            _shot("Medium shot", "slow push-in", "grabs the handle"),
            _shot("Medium shot", "slow push-in", "carries it to the shelf"),
            _shot("Medium shot", "slow push-in", "drops clothes inside"),
        ]
    }
    problems = brief_quality_problems(brief)
    assert any("shot size" in problem for problem in problems)
    assert any("camera move" in problem for problem in problems)


def test_a_shot_without_timed_beats_is_flagged() -> None:
    shot = {**GOOD["shots"][0], "motion_prompt": "slow push-in on the basket"}
    problems = brief_quality_problems({"shots": [shot, *GOOD["shots"][1:]]})
    assert problems == [
        "Shot 1: motion_prompt has 0 timed beats; write at least 3 "
        "(for example '0 to 3s: ...') each with a new visible action."
    ]


def test_vague_words_are_flagged_only_when_they_pile_up() -> None:
    one = {**GOOD["shots"][0], "keyframe_prompt": "Close-up of a stunning basket"}
    two = {**GOOD["shots"][0], "keyframe_prompt": "Close-up of a stunning, modern basket"}
    assert brief_quality_problems({"shots": [one, *GOOD["shots"][1:]]}) == []
    problems = brief_quality_problems({"shots": [two, *GOOD["shots"][1:]]})
    assert problems == ["Shot 1: replace the vague words (modern, stunning) with what is seen."]


def test_a_voiceover_that_does_not_fit_a_shot_is_flagged() -> None:
    short = {**GOOD["shots"][0], "voiceover": "Mua ngay."}
    long = {**GOOD["shots"][1], "voiceover": " ".join(["từ"] * 60)}
    problems = brief_quality_problems({"shots": [short, long, GOOD["shots"][2]]})
    assert "Shot 1: voiceover has 2 words; 15 to 45 fit a 15 second shot." in problems
    assert "Shot 2: voiceover has 60 words; 15 to 45 fit a 15 second shot." in problems


def test_two_shots_with_the_same_motion_are_flagged() -> None:
    twin = {**GOOD["shots"][0], "keyframe_prompt": "Wide shot of the room"}
    problems = brief_quality_problems({"shots": [GOOD["shots"][0], twin, GOOD["shots"][2]]})
    assert any("Shots 1 and 2 describe almost the same motion" in problem for problem in problems)


class _Rewriter:
    """Writes a bad storyboard until it is told what is wrong, then a good one."""

    def __init__(self, always_bad: bool = False) -> None:
        self.always_bad = always_bad
        self.ideas: list[str] = []

    async def write(self, product, user_idea, references, shot_count=1):
        self.ideas.append(user_idea)
        bad = self.always_bad or len(self.ideas) == 1
        shots = [_shot("Medium shot", "slow push-in", "grabs it")] * 3 if bad else GOOD["shots"]
        return {"title": "T", "shots": shots[:shot_count]}


async def _ready_service(tmp_path, writer):
    from tests.test_product_briefs import HTML, PIN, PRODUCT_ID, URL

    service = ProductCatalogService(SqliteProductRepository(tmp_path / "q.db"), briefer=writer)
    await service.ingest({"kind": "page", "url": URL, "html": HTML})
    await service._repository.select_product(PRODUCT_ID, "áo thun")
    await service.ingest(
        {"kind": "pinterest", "product_type": "áo thun", "query": "q", "pins": [PIN]}
    )
    [image] = await service.reference_images("pending", "áo thun")
    await service.set_image_status(image["image_id"], "live")
    return service, PRODUCT_ID


async def test_a_weak_storyboard_is_rewritten_with_the_problems_in_hand(tmp_path) -> None:
    writer = _Rewriter()
    service, product_id = await _ready_service(tmp_path, writer)
    record = await service.create_brief(product_id, "my idea", video_seconds=45)
    assert len(writer.ideas) == 2
    assert writer.ideas[0] == "my idea"
    assert "Rewrite the storyboard and fix these problems" in writer.ideas[1]
    assert "shot size" in writer.ideas[1]
    assert record["user_idea"] == "my idea"
    assert record["brief"]["quality_problems"] == []
    events = await service.events(product_id)
    assert events[-1]["status"] == "ok" and "2 attempt(s)" in events[-1]["message"]


async def test_problems_that_survive_every_attempt_are_reported_not_hidden(tmp_path) -> None:
    writer = _Rewriter(always_bad=True)
    service, product_id = await _ready_service(tmp_path, writer)
    record = await service.create_brief(product_id, video_seconds=45)
    assert len(writer.ideas) == 3
    assert record["brief"]["quality_problems"]
    events = await service.events(product_id)
    assert events[-1]["status"] == "flagged" and "Still open" in events[-1]["message"]


async def test_editing_a_brief_checks_it_again(tmp_path) -> None:
    service, product_id = await _ready_service(tmp_path, _Rewriter())
    await service.create_brief(product_id, video_seconds=45)
    weak = {"shots": [_shot("Medium shot", "slow push-in", "grabs it")] * 3}
    record = await service.update_brief(product_id, weak, "draft")
    assert record["brief"]["quality_problems"]
    fixed = await service.update_brief(product_id, GOOD, "draft")
    assert fixed["brief"]["quality_problems"] == []


@pytest.fixture(autouse=True)
def _tests_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(".")
