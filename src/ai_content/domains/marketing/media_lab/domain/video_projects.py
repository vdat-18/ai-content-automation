"""Domain records for final Ads assembled from completed Media Lab video runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class VideoProjectState(StrEnum):
    ASSEMBLING = "assembling"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True)
class VideoProjectShot:
    shot_id: str
    source_run_id: str
    trim_start_seconds: float
    trim_end_seconds: float

    @property
    def duration_seconds(self) -> float:
        return self.trim_end_seconds - self.trim_start_seconds


@dataclass(frozen=True)
class CreateVideoProjectCommand:
    source_run_id: str
    shots: tuple[VideoProjectShot, ...]
    target_duration_seconds: float


@dataclass(frozen=True)
class VideoProject:
    project_id: str
    source_run_id: str
    input_hash: str
    shots: tuple[VideoProjectShot, ...]
    target_duration_seconds: float
    state: VideoProjectState
    source_asset_ids: tuple[str, ...]
    output_asset_id: str | None
    output_checksum_sha256: str | None
    actual_width: int | None
    actual_height: int | None
    actual_duration_milliseconds: int | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None = None
    reviewed_at: datetime | None = None


__all__ = [
    "CreateVideoProjectCommand",
    "VideoProject",
    "VideoProjectShot",
    "VideoProjectState",
]
