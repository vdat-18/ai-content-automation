"""Turn short English texts into vectors with an OpenAI-compatible embeddings endpoint."""

from __future__ import annotations

import httpx

_BATCH = 64
_TIMEOUT = 90


class TextEmbeddingError(RuntimeError):
    """The embedding model did not return vectors."""


class TextEmbedder:
    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._url = base_url.rstrip("/") + "/embeddings"
        self._key = api_key
        self.model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
            for start in range(0, len(texts), _BATCH):
                batch = texts[start : start + _BATCH]
                try:
                    response = await http.post(
                        self._url,
                        json={"model": self.model, "input": batch},
                        headers={"Authorization": f"Bearer {self._key}"},
                    )
                    response.raise_for_status()
                    rows = sorted(response.json()["data"], key=lambda row: row["index"])
                except (httpx.HTTPError, KeyError, ValueError) as error:
                    raise TextEmbeddingError(f"Embedding request failed: {error}") from error
                if len(rows) != len(batch):
                    raise TextEmbeddingError("The embedding model returned too few vectors")
                vectors += [[float(x) for x in row["embedding"]] for row in rows]
        return vectors
