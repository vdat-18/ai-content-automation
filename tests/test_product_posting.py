from types import SimpleNamespace

import pytest
from baml_py.baml_py import BamlClientError

from ai_content.domains.marketing.products.posting import (
    PostingPackageError,
    PostingPackageWriter,
)
from ai_content.domains.marketing.products.repositories import SqliteProductRepository
from ai_content.domains.marketing.products.service import (
    KeyframeUnavailable,
    ProductCatalogService,
)

PRODUCT_ID = "1730000000000000001"


class _FakeBaml:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.seen: list[tuple[str, str]] = []

    async def WritePostingPackage(self, product_json, brief_json):
        if self.fail:
            raise BamlClientError("503", "503", "503")
        self.seen.append((product_json, brief_json))
        return SimpleNamespace(
            captions=[" Một ", "", "Hai"], hashtags=["#TikTokShop", "gọn gàng", "#tiktokshop", " "]
        )


async def test_writer_cleans_hashtags_and_keeps_only_text_the_model_should_see() -> None:
    client = _FakeBaml()
    brief = {
        "title": "T",
        "scene": "s",
        "image_prompt": "NEVER SENT",
        "shots": [{"role": "hook", "keyframe_prompt": "NEVER SENT", "voiceover": "v"}],
    }
    package = await PostingPackageWriter(client).write(
        {"title": "Giỏ", "url": "https://shop/p/1"}, brief
    )
    assert package == {
        "captions": ["Một", "Hai"],
        "hashtags": ["#tiktokshop", "#gọngàng"],
        "product_url": "https://shop/p/1",
    }
    assert "NEVER SENT" not in client.seen[0][1] and '"voiceover": "v"' in client.seen[0][1]


async def test_writer_reports_model_errors() -> None:
    with pytest.raises(PostingPackageError):
        await PostingPackageWriter(_FakeBaml(fail=True)).write({}, {})


async def test_service_keeps_the_package_on_the_brief_across_edits(tmp_path) -> None:
    repository = SqliteProductRepository(tmp_path / "p.db")
    service = ProductCatalogService(repository, poster=PostingPackageWriter(_FakeBaml()))
    assert await service.create_post_package(PRODUCT_ID) is None
    await repository.upsert_detail({"product_id": PRODUCT_ID, "title": "Giỏ", "images": []})
    await repository.save_brief(PRODUCT_ID, "ý", {"title": "T", "scene": "a"}, "approved")

    package = await service.create_post_package(PRODUCT_ID)
    assert package is not None and package["captions"] == ["Một", "Hai"]
    edited = await service.update_brief(PRODUCT_ID, {"scene": "b"}, "approved")
    assert edited is not None
    assert edited["brief"]["post_package"] == package and edited["brief"]["scene"] == "b"


async def test_service_needs_the_llm(tmp_path) -> None:
    repository = SqliteProductRepository(tmp_path / "p.db")
    service = ProductCatalogService(repository)
    await repository.upsert_detail({"product_id": PRODUCT_ID, "title": "Giỏ", "images": []})
    await repository.save_brief(PRODUCT_ID, "", {"title": "T"}, "approved")
    with pytest.raises(KeyframeUnavailable, match="not configured"):
        await service.create_post_package(PRODUCT_ID)


async def test_package_and_brief_carry_warnings_and_the_ai_label_reminder(tmp_path) -> None:
    repository = SqliteProductRepository(tmp_path / "w.db")

    class _Risky(_FakeBaml):
        async def WritePostingPackage(self, product_json, brief_json):
            return SimpleNamespace(captions=["Sọt tốt nhất!"], hashtags=["#sot"])

    service = ProductCatalogService(repository, poster=PostingPackageWriter(_Risky()))
    await repository.upsert_detail({"product_id": PRODUCT_ID, "title": "Giỏ", "images": []})
    await repository.save_brief(PRODUCT_ID, "", {"title": "T"}, "approved")
    package = await service.create_post_package(PRODUCT_ID)
    assert package is not None
    assert package["warnings"] == ['caption 1: "tốt nhất" (absolute claim)']
    assert "AI" in package["ai_label_reminder"]

    edited = await service.update_brief(PRODUCT_ID, {"selling_angle": "Rẻ nhất"}, "draft")
    assert edited is not None
    assert edited["brief"]["warnings"] == ['selling_angle: "rẻ nhất" (absolute claim)']
