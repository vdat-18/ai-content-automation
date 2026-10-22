"""Deterministic temporal evidence extraction for Media Lab video review."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path
from time import monotonic

from PIL import Image

from ai_content.domains.marketing.creative.adapters.image_files import inspect_image
from ai_content.domains.marketing.creative.ports.images import ImageGenerationError

from ..domain.models import ImageBinary
from ..domain.video_models import VideoQualityReviewFrame, VideoTemporalEvidence
from ..ports.video_interfaces import MediaLabVideoQualityReviewError


class FfmpegVideoFrameSampler:
    """Extract evenly spaced JPEG evidence frames across one exact MP4 timeline."""

    def __init__(
        self,
        *,
        sampling_rate_fps: int = 2,
        max_frame_edge_pixels: int = 1_280,
        jpeg_quality: int = 88,
    ) -> None:
        self._sampling_rate_fps = sampling_rate_fps
        self._max_frame_edge_pixels = max_frame_edge_pixels
        self._jpeg_quality = jpeg_quality

    def sample(self, path: Path) -> VideoTemporalEvidence:
        duration = self._duration(path)
        return self.sample_at(path, temporal_sample_positions(duration, self._sampling_rate_fps))

    def sample_at(self, path: Path, positions: tuple[float, ...]) -> VideoTemporalEvidence:
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            raise MediaLabVideoQualityReviewError(
                "ffmpeg and ffprobe are required for Media Lab video quality review",
                code="media_tool_unavailable",
            )
        duration = self._duration(path)
        if not positions:
            raise MediaLabVideoQualityReviewError(
                "Media Lab video temporal evidence requires at least one timestamp",
                code="frame_sampling_failed",
            )
        normalized_positions = tuple(
            min(max(position, 0.0), max(duration - 0.05, 0.0)) for position in positions
        )
        deadline = monotonic() + 60
        frames: list[VideoQualityReviewFrame] = []
        for index, position in enumerate(normalized_positions, start=1):
            content = self._frame(path, position, deadline)
            image = self._evidence_image(content)
            frames.append(
                VideoQualityReviewFrame(
                    label=f"candidate_frame_{index:03d}",
                    timestamp_milliseconds=round(position * 1_000),
                    image=image,
                )
            )
        return VideoTemporalEvidence(
            sampling_rate_fps=self._sampling_rate_fps,
            duration_milliseconds=round(duration * 1_000),
            frames=tuple(frames),
        )

    def _duration(self, path: Path) -> float:
        output = self._run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            timeout_seconds=30,
        )
        try:
            duration = float(json.loads(output)["format"]["duration"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise MediaLabVideoQualityReviewError(
                "Media Lab could not read generated video duration",
                code="frame_sampling_failed",
            ) from error
        if duration <= 0:
            raise MediaLabVideoQualityReviewError(
                "Media Lab generated video has no positive duration",
                code="frame_sampling_failed",
            )
        return duration

    def _frame(self, path: Path, position: float, deadline: float) -> bytes:
        remaining_seconds = deadline - monotonic()
        if remaining_seconds <= 0:
            raise MediaLabVideoQualityReviewError(
                "Media Lab video temporal evidence extraction timed out",
                code="frame_sampling_failed",
            )
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-ss",
                    f"{position:.3f}",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "png",
                    "-",
                ],
                capture_output=True,
                check=False,
                timeout=min(30, remaining_seconds),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise MediaLabVideoQualityReviewError(
                "Media Lab could not sample generated video frames",
                code="frame_sampling_failed",
            ) from error
        if result.returncode != 0 or not result.stdout:
            raise MediaLabVideoQualityReviewError(
                "Media Lab could not sample generated video frames",
                code="frame_sampling_failed",
            )
        return result.stdout

    def _evidence_image(self, content: bytes) -> ImageBinary:
        try:
            _, _, image_format = inspect_image(content)
        except (ImageGenerationError, SyntaxError) as error:
            raise MediaLabVideoQualityReviewError(
                "Media Lab could not decode a sampled video frame",
                code="frame_sampling_failed",
            ) from error
        if image_format not in {"png", "jpeg"}:
            raise MediaLabVideoQualityReviewError(
                "Media Lab sampled an unsupported video frame format",
                code="frame_sampling_failed",
            )
        try:
            with Image.open(io.BytesIO(content)) as frame:
                frame = frame.convert("RGB")
                frame.thumbnail(
                    (self._max_frame_edge_pixels, self._max_frame_edge_pixels),
                    Image.Resampling.LANCZOS,
                )
                output = io.BytesIO()
                frame.save(
                    output,
                    format="JPEG",
                    quality=self._jpeg_quality,
                    optimize=True,
                    progressive=True,
                    subsampling=0,
                )
        except OSError as error:
            raise MediaLabVideoQualityReviewError(
                "Media Lab could not prepare temporal video evidence",
                code="frame_sampling_failed",
            ) from error
        return ImageBinary(output.getvalue(), ".jpg", "image/jpeg")

    def _run(self, args: list[str], *, timeout_seconds: float) -> str:
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise MediaLabVideoQualityReviewError(
                "Media Lab could not inspect generated video",
                code="frame_sampling_failed",
            ) from error
        if result.returncode != 0:
            raise MediaLabVideoQualityReviewError(
                "Media Lab could not inspect generated video",
                code="frame_sampling_failed",
            )
        return result.stdout


def temporal_sample_positions(duration_seconds: float, sampling_rate_fps: int) -> tuple[float, ...]:
    """Cover the clip at a bounded fixed cadence and include its terminal frame."""
    final_position = max(duration_seconds - 0.05, 0.0)
    frame_count = int(final_position * sampling_rate_fps) + 1
    positions = tuple(index / sampling_rate_fps for index in range(frame_count))
    if positions and abs(positions[-1] - final_position) < 0.001:
        return positions
    return (*positions, final_position)


__all__ = ["FfmpegVideoFrameSampler", "temporal_sample_positions"]
