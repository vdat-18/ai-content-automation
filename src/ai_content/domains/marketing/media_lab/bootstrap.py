"""Composition root for persisted Media Lab image and video workflow slices."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_content.platform.ai_usage import AIUsageTracker
from ai_content.platform.artifacts import ArtifactStore

from .adapters.artifacts import MediaLabImageArtifacts
from .adapters.asset_artifacts import FilesystemMediaAssetArtifacts
from .adapters.asset_preprocessing import MediaPreprocessor
from .adapters.asset_sqlite_repository import SqliteMediaAssetRepository
from .adapters.baml_orchestration import BamlMediaLabImageOrchestrator
from .adapters.baml_video_orchestration import BamlMediaLabVideoOrchestrator
from .adapters.planning_job_sqlite_repository import SqliteMediaLabPlanningJobRepository
from .adapters.sqlite_repository import SqliteMediaLabImageRepository
from .adapters.video_ad_sqlite_repository import SqliteMediaLabVideoAdRepository
from .adapters.video_artifacts import MediaLabVideoArtifacts
from .adapters.video_candidate_selector import FfmpegVideoCandidateSelector
from .adapters.video_compositor import FfmpegVideoCompositor
from .adapters.video_frames import FfmpegVideoFrameSampler
from .adapters.video_project_sqlite_repository import (
    SqliteMediaLabVideoProjectRepository,
)
from .adapters.video_sqlite_repository import SqliteMediaLabVideoRepository
from .application.assets import MediaAssetService
from .application.image_runs import MediaLabImageService
from .application.orchestration import MediaLabImageOrchestrationService
from .application.planning_jobs import MediaLabPlanningJobService
from .application.video_ads import MediaLabVideoAdService
from .application.video_orchestration import MediaLabVideoOrchestrationService
from .application.video_projects import MediaLabVideoProjectService
from .application.video_runs import MediaLabVideoService
from .config.orchestration import (
    MediaLabVideoVerifierConfig,
    load_media_lab_image_orchestrator_config,
    load_media_lab_video_orchestrator_config,
)
from .domain.assets import MediaAssetLimits
from .domain.models import ImageCapability
from .domain.video_models import VideoCapability
from .ports.assets import IMediaAssetArtifacts, IMediaAssetRepository, IMediaPreprocessor
from .ports.interfaces import IImageGenerationBackend, IImageQualityReviewer, IImageRunRepository
from .ports.planning_jobs import IPlanningJobRepository
from .ports.video_ads import IVideoAdPlanner, IVideoAdRepository
from .ports.video_interfaces import (
    IImageOutputSource,
    IVideoEvidenceVerifier,
    IVideoFrameSampler,
    IVideoGenerationBackend,
    IVideoQualityReviewer,
    IVideoRunRepository,
)
from .ports.video_projects import IVideoProjectRepository


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


def build_runtime(
    db_path: Path,
    artifacts_root: Path,
    generator: IImageGenerationBackend,
    *,
    repository: IImageRunRepository | None = None,
    quality_reviewer: IImageQualityReviewer | None = None,
    media_assets: MediaAssetService | None = None,
) -> MediaLabImageService:
    active_repository = repository or SqliteMediaLabImageRepository(db_path)
    return MediaLabImageService(
        active_repository,
        MediaLabImageArtifacts(ArtifactStore(artifacts_root)),
        generator,
        quality_reviewer=quality_reviewer,
        media_assets=media_assets,
    )


@dataclass(frozen=True)
class MediaLabTerraRuntime:
    orchestration: MediaLabImageOrchestrationService
    quality_reviewer: IImageQualityReviewer | None


@dataclass(frozen=True)
class MediaLabVideoTerraRuntime:
    orchestration: MediaLabVideoOrchestrationService
    quality_reviewer: IVideoQualityReviewer | None
    video_ad_planner: IVideoAdPlanner | None


def build_terra_runtime(
    config_path: Path,
    *,
    api_key: str | None,
    capabilities: tuple[ImageCapability, ...],
    usage_tracker: AIUsageTracker | None = None,
) -> MediaLabTerraRuntime:
    config = load_media_lab_image_orchestrator_config(config_path)
    terra = BamlMediaLabImageOrchestrator(
        config,
        api_key=api_key,
        usage_tracker=usage_tracker,
    )
    return MediaLabTerraRuntime(
        orchestration=MediaLabImageOrchestrationService(terra, capabilities),
        quality_reviewer=terra if terra.quality_review_enabled else None,
    )


def build_orchestration_runtime(
    config_path: Path,
    *,
    api_key: str | None,
    capabilities: tuple[ImageCapability, ...],
    usage_tracker: AIUsageTracker | None = None,
) -> MediaLabImageOrchestrationService:
    return build_terra_runtime(
        config_path,
        api_key=api_key,
        capabilities=capabilities,
        usage_tracker=usage_tracker,
    ).orchestration


def build_video_runtime(
    db_path: Path,
    artifacts_root: Path,
    generator: IVideoGenerationBackend,
    image_source: IImageOutputSource,
    *,
    repository: IVideoRunRepository | None = None,
    quality_reviewer: IVideoQualityReviewer | None = None,
    evidence_verifier: IVideoEvidenceVerifier | None = None,
    frame_sampler: IVideoFrameSampler | None = None,
    media_assets: MediaAssetService | None = None,
) -> MediaLabVideoService:
    active_repository = repository or SqliteMediaLabVideoRepository(db_path)
    return MediaLabVideoService(
        active_repository,
        MediaLabVideoArtifacts(ArtifactStore(artifacts_root)),
        generator,
        image_source,
        quality_reviewer=quality_reviewer,
        evidence_verifier=evidence_verifier,
        frame_sampler=frame_sampler,
        media_assets=media_assets,
    )


def build_video_project_runtime(
    db_path: Path,
    artifacts_root: Path,
    video_runs: MediaLabVideoService,
    media_assets: MediaAssetService,
    *,
    repository: IVideoProjectRepository | None = None,
) -> MediaLabVideoProjectService:
    return MediaLabVideoProjectService(
        repository or SqliteMediaLabVideoProjectRepository(db_path),
        video_runs,
        FfmpegVideoCompositor(artifacts_root / "media-lab-video-projects"),
        media_assets,
    )


def build_video_ad_runtime(
    db_path: Path,
    artifacts_root: Path,
    planner: IVideoAdPlanner,
    video_runs: MediaLabVideoService,
    media_assets: MediaAssetService,
    *,
    repository: IVideoAdRepository | None = None,
) -> MediaLabVideoAdService:
    return MediaLabVideoAdService(
        repository or SqliteMediaLabVideoAdRepository(db_path),
        planner,
        video_runs,
        FfmpegVideoCandidateSelector(),
        FfmpegVideoCompositor(artifacts_root / "media-lab-video-ads"),
        media_assets,
        media_assets,
    )


def build_planning_job_runtime(
    db_path: Path,
    media_assets: MediaAssetService,
    image_planner: MediaLabImageOrchestrationService | None,
    video_planner: MediaLabVideoOrchestrationService | None,
    *,
    repository: IPlanningJobRepository | None = None,
) -> MediaLabPlanningJobService:
    return MediaLabPlanningJobService(
        repository or SqliteMediaLabPlanningJobRepository(db_path),
        media_assets,
        image_planner,
        video_planner,
    )


def build_video_frame_sampler(config: MediaLabVideoVerifierConfig) -> IVideoFrameSampler:
    return FfmpegVideoFrameSampler(
        sampling_rate_fps=config.temporal_sampling_rate_fps,
        max_frame_edge_pixels=config.temporal_max_frame_edge_pixels,
        jpeg_quality=config.temporal_jpeg_quality,
    )


def build_video_terra_runtime(
    config_path: Path,
    *,
    api_key: str | None,
    capabilities: tuple[VideoCapability, ...],
    usage_tracker: AIUsageTracker | None = None,
) -> MediaLabVideoTerraRuntime:
    config = load_media_lab_video_orchestrator_config(config_path)
    terra = BamlMediaLabVideoOrchestrator(
        config,
        api_key=api_key,
        capabilities=capabilities,
        usage_tracker=usage_tracker,
    )
    return MediaLabVideoTerraRuntime(
        orchestration=MediaLabVideoOrchestrationService(terra, capabilities),
        quality_reviewer=terra if terra.quality_review_enabled else None,
        video_ad_planner=terra if config.video_ad_prompt is not None else None,
    )


__all__ = [
    "MediaLabTerraRuntime",
    "MediaLabVideoTerraRuntime",
    "build_media_asset_runtime",
    "build_orchestration_runtime",
    "build_planning_job_runtime",
    "build_runtime",
    "build_terra_runtime",
    "build_video_ad_runtime",
    "build_video_frame_sampler",
    "build_video_project_runtime",
    "build_video_runtime",
    "build_video_terra_runtime",
]
