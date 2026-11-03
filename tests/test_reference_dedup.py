import io

import pytest
from PIL import Image

from ai_content.domains.marketing.products import service as service_module
from ai_content.domains.marketing.products.embedding import dhash, hamming
from ai_content.domains.marketing.products.references import ProfileGenerationError
from ai_content.domains.marketing.products.repositories import SqliteProductRepository
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
    repository = SqliteProductRepository(tmp_path / "d.db")
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
    service = ProductCatalogService(SqliteProductRepository(tmp_path / "n.db"))
    with pytest.raises(ProfileGenerationError, match="disabled"):
        await service.backfill_fingerprints()
