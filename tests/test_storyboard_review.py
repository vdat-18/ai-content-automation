from types import SimpleNamespace

from baml_py.baml_py import BamlError
from tests.test_product_briefs import HTML, PIN, PRODUCT_ID, URL

from ai_content.domains.marketing.products.repositories import SqliteProductRepository
from ai_content.domains.marketing.products.service import ProductCatalogService
from ai_content.domains.marketing.products.storyboard_review import StoryboardReviewer

SHOT = {"keyframe_prompt": "k", "motion_prompt": "m", "voiceover": "v"}


def _reviewer(reply=None, error: Exception | None = None) -> StoryboardReviewer:
    class Client:
        async def ReviewStoryboard(self, product_json, brief_json):  # noqa: N802
            if error:
                raise error
            return SimpleNamespace(**reply)

    return StoryboardReviewer(Client())  # type: ignore[arg-type]


async def test_a_passing_review_has_no_problems() -> None:
    reviewer = _reviewer({"passed": True, "problems": []})
    assert await reviewer.review({}, {"shots": [SHOT]}) == []


async def test_a_failing_review_says_where_what_and_how_to_fix() -> None:
    problem = SimpleNamespace(
        where=" shot 2 motion_prompt ", problem=" Only drifts. ", fix=" Add a 3 to 6s beat. "
    )
    reviewer = _reviewer({"passed": False, "problems": [problem]})
    assert await reviewer.review({}, {"shots": [SHOT]}) == [
        "shot 2 motion_prompt: Only drifts. Fix: Add a 3 to 6s beat."
    ]


async def test_a_rejection_without_reasons_still_counts_as_a_failure() -> None:
    reviewer = _reviewer({"passed": False, "problems": []})
    assert await reviewer.review({}, {"shots": [SHOT]})


async def test_a_review_that_could_not_run_is_unchecked_not_passed() -> None:
    reviewer = _reviewer(error=BamlError("down"))
    assert await reviewer.review({}, {"shots": [SHOT]}) is None


class _Writer:
    def __init__(self) -> None:
        self.ideas: list[str] = []

    async def write(self, product, user_idea, shot_count=1):
        self.ideas.append(user_idea)
        return {"title": "T", "shots": [SHOT] * shot_count}


class _Judge:
    """Rejects the first `bad` storyboards, then accepts."""

    def __init__(self, bad: int, unchecked: bool = False) -> None:
        self.bad = bad
        self.unchecked = unchecked
        self.calls = 0

    async def review(self, product, brief):
        self.calls += 1
        if self.unchecked:
            return None
        return ["Shot 1: add visible action."] if self.calls <= self.bad else []


async def _service(tmp_path, writer, judge):
    service = ProductCatalogService(
        SqliteProductRepository(tmp_path / "q.db"),
        briefer=writer,
        storyboard_reviewer=judge,  # type: ignore[arg-type]
    )
    await service.ingest({"kind": "page", "url": URL, "html": HTML})
    await service._repository.select_product(PRODUCT_ID, "áo thun")
    await service.ingest(
        {"kind": "pinterest", "product_type": "áo thun", "query": "q", "pins": [PIN]}
    )
    [image] = await service.reference_images("pending", "áo thun")
    await service.set_image_status(image["image_id"], "live")
    return service


async def test_a_rejected_storyboard_is_rewritten_with_the_reviewers_notes(tmp_path) -> None:
    writer, judge = _Writer(), _Judge(bad=1)
    service = await _service(tmp_path, writer, judge)
    record = await service.create_brief(PRODUCT_ID, "my idea", video_seconds=30)
    assert len(writer.ideas) == 2 and writer.ideas[0] == "my idea"
    assert "Shot 1: add visible action." in writer.ideas[1]
    assert record["user_idea"] == "my idea"
    assert record["brief"]["quality_problems"] == []
    last = (await service.events(PRODUCT_ID))[-1]
    assert last["status"] == "ok" and "2 attempt(s)" in last["message"]


async def test_problems_that_survive_every_attempt_are_reported(tmp_path) -> None:
    writer, judge = _Writer(), _Judge(bad=99)
    service = await _service(tmp_path, writer, judge)
    record = await service.create_brief(PRODUCT_ID, video_seconds=30)
    assert len(writer.ideas) == 3
    assert record["brief"]["quality_problems"] == ["Shot 1: add visible action."]
    assert (await service.events(PRODUCT_ID))[-1]["status"] == "flagged"


async def test_an_unavailable_reviewer_does_not_block_the_brief(tmp_path) -> None:
    writer = _Writer()
    service = await _service(tmp_path, writer, _Judge(bad=0, unchecked=True))
    record = await service.create_brief(PRODUCT_ID, video_seconds=30)
    assert len(writer.ideas) == 1 and record["brief"]["quality_problems"] == []


async def test_editing_a_brief_reviews_it_again(tmp_path) -> None:
    judge = _Judge(bad=0)
    service = await _service(tmp_path, _Writer(), judge)
    await service.create_brief(PRODUCT_ID, video_seconds=30)
    judge.bad, judge.calls = 99, 0
    # a title is not worth a review
    record = await service.update_brief(PRODUCT_ID, {"title": "New"}, "draft")
    assert judge.calls == 0 and record["brief"]["quality_problems"] == []
    changed = [{**SHOT, "voiceover": "edited"}] * 3
    record = await service.update_brief(PRODUCT_ID, {"shots": changed}, "draft")
    assert record["brief"]["quality_problems"] == ["Shot 1: add visible action."]
