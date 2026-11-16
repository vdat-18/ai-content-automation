from pathlib import Path

import pytest
from tests.pgstore import product_repository

from ai_content.domains.marketing.products.service import (
    KeyframeUnavailable,
    ProductCatalogService,
    video_folder,
)


def _hook(text: str, angle: str = "question") -> dict[str, str]:
    return {"angle": angle, "text": text}


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
    repository = product_repository()
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


async def test_hooks_are_written_for_a_talking_opening_too(tmp_path) -> None:
    service = await _service(tmp_path, _Writer([_hook("Áo mát không?")]))
    await service._repository.save_brief(
        "42", "idea", {"title": "Áo", "shots": [{"delivery": "talking"}]}, "draft"
    )
    [saved] = await service.write_hooks("42", Path(tmp_path))
    assert saved["text"] == "Áo mát không?"
    [listed] = await service.hooks("42", Path(tmp_path))
    assert listed["filming"] is False and listed["built"] is False
