import io

import pytest
from PIL import Image
from tests.pgstore import product_repository

from ai_content.domains.marketing.products import service as service_module
from ai_content.domains.marketing.products.embedding import dhash, hamming
from ai_content.domains.marketing.products.references import ProfileGenerationError
from ai_content.domains.marketing.products.service import ProductCatalogService


def _jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def _gradient(horizontal: bool, size: int = 64) -> Image.Image:
    image = Image.new("RGB", (size, size))
    for x in range(size):
        for y in range(size):
            value = (x if horizontal else y) * 255 // (size - 1)
            image.putpixel((x, y), (value, value, value))
    return image


def _checker(size: int = 64) -> Image.Image:
    image = Image.new("RGB", (size, size))
    for x in range(size):
        for y in range(size):
            value = 255 if (x // 8 + y // 8) % 2 else 0
            image.putpixel((x, y), (value, 90, 255 - value))
    return image


BASE = _jpeg(_gradient(True))
RESIZED = _jpeg(_gradient(True, 96))
OTHER = _jpeg(_gradient(False))
LOOKALIKE = _jpeg(_checker())
VECTORS = {
    BASE: [1.0, 0.0, 0.0],
    RESIZED: [1.0, 0.0, 0.0],
    OTHER: [0.0, 1.0, 0.0],
    LOOKALIKE: [0.95, 0.31225, 0.0],
}
URLS = {
    "a": "https://i.pinimg.com/236x/aa/aa/aaaa.jpg",
    "resized": "https://i.pinimg.com/236x/ab/ab/abab.jpg",
    "other": "https://i.pinimg.com/236x/bb/bb/bbbb.jpg",
    "lookalike": "https://i.pinimg.com/236x/cc/cc/cccc.jpg",
}
CONTENT = {
    URLS["a"]: BASE,
    URLS["resized"]: RESIZED,
    URLS["other"]: OTHER,
    URLS["lookalike"]: LOOKALIKE,
}


class _FakeEmbedder:
    def __init__(self) -> None:
        self.embedded = 0

    async def embed_many(self, contents):
        self.embedded += len(contents)
        return [VECTORS[content] for content in contents]


@pytest.fixture(autouse=True)
def _fake_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    async def download(urls, http=None):
        return {
            url.replace("/236x/", "/736x/"): CONTENT[url]
            for url in CONTENT
            if url.replace("/236x/", "/736x/") in urls
        }

    monkeypatch.setattr(service_module, "download_images", download)


def _pin(name: str) -> dict[str, str]:
    return {"image_url": URLS[name], "pin_url": f"/pin/{name}/", "title": name}


def _crawl(*names: str) -> dict:
    return {
        "kind": "pinterest",
        "product_type": "áo thun",
        "query": "q",
        "pins": [_pin(name) for name in names],
    }


async def _service(tmp_path) -> tuple[ProductCatalogService, _FakeEmbedder]:
    embedder = _FakeEmbedder()
    repository = product_repository()
    return ProductCatalogService(repository, embedder=embedder), embedder  # type: ignore[arg-type]


def test_fixtures_behave_as_intended() -> None:
    assert hamming(dhash(BASE), dhash(RESIZED)) <= 4
    assert hamming(dhash(BASE), dhash(OTHER)) > 4
    assert hamming(dhash(BASE), dhash(LOOKALIKE)) > 4


async def test_duplicates_are_dropped_before_review(tmp_path) -> None:
    service, embedder = await _service(tmp_path)
    result = await service.ingest(_crawl("a", "other", "lookalike", "resized"))
    assert (result["added"], result["duplicates"]) == (2, 2)
    rows = {i["title"]: i for i in await service.reference_images(None, "áo thun")}
    assert rows["a"]["status"] == "pending" and rows["other"]["status"] == "pending"
    assert rows["lookalike"]["status"] == rows["resized"]["status"] == "duplicate"
    # the look-alike repeats image "a" by embedding, the resized copy by hash
    assert rows["lookalike"]["image_id"] != rows["a"]["image_id"]
    assert embedder.embedded == 4


async def test_known_images_are_not_embedded_again(tmp_path) -> None:
    service, embedder = await _service(tmp_path)
    await service.ingest(_crawl("a", "other"))
    assert embedder.embedded == 2
    again = await service.ingest(_crawl("a", "other"))
    assert (again["added"], again["duplicates"]) == (0, 0)
    assert embedder.embedded == 2


async def test_removed_images_still_block_their_copies(tmp_path) -> None:
    service, _ = await _service(tmp_path)
    await service.ingest(_crawl("a"))
    [first] = await service.reference_images(None, "áo thun")
    await service.set_image_status(first["image_id"], "removed")
    result = await service.ingest(_crawl("resized"))
    assert (result["added"], result["duplicates"]) == (0, 1)


async def test_backfill_fingerprints_old_images(tmp_path) -> None:
    service, _ = await _service(tmp_path)
    await service._repository.add_reference_images(  # noqa: SLF001
        "áo thun",
        "q",
        [
            {
                "image_id": "old",
                "image_url": URLS["a"].replace("/236x/", "/736x/"),
                "pin_url": "/p/",
                "title": "old",
            }
        ],
    )
    assert await service.backfill_fingerprints() == 1
    assert await service.backfill_fingerprints() == 0
    result = await service.ingest(_crawl("resized"))
    assert result["duplicates"] == 1


async def test_backfill_needs_an_embedder(tmp_path) -> None:
    service = ProductCatalogService(product_repository())
    with pytest.raises(ProfileGenerationError, match="disabled"):
        await service.backfill_fingerprints()


async def test_similarity_of_eighty_percent_counts_as_the_same_image(tmp_path, monkeypatch) -> None:
    near = _jpeg(_checker(48))
    far = _jpeg(_checker(40))
    VECTORS[near] = [0.85, 0.5268, 0.0]  # 85% like BASE: a copy from now on
    VECTORS[far] = [0.70, 0.7141, 0.0]  # 70% like BASE: still a different image
    CONTENT[URLS["a"].replace("a/aa", "n/nn")] = near
    URLS["near"] = URLS["a"].replace("aa/aa/aaaa", "dd/dd/dddd")
    URLS["far"] = URLS["a"].replace("aa/aa/aaaa", "ee/ee/eeee")
    CONTENT[URLS["near"]] = near
    CONTENT[URLS["far"]] = far
    service, _ = await _service(tmp_path)
    result = await service.ingest(_crawl("a", "near", "far"))
    assert (result["added"], result["duplicates"]) == (2, 1)
    rows = {i["title"]: i["status"] for i in await service.reference_images(None, "áo thun")}
    assert rows["near"] == "duplicate" and rows["far"] == "pending"


async def test_an_image_that_cannot_be_checked_is_flagged_not_passed(tmp_path, monkeypatch) -> None:
    service, _ = await _service(tmp_path)

    async def download(urls, http=None):
        return {}

    monkeypatch.setattr(service_module, "download_images", download)
    result = await service.ingest(_crawl("a"))
    assert (result["added"], result["duplicates"], result["check_failed"]) == (1, 0, 1)
    [row] = await service.reference_images(None, "áo thun")
    assert row["status"] == "check_failed"
    assert await service.reference_images("pending", "áo thun") == []


async def test_a_broken_embedder_stops_the_ingest_instead_of_letting_images_through(
    tmp_path,
) -> None:
    class Broken:
        async def embed_many(self, contents):
            raise RuntimeError("model file is missing")

    service = ProductCatalogService(product_repository(), embedder=Broken())  # type: ignore[arg-type]
    with pytest.raises(ProfileGenerationError, match="duplicate check failed"):
        await service.ingest(_crawl("a"))
    assert await service.reference_images(None, "áo thun") == []


async def test_ingest_without_an_embedder_is_refused(tmp_path) -> None:
    service = ProductCatalogService(product_repository())
    with pytest.raises(ProfileGenerationError, match="duplicate check is off"):
        await service.ingest(_crawl("a"))


async def test_recheck_applies_a_lower_threshold_to_stored_images(tmp_path) -> None:
    service, _ = await _service(tmp_path)
    repository = service._repository  # noqa: SLF001
    near = _jpeg(_checker(48))
    VECTORS[near] = [0.85, 0.5268, 0.0]
    await service.ingest(_crawl("a"))
    # an image stored back when only 90% counted as a copy
    await repository.add_reference_images(
        "áo thun",
        "q",
        [
            {
                "image_id": "late",
                "image_url": "https://x/late.jpg",
                "pin_url": "/p/",
                "title": "late",
                "phash": f"{dhash(near):016x}",
                "embedding": VECTORS[near],
            }
        ],
    )
    report = await service.recheck_duplicates()
    assert report["marked_duplicate"] == 1
    rows = {i["title"]: i["status"] for i in await service.reference_images(None, "áo thun")}
    assert rows["late"] == "duplicate" and rows["a"] == "pending"
