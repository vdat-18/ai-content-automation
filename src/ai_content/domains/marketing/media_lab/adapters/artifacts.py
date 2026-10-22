"""Filesystem artifacts owned by Media Lab image runs."""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path, PurePosixPath

from PIL import Image

from ai_content.platform.artifacts import ArtifactStore

from ..domain.models import ImageBinary, ImageOutputFormat, ImageRun
from .serialization import run_to_dict


class MediaLabImageArtifacts:
    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    def write_source(self, run_id: str, reference_id: str, image: ImageBinary) -> tuple[str, str]:
        checksum = hashlib.sha256(image.content).hexdigest()
        path = self._store.write_bytes(
            image.content,
            "media-lab",
            "image-runs",
            run_id,
            "sources",
            f"{reference_id}{image.extension}",
        )
        return self._relative(path), checksum

    def write_output(self, run_id: str, content: bytes, extension: str) -> tuple[str, str]:
        checksum = hashlib.sha256(content).hexdigest()
        path = self._store.write_bytes(
            content,
            "media-lab",
            "image-runs",
            run_id,
            "outputs",
            f"final{extension}",
        )
        return self._relative(path), checksum

    def write_delivery(
        self,
        run_id: str,
        content: bytes,
        content_type: str,
        output_format: ImageOutputFormat,
    ) -> tuple[str, str, str]:
        output, extension, delivery_content_type = _convert_delivery(
            content, content_type, output_format
        )
        checksum = hashlib.sha256(output).hexdigest()
        path = self._store.write_bytes(
            output,
            "media-lab",
            "image-runs",
            run_id,
            "deliveries",
            f"final{extension}",
        )
        return self._relative(path), checksum, delivery_content_type

    def write_manifest(self, run: ImageRun) -> str:
        content = json.dumps(run_to_dict(run), ensure_ascii=False, indent=2, sort_keys=True)
        path = self._store.write_text(
            content,
            "media-lab",
            "image-runs",
            run.run_id,
            "manifest.json",
        )
        return self._relative(path)

    def read(self, artifact_ref: str) -> bytes:
        target = self._store.path(*PurePosixPath(artifact_ref).parts)
        if not target.is_file():
            raise FileNotFoundError(artifact_ref)
        return target.read_bytes()

    def output_path(self, artifact_ref: str) -> Path:
        return self._store.path(*PurePosixPath(artifact_ref).parts)

    def _relative(self, path: Path) -> str:
        return path.relative_to(self._store.root).as_posix()


def _convert_delivery(
    content: bytes,
    content_type: str,
    output_format: ImageOutputFormat,
) -> tuple[bytes, str, str]:
    if content_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise ValueError("Media Lab image output has an unsupported content type")
    try:
        with Image.open(BytesIO(content)) as opened:
            opened.load()
            image = opened.copy()
    except OSError as error:
        raise ValueError("Media Lab image output could not be decoded") from error

    output = BytesIO()
    if output_format == ImageOutputFormat.PNG:
        image.save(output, format="PNG", optimize=True)
        return output.getvalue(), ".png", "image/png"
    if output_format == ImageOutputFormat.JPEG:
        if image.mode not in {"RGB", "L"}:
            base = Image.new("RGB", image.size, "white")
            base.paste(image, mask=image.getchannel("A") if "A" in image.getbands() else None)
            image = base
        else:
            image = image.convert("RGB")
        image.save(output, format="JPEG", quality=95, optimize=True, progressive=True)
        return output.getvalue(), ".jpg", "image/jpeg"
    if output_format == ImageOutputFormat.WEBP:
        image.save(output, format="WEBP", quality=95, method=6)
        return output.getvalue(), ".webp", "image/webp"
    raise ValueError("Media Lab image delivery format is invalid")


__all__ = ["MediaLabImageArtifacts"]
