"""Test configuration."""

import hashlib
import io
import os
from pathlib import Path

import pytest
from PIL import Image
from tests.pgstore import forget_rows


@pytest.fixture(scope="session", autouse=True)
def _shared_whisper_models(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Keep the speech model between runs: tests look for it in `<temp base>/whisper`."""
    shared = os.environ.get("AIC_TEST_WHISPER_DIR")
    if shared:
        (tmp_path_factory.getbasetemp() / "whisper").symlink_to(shared, target_is_directory=True)


@pytest.fixture(autouse=True)
def _fresh_database() -> None:
    """Every test starts with an empty database (emptied when a test first asks for one)."""
    forget_rows()


@pytest.fixture
def project_root() -> Path:
    """Get project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def src_root(project_root: Path) -> Path:
    """Get src directory."""
    return project_root / "src" / "ai_content"


def _distinct_jpeg(seed: str) -> bytes:
    """A small image whose hash differs from every other seed's, so nothing counts as a duplicate."""
    digest = hashlib.sha256(seed.encode()).digest()
    image = Image.new("L", (72, 64))
    for column in range(9):
        for row in range(8):
            shade = digest[(column * 8 + row) % len(digest)]
            for x in range(column * 8, column * 8 + 8):
                for y in range(row * 8, row * 8 + 8):
                    image.putpixel((x, y), shade)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=95)
    return buffer.getvalue()


class _DistinctEmbedder:
    """Gives every image its own direction, so no two images look alike."""

    async def embed_many(self, contents: list[bytes]) -> list[list[float]]:
        vectors = []
        for content in contents:
            index = int(hashlib.sha1(content).hexdigest(), 16) % 512
            vector = [0.0] * 512
            vector[index] = 1.0
            vectors.append(vector)
        return vectors


@pytest.fixture(autouse=True)
def _reference_checks_that_find_nothing(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Most tests ingest Pinterest pins without caring about duplicates.

    The duplicate check refuses to run without an embedder and a download, so those tests get a
    check that finds every image new. The tests of the check itself (test_reference_dedup) opt out.
    """
    if request.module.__name__.endswith("test_reference_dedup"):
        return
    from ai_content.domains.marketing.products import service as service_module

    async def download(urls, http=None):
        return {url: _distinct_jpeg(url) for url in urls}

    monkeypatch.setattr(service_module, "download_images", download)
    original = service_module.ProductCatalogService.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        if self._embedder is None:
            self._embedder = _DistinctEmbedder()

    monkeypatch.setattr(service_module.ProductCatalogService, "__init__", init)
