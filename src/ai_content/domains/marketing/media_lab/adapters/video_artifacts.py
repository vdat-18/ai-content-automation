"""Filesystem artifacts owned by Media Lab video runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from ai_content.platform.artifacts import ArtifactStore

from ..domain.models import ImageBinary
from ..domain.video_models import VideoRun
from .video_serialization import video_run_to_dict


class MediaLabVideoArtifacts:
    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    def write_source(self, run_id: str, reference_id: str, image: ImageBinary) -> tuple[str, str]:
        checksum = hashlib.sha256(image.content).hexdigest()
        path = self._store.write_bytes(
            image.content,
            "media-lab",
            "video-runs",
            run_id,
            "sources",
            f"{reference_id}{image.extension}",
        )
        return self._relative(path), checksum

    def write_output(self, run_id: str, content: bytes) -> tuple[str, str]:
        checksum = hashlib.sha256(content).hexdigest()
        path = self._store.write_bytes(
            content,
            "media-lab",
            "video-runs",
            run_id,
            "outputs",
            "final.mp4",
        )
        return self._relative(path), checksum

    def write_review_frame(
        self,
        run_id: str,
        frame_index: int,
        image: ImageBinary,
    ) -> tuple[str, str]:
        checksum = hashlib.sha256(image.content).hexdigest()
        path = self._store.write_bytes(
            image.content,
            "media-lab",
            "video-runs",
            run_id,
            "review-frames",
            f"frame-{frame_index:02d}{image.extension}",
        )
        return self._relative(path), checksum

    def write_manifest(self, run: VideoRun) -> str:
        content = json.dumps(video_run_to_dict(run), ensure_ascii=False, indent=2, sort_keys=True)
        path = self._store.write_text(
            content,
            "media-lab",
            "video-runs",
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


__all__ = ["MediaLabVideoArtifacts"]
