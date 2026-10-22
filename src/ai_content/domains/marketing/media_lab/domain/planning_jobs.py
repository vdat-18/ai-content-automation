"""Durable background jobs for Media Lab request planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .models import ImageOrchestrationPlan
from .video_models import VideoOrchestrationPlan


class PlanningJobKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class PlanningJobState(StrEnum):
    PLANNING = "planning"
    READY = "ready"
    NEEDS_INPUT = "needs_input"
    FAILED = "failed"


@dataclass(frozen=True)
class PlanningJob:
    job_id: str
    source_run_id: str
    input_hash: str
    kind: PlanningJobKind
    user_request: str
    source_asset_ids: tuple[str, ...]
    state: PlanningJobState
    plan: ImageOrchestrationPlan | VideoOrchestrationPlan | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime


__all__ = ["PlanningJob", "PlanningJobKind", "PlanningJobState"]
