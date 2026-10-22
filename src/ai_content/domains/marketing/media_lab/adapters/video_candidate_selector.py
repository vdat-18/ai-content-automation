"""FFmpeg-based deterministic technical selection for generated video candidates."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from ..domain.video_ads import VideoUsableSegment
from ..ports.video_ads import MediaLabVideoAdError

_BLACK_RE = re.compile(r"black_start:(?P<start>[0-9.]+).*?black_end:(?P<end>[0-9.]+)")
_FREEZE_RE = re.compile(r"freeze_start: (?P<start>[0-9.]+).*?freeze_end: (?P<end>[0-9.]+)", re.S)


class FfmpegVideoCandidateSelector:
    def __init__(self, *, timeout_seconds: int = 900) -> None:
        self._timeout_seconds = timeout_seconds

    def select(
        self,
        shot_id: str,
        candidates: tuple[tuple[int, str, Path], ...],
        usable_duration_seconds: float,
    ) -> VideoUsableSegment:
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            raise MediaLabVideoAdError(
                "ffmpeg and ffprobe are required for candidate selection",
                code="ffmpeg_unavailable",
            )
        accepted: list[VideoUsableSegment] = []
        for candidate_index, run_id, path in candidates:
            try:
                duration = self._probe(path)
                self._decode(path)
                analysis = self._analyze(path)
            except MediaLabVideoAdError:
                continue
            start = _usable_start(analysis["black_ranges"], duration, usable_duration_seconds)
            end = start + usable_duration_seconds
            if end > duration + 0.1:
                continue
            black_overlap = _overlap_total(analysis["black_ranges"], start, end)
            freeze_overlap = _overlap_total(analysis["freeze_ranges"], start, end)
            if black_overlap > usable_duration_seconds * 0.2:
                continue
            if freeze_overlap > usable_duration_seconds * 0.6:
                continue
            score = 100.0 - black_overlap * 20.0 - freeze_overlap * 8.0 - candidate_index * 0.01
            observations = (
                f"black_overlap_seconds={black_overlap:.3f}",
                f"freeze_overlap_seconds={freeze_overlap:.3f}",
                f"source_duration_seconds={duration:.3f}",
            )
            accepted.append(
                VideoUsableSegment(
                    shot_id=shot_id,
                    candidate_index=candidate_index,
                    run_id=run_id,
                    trim_start_seconds=round(start, 3),
                    trim_end_seconds=round(end, 3),
                    score=round(score, 3),
                    observations=observations,
                )
            )
        if not accepted:
            raise MediaLabVideoAdError(
                f"No technically usable candidate remains for shot {shot_id}",
                status_code=422,
                code="no_usable_candidate",
            )
        return max(accepted, key=lambda item: (item.score, -item.candidate_index))

    def _probe(self, path: Path) -> float:
        result = _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,width,height",
                "-of",
                "json",
                str(path),
            ],
            self._timeout_seconds,
        )
        try:
            payload = json.loads(result.stdout)
            duration = float(payload["format"]["duration"])
            video = next(item for item in payload["streams"] if item.get("codec_type") == "video")
            if duration <= 0 or int(video["width"]) <= 0 or int(video["height"]) <= 0:
                raise ValueError
        except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as error:
            raise MediaLabVideoAdError(
                "Candidate video metadata is invalid", code="invalid_video_metadata"
            ) from error
        return duration

    def _decode(self, path: Path) -> None:
        _run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "null", "-"],
            self._timeout_seconds,
        )

    def _analyze(self, path: Path) -> dict[str, tuple[tuple[float, float], ...]]:
        result = _run(
            [
                "ffmpeg",
                "-hide_banner",
                "-i",
                str(path),
                "-vf",
                "blackdetect=d=0.35:pix_th=0.10,freezedetect=n=-50dB:d=1.5",
                "-an",
                "-f",
                "null",
                "-",
            ],
            self._timeout_seconds,
        )
        return {
            "black_ranges": tuple(
                (float(match.group("start")), float(match.group("end")))
                for match in _BLACK_RE.finditer(result.stderr)
            ),
            "freeze_ranges": tuple(
                (float(match.group("start")), float(match.group("end")))
                for match in _FREEZE_RE.finditer(result.stderr)
            ),
        }


def _usable_start(
    black_ranges: tuple[tuple[float, float], ...],
    duration: float,
    usable_duration: float,
) -> float:
    candidates = [0.0, *(end for _, end in black_ranges)]
    for start in sorted(set(candidates)):
        if (
            start + usable_duration <= duration + 0.1
            and _overlap_total(black_ranges, start, start + usable_duration)
            <= usable_duration * 0.2
        ):
            return start
    return 0.0


def _overlap_total(ranges: tuple[tuple[float, float], ...], start: float, end: float) -> float:
    return sum(max(0.0, min(end, right) - max(start, left)) for left, right in ranges)


def _run(command: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MediaLabVideoAdError(
            "Video technical command could not complete", code="media_command_failed"
        ) from error
    if result.returncode != 0:
        raise MediaLabVideoAdError("Video technical command failed", code="media_command_failed")
    return result


__all__ = ["FfmpegVideoCandidateSelector"]
