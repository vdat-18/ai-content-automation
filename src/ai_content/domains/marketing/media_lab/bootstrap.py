"""Composition root for Media Asset storage."""

from __future__ import annotations

from pathlib import Path

from ai_content.platform.artifacts import ArtifactStore

from .adapters.asset_artifacts import FilesystemMediaAssetArtifacts
from .adapters.asset_preprocessing import MediaPreprocessor
from .adapters.asset_sqlite_repository import SqliteMediaAssetRepository
from .application.assets import MediaAssetService
from .domain.assets import MediaAssetLimits
from .ports.assets import IMediaAssetArtifacts, IMediaAssetRepository, IMediaPreprocessor


def build_media_asset_runtime(
    db_path: Path,
    artifacts_root: Path,
    limits: MediaAssetLimits,
    *,
    repository: IMediaAssetRepository | None = None,
    artifacts: IMediaAssetArtifacts | None = None,
    preprocessor: IMediaPreprocessor | None = None,
) -> MediaAssetService:
    return MediaAssetService(
        repository or SqliteMediaAssetRepository(db_path),
        artifacts or FilesystemMediaAssetArtifacts(ArtifactStore(artifacts_root)),
        limits,
        preprocessor or MediaPreprocessor(limits),
    )
