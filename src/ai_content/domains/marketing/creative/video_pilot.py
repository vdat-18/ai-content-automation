"""Single-clip video pilot used to verify a configured provider boundary."""

import hashlib
import json
from pathlib import Path

from ai_content.platform.artifacts.store import ArtifactStore

from .adapters.comfyui_videos import ComfyUIVideoBackend
from .adapters.openai_compatible_videos import OpenAICompatibleVideoBackend
from .config.videos import VideoBackendConfig
from .ports.videos import IVideoBackend, VideoGenerationRequest


def build_video_backend(config: VideoBackendConfig, *, api_key: str | None = None) -> IVideoBackend:
    if config.backend == "comfyui":
        return ComfyUIVideoBackend(config)
    return OpenAICompatibleVideoBackend(config, api_key=api_key)


async def generate_video_clip(
    config: VideoBackendConfig,
    request: VideoGenerationRequest,
    output_dir: Path,
    *,
    api_key: str | None = None,
) -> Path:
    """Generate one provider clip and persist bytes plus reproducibility metadata."""
    if output_dir.exists():
        raise FileExistsError(f"Video output directory already exists: {output_dir}")
    generated = await build_video_backend(config, api_key=api_key).generate(request)
    store = ArtifactStore(output_dir)
    video_path = store.write_bytes(generated.content, "clip.mp4")
    metadata = {
        "artifact": video_path.name,
        "elapsed_seconds": generated.elapsed_seconds,
        "model": generated.model,
        "model_revision": generated.model_revision,
        "prompt_sha256": hashlib.sha256(generated.prompt.encode("utf-8")).hexdigest(),
        "quality": generated.quality,
        "runtime_version": generated.runtime_version,
        "seed": generated.seed,
        "seconds": generated.seconds,
        "service_job_id": generated.service_job_id,
        "sha256": hashlib.sha256(generated.content).hexdigest(),
        "size": generated.size,
        "workflow_hash": generated.workflow_hash,
    }
    store.write_text(json.dumps(metadata, indent=2), "metadata.json")
    return video_path


__all__ = ["build_video_backend", "generate_video_clip"]
