"""Auditable artifact projection for a Creative loop run."""

import json
from pathlib import Path

from ai_content.platform.artifacts.store import ArtifactStore

from ..domain.models import CreativeLoopRun
from .serialization import run_to_dict


def write_creative_loop_artifacts(store: ArtifactStore, run: CreativeLoopRun) -> Path:
    return store.write_text(
        json.dumps(run_to_dict(run), ensure_ascii=False, indent=2),
        "creative-loops",
        run.source_run_id,
        "manifest.json",
    )


__all__ = ["write_creative_loop_artifacts"]
