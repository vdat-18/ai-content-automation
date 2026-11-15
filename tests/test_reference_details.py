from types import SimpleNamespace

import httpx
from tests.pgstore import product_repository

from ai_content.domains.marketing.products.briefing import reference_note, reference_search_text
from ai_content.domains.marketing.products.image_review import ReferenceImageReviewer
from ai_content.domains.marketing.products.service import ProductCatalogService

FULL = {
    "score": 4,
    "description": "A bathroom shelf with a pump bottle in soft window light.",
    "reject_reason": None,
    "setting": "bathroom shelf",
    "surface_and_props": ["marble", "towel"],
    "lighting": "soft window light from the left",
    "color_palette": ["beige", "white"],
    "style": ["minimal"],
    "camera": "eye level, medium shot",
    "people": "none",
    "placement": "centre of the shelf, bottle about hand sized",
    "fits_products": ["skincare", "cleaning"],
    "motion_ideas": ["slow push-in"],
}


def _reviewer(reply: dict) -> ReferenceImageReviewer:
    class Client:
        async def ReviewReferenceImage(self, image):  # noqa: N802
            return SimpleNamespace(model_dump=lambda: dict(reply))

    return ReferenceImageReviewer(Client())  # type: ignore[arg-type]


def _http() -> httpx.AsyncClient:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"img"))
    return httpx.AsyncClient(transport=transport)


async def test_a_full_review_is_kept_with_all_its_detail() -> None:
    result = await _reviewer(FULL).review_all(
        [{"image_id": "a", "image_url": "https://x/a.jpg", "product_type": "lotion"}], _http()
    )
    assert result["a"]["setting"] == "bathroom shelf" and result["a"]["usable"] is True


async def test_a_review_cut_off_half_way_does_not_pass_as_a_review() -> None:
    cut = {**FULL, "setting": None, "lighting": None, "camera": None, "placement": None}
    result = await _reviewer(cut).review_all(
        [{"image_id": "a", "image_url": "https://x/a.jpg", "product_type": "lotion"}], _http()
    )
    assert result == {"a": None}


async def test_an_unusable_image_needs_no_detail() -> None:
    plain = {
        "score": 1,
        "description": "plain white backdrop",
        "reject_reason": "studio",
    }
    reply = {**dict.fromkeys(FULL), **plain}
    result = await _reviewer(reply).review_all(
        [{"image_id": "a", "image_url": "https://x/a.jpg", "product_type": "lotion"}], _http()
    )
    assert result["a"]["usable"] is False


def test_the_brief_writer_gets_every_detail_of_the_picture() -> None:
    note = reference_note({"screening": FULL})
    for expected in (
        "bathroom shelf",
        "soft window light from the left",
        "beige, white",
        "eye level, medium shot",
        "centre of the shelf",
        "skincare, cleaning",
        "slow push-in",
    ):
        assert expected in note
    assert reference_note({"screening": {"description": "old short review"}}) == "old short review"


def test_a_picture_is_found_by_its_description_alone() -> None:
    assert reference_search_text({"screening": FULL}) == FULL["description"]
    assert reference_search_text({"screening": {"scene_description": "old", "placement_note": "p"}}) == "old p"
    assert reference_search_text({}) == ""


async def test_a_low_score_is_not_usable_and_three_is() -> None:
    for score, usable in ((2, False), (3, True)):
        [result] = (
            await _reviewer({**FULL, "score": score}).review_all(
                [{"image_id": "a", "image_url": "https://x/a.jpg"}], _http()
            )
        ).values()
        assert result["usable"] is usable


async def test_old_reviews_get_their_detail_and_keep_their_status(tmp_path) -> None:
    repository = product_repository()
    await repository.add_reference_images(
        "lotion",
        "q",
        [{"image_id": "old", "image_url": "https://x/old.jpg", "pin_url": "/p/", "title": "old"}],
    )
    await repository.set_image_screening("old", {"usable": True, "description": "short"}, "live")

    class Reviewer:
        async def review_all(self, images):
            return {image["image_id"]: dict(FULL) for image in images}

    service = ProductCatalogService(repository, reviewer=Reviewer())  # type: ignore[arg-type]
    assert await service.redescribe_images(10) == {"described": 1, "failed": 0, "left": 0}
    [image] = await service.reference_images(None, "lotion")
    assert image["status"] == "live" and image["screening"]["setting"] == "bathroom shelf"
    # nothing left to describe
    assert (await service.redescribe_images(10))["described"] == 0
