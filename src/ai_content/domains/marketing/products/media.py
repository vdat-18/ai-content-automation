"""Download product images and videos once, skipping files already stored."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
}
_MANIFEST = "manifest.json"


@dataclass
class MediaDownloadReport:
    downloaded: int = 0
    duplicates: int = 0
    skipped: int = 0
    failed: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def _targets(product: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (file stem, url) pairs for a product's images and best video."""
    items = [
        (f"image_{i + 1:02d}", url) for i, url in enumerate(product.get("images") or []) if url
    ]
    raw = product.get("raw_product_info") or {}
    video = raw.get("header_video") or raw.get("desc_video") or {}
    infos = [info for info in video.get("video_infos") or [] if info.get("main_url")]
    if infos:
        best = max(infos, key=lambda info: (info.get("height") or 0, info.get("size") or 0))
        items.append(("video", best["main_url"]))
    return items


async def download_product_media(
    products: list[dict[str, Any]], root: Path, client: httpx.AsyncClient | None = None
) -> MediaDownloadReport:
    """Save media under root/<product_id>/ and skip bytes already seen (by SHA-256)."""
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / _MANIFEST
    seen: dict[str, str] = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    report = MediaDownloadReport()
    owned = client is None
    client = client or httpx.AsyncClient(timeout=60, follow_redirects=True)
    try:
        for product in products:
            folder = root / str(product["product_id"])
            for stem, url in _targets(product):
                if any(folder.glob(f"{stem}.*")):
                    report.skipped += 1
                    continue
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                except httpx.HTTPError:
                    report.failed += 1
                    continue
                digest = hashlib.sha256(response.content).hexdigest()
                if digest in seen:
                    report.duplicates += 1
                    continue
                kind = response.headers.get("content-type", "").split(";")[0]
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"{stem}{_EXTENSIONS.get(kind, '.bin')}"
                path.write_bytes(response.content)
                seen[digest] = str(path.relative_to(root))
                report.downloaded += 1
    finally:
        if owned:
            await client.aclose()
        manifest_path.write_text(json.dumps(seen, indent=2), encoding="utf-8")
    return report
