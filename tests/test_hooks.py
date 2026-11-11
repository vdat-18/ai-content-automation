from pathlib import Path

import pytest

from ai_content.domains.marketing.products.hooks import passing_hooks
from ai_content.domains.marketing.products.repositories import SqliteProductRepository
from ai_content.domains.marketing.products.service import (
    KeyframeUnavailable,
    ProductCatalogService,
    video_folder,
)

FACTS = "sold_count: 3200, price 199000"


def _hook(text: str, angle: str = "question") -> dict[str, str]:
    return {"angle": angle, "text": text}


def test_only_short_clean_and_grounded_hooks_are_kept() -> None:
    hooks = [
        _hook("Áo mát thế này có tin không?"),
        _hook("Một hai ba bốn năm sáu bảy tám"),  # eight words
        _hook("Sản phẩm tốt nhất thị trường"),  # absolute claim
        _hook("Đã có 10.000 người mua rồi", "number"),  # number not in the product data
        _hook("Hơn 3.000 người đã mua", "number"),  # rounded down from 3,200
        _hook("áo mát thế này có tin không?"),  # same hook again
        _hook(""),
    ]
    assert [h["text"] for h in passing_hooks(hooks, FACTS)] == [
        "Áo mát thế này có tin không?",
        "Hơn 3.000 người đã mua",
    ]


def test_a_hook_variant_keeps_its_files_in_its_own_folder() -> None:
    assert video_folder("42") == "videos/42"
    assert video_folder("42", "hook_2") == "videos/42/hook_2"


class _Writer:
    def __init__(self, hooks) -> None:
        self.hooks = hooks

    async def write(self, product, brief, rules="", count=3):
        return self.hooks


async def _service(tmp_path, writer) -> ProductCatalogService:
    tmp_path.mkdir(parents=True, exist_ok=True)
    repository = SqliteProductRepository(tmp_path / "s.db")
    await repository.upsert_detail(
        {"product_id": "42", "title": "Áo", "price": {"sale": "99000"}, "images": ["u"]}
    )
    await repository.save_brief(
        "42", "idea", {"title": "Áo", "shots": [{"voiceover": "x"}]}, "draft"
    )
    return ProductCatalogService(repository, hook_writer=writer)  # type: ignore[arg-type]


async def test_hooks_are_saved_listed_and_need_the_model(tmp_path) -> None:
    root = Path(tmp_path)
    service = await _service(tmp_path, _Writer([_hook("Áo mát không?"), _hook("Mặc là mê ngay")]))
    saved = await service.write_hooks("42", root)
    assert [h["id"] for h in saved] == ["hook_1", "hook_2"]
    listed = await service.hooks("42", root)
    assert [h["text"] for h in listed] == ["Áo mát không?", "Mặc là mê ngay"]
    assert not any(h["built"] for h in listed)
    assert await service.build_hook_video("42", root, "hook_9") is None

    empty = await _service(tmp_path / "none", _Writer([]))
    with pytest.raises(KeyframeUnavailable, match="No hook passed"):
        await empty.write_hooks("42", root)
    unset = await _service(tmp_path / "unset", None)
    with pytest.raises(KeyframeUnavailable, match="not configured"):
        await unset.write_hooks("42", root)
