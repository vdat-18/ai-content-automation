"""Local image embeddings (DINO family, ONNX on CPU) and perceptual hashes for deduplication."""

from __future__ import annotations

import asyncio
import io
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
import onnxruntime as ort
from loguru import logger
from PIL import Image

_HF = "https://huggingface.co"
_INPUT_SIZE = 224
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)


@dataclass(frozen=True)
class EmbeddingModel:
    repo: str
    files: tuple[str, ...]


MODELS: dict[str, EmbeddingModel] = {
    "dinov2-small": EmbeddingModel("onnx-community/dinov2-small", ("onnx/model.onnx",)),
    "dinov3-vits16": EmbeddingModel(
        "onnx-community/dinov3-vits16-pretrain-lvd1689m-ONNX",
        ("onnx/model.onnx", "onnx/model.onnx_data"),
    ),
}


def dhash(content: bytes) -> int:
    """64-bit difference hash: robust to resizing and re-compression."""
    with Image.open(io.BytesIO(content)) as image:
        gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = np.asarray(gray, dtype=np.int16)
    bits = (pixels[:, 1:] > pixels[:, :-1]).flatten()
    return int("".join("1" if bit else "0" for bit in bits), 2)


def hamming(first: int, second: int) -> int:
    return (first ^ second).bit_count()


class ImageEmbedder:
    """Download an ONNX DINO model once and turn images into unit-length vectors."""

    def __init__(self, model_name: str, cache_dir: Path) -> None:
        if model_name not in MODELS:
            raise ValueError(f"Unknown embedding model {model_name!r}; use one of {sorted(MODELS)}")
        self.name = model_name
        self._model = MODELS[model_name]
        self._directory = cache_dir / model_name
        self._session: ort.InferenceSession | None = None
        self._lock = threading.Lock()

    def _load(self) -> ort.InferenceSession:
        with self._lock:
            if self._session is None:
                self._directory.mkdir(parents=True, exist_ok=True)
                for file in self._model.files:
                    self._download(file)
                path = self._directory / Path(self._model.files[0]).name
                self._session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
            return self._session

    def _download(self, file: str) -> None:
        target = self._directory / Path(file).name
        if target.exists():
            return
        logger.info("Downloading embedding model file {}/{}", self._model.repo, file)
        partial = target.with_suffix(target.suffix + ".part")
        url = f"{_HF}/{self._model.repo}/resolve/main/{file}"
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes(1 << 20):
                    handle.write(chunk)
        partial.replace(target)

    def embed(self, content: bytes) -> list[float]:
        """Return the L2-normalized class-token embedding of one image."""
        with Image.open(io.BytesIO(content)) as image:
            resized = image.convert("RGB").resize(
                (_INPUT_SIZE, _INPUT_SIZE), Image.Resampling.BICUBIC
            )
        pixels = np.asarray(resized, dtype=np.float32).transpose(2, 0, 1) / 255.0
        batch = ((pixels - _MEAN) / _STD)[None]
        session = self._load()
        hidden = session.run(None, {session.get_inputs()[0].name: batch})[0]
        vector = hidden[0, 0].astype(np.float64)
        return (vector / np.linalg.norm(vector)).tolist()

    async def embed_many(self, contents: list[bytes]) -> list[list[float]]:
        return await asyncio.to_thread(lambda: [self.embed(content) for content in contents])


def cosine(first: list[float], second: list[float]) -> float:
    return float(np.dot(first, second))


async def download_images(
    urls: list[str], http: httpx.AsyncClient | None = None
) -> dict[str, bytes]:
    """Fetch images concurrently; failures are logged and left out of the result."""
    semaphore = asyncio.Semaphore(4)
    owned = http is None
    http = http or httpx.AsyncClient(timeout=30, follow_redirects=True)

    async def fetch(url: str) -> tuple[str, bytes | None]:
        async with semaphore:
            try:
                response = await http.get(url)
                response.raise_for_status()
            except httpx.HTTPError as error:
                logger.warning("Image download failed: {}", str(error)[:200])
                return url, None
            return url, response.content

    try:
        return {url: data for url, data in await asyncio.gather(*map(fetch, urls)) if data}
    finally:
        if owned:
            await http.aclose()
