from ai_content.domains.marketing.products.briefing import earlier_videos
from ai_content.domains.marketing.products.projects import product_of


def test_a_project_belongs_to_the_product_before_its_suffix() -> None:
    assert product_of("1730000000000000001") == "1730000000000000001"
    assert product_of("1730000000000000001-v2") == "1730000000000000001"


def test_the_earlier_videos_are_listed_with_their_script_and_place() -> None:
    brief = {"title": "Dai khong rach", "scene": "a kitchen", "script": "Ban bi tham nuoc?"}
    assert earlier_videos([brief]) == "1. Dai khong rach (place: a kitchen)\nBan bi tham nuoc?"
    assert earlier_videos([]) == ""


async def test_a_new_video_is_told_the_earlier_ones_and_a_product_keeps_all_of_them(tmp_path) -> None:
    from test_product_briefs import PRODUCT_ID, _make_reference_live, _service

    seen: list[str] = []

    class _Writer:
        async def write(
            self, product, user_idea, shot_count=1, person_photos=None, rules="", earlier=""
        ):
            seen.append(earlier)
            return {
                "title": f"Brief {len(seen)}",
                "selling_angle": "angle",
                "scene": "a kitchen",
                "shots": [{"role": "hook", "description": "d", "keyframe_prompt": "x"}] * shot_count,
            }

    service = await _service(tmp_path, _Writer())
    await service._repository.select_product(PRODUCT_ID, "áo thun")
    await _make_reference_live(service)
    second = f"{PRODUCT_ID}-v2"
    await service.create_brief(PRODUCT_ID, video_seconds=15, person_photos=[b"face"])
    await service.create_brief(second, video_seconds=15, person_photos=[b"face"])
    assert seen[0] == ""
    assert "Brief 1" in seen[1] and "a kitchen" in seen[1]
    assert {r["product_id"] for r in await service._repository.list_briefs()} == {PRODUCT_ID, second}
    assert await service.delete_product(PRODUCT_ID, tmp_path)
    assert await service._repository.list_briefs() == []  # every video of the product goes with it
