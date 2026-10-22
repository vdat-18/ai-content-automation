"""FFmpeg compositor for deterministic final Ads video assembly."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

from ..ports.video_projects import (
    VideoCompositionError,
    VideoCompositionRequest,
    VideoCompositionResult,
)


class FfmpegVideoCompositor:
    """Trim, concatenate, encode and full-decode one final MP4."""

    def __init__(self, output_root: Path, *, timeout_seconds: int = 900) -> None:
        self._output_root = output_root
        self._timeout_seconds = timeout_seconds

    def compose(self, request: VideoCompositionRequest) -> VideoCompositionResult:
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            raise VideoCompositionError(
                "ffmpeg and ffprobe are required for final video assembly",
                code="ffmpeg_unavailable",
            )
        for shot in request.shots:
            _full_decode(shot.source_path, self._timeout_seconds)

        project_dir = self._output_root / request.project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        output_path = project_dir / "final.mp4"
        if output_path.exists():
            output_path.unlink()
        command = ["ffmpeg", "-v", "error", "-y"]
        for shot in request.shots:
            command.extend(["-i", str(shot.source_path)])
        logo_input_index = None
        if request.logo_path is not None:
            logo_input_index = len(request.shots)
            command.extend(["-i", str(request.logo_path)])

        filters: list[str] = []
        concat_inputs: list[str] = []
        for index, shot in enumerate(request.shots):
            duration = shot.trim_end_seconds - shot.trim_start_seconds
            video_filter = (
                f"[{index}:v]trim=start={shot.trim_start_seconds:.6f}:"
                f"end={shot.trim_end_seconds:.6f},setpts=PTS-STARTPTS,"
                f"scale={request.width}:{request.height}:force_original_aspect_ratio=decrease,"
                f"pad={request.width}:{request.height}:(ow-iw)/2:(oh-ih)/2:color=black,"
                "setsar=1,fps=24,format=yuv420p"
            )
            if shot.overlay_text:
                text_path = project_dir / f"overlay-{index:02d}.txt"
                text_path.write_text(shot.overlay_text, encoding="utf-8")
                escaped = _escape_filter_path(text_path)
                overlay_enable = ""
                if index == len(request.shots) - 1 and request.cta_text:
                    end_card_start = max(0.0, duration - 1.5)
                    overlay_enable = f":enable='lt(t,{end_card_start:.6f})'"
                video_filter += (
                    f",drawtext=textfile='{escaped}':fontcolor=white:"
                    f"fontsize=h/22:box=1:boxcolor=black@0.58:boxborderw=18:"
                    f"x=(w-text_w)/2:y=h*0.82{overlay_enable}"
                )
            if index == len(request.shots) - 1 and request.cta_text:
                cta_path = project_dir / "cta.txt"
                cta_path.write_text(
                    _wrap_end_card_text(request.cta_text, request.width, request.height),
                    encoding="utf-8",
                )
                escaped_cta = _escape_filter_path(cta_path)
                end_card_start = max(0.0, duration - 1.5)
                video_filter += (
                    f",drawbox=x=0:y=0:w=iw:h=ih:color=black@0.72:t=fill:"
                    f"enable='gte(t,{end_card_start:.6f})'"
                    f",drawtext=textfile='{escaped_cta}':fontcolor=white:"
                    f"fontsize=h/18:line_spacing={max(4, request.height // 72)}:"
                    f"x=(w-text_w)/2:y=(h-text_h)/2:"
                    f"enable='gte(t,{end_card_start:.6f})'"
                )
            filters.append(video_filter + f"[v{index}]")
            probe = _probe(shot.source_path, self._timeout_seconds)
            if probe["has_audio"]:
                filters.append(
                    f"[{index}:a]atrim=start={shot.trim_start_seconds:.6f}:"
                    f"end={shot.trim_end_seconds:.6f},asetpts=PTS-STARTPTS,"
                    f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    f"loudnorm=I=-18:LRA=11:TP=-1.5[a{index}]"
                )
            else:
                filters.append(
                    f"anullsrc=r=48000:cl=stereo,atrim=duration={duration:.6f},"
                    f"asetpts=PTS-STARTPTS[a{index}]"
                )
            concat_inputs.append(f"[v{index}][a{index}]")
        video_output = "vbase" if logo_input_index is not None else "vout"
        filters.append(
            "".join(concat_inputs)
            + f"concat=n={len(request.shots)}:v=1:a=1[{video_output}][aconcat]"
        )
        filters.append("[aconcat]loudnorm=I=-16:LRA=11:TP=-1.5[aout]")
        if logo_input_index is not None:
            filters.append(f"[{logo_input_index}:v]scale={max(96, request.width // 7)}:-1[logo]")
            filters.append(
                f"[vbase][logo]overlay=x=W-w-{max(16, request.width // 40)}:"
                f"y={max(16, request.height // 40)}:format=auto[vout]"
            )
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "16",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        _run(command, self._timeout_seconds)
        _full_decode(output_path, self._timeout_seconds)
        result = _probe(output_path, self._timeout_seconds)
        if result["width"] != request.width or result["height"] != request.height:
            raise VideoCompositionError(
                "Final video dimensions do not match the source contract",
                code="output_dimensions_mismatch",
            )
        duration_milliseconds = round(result["duration_seconds"] * 1000)
        expected_milliseconds = round(request.target_duration_seconds * 1000)
        if abs(duration_milliseconds - expected_milliseconds) > 500:
            raise VideoCompositionError(
                "Final video duration does not match the project contract",
                code="output_duration_mismatch",
            )
        return VideoCompositionResult(
            output_path=output_path,
            width=result["width"],
            height=result["height"],
            duration_milliseconds=duration_milliseconds,
        )


def _escape_filter_path(path: Path) -> str:
    return path.resolve().as_posix().replace(":", "\\:").replace("'", "\\'")


def _wrap_end_card_text(text: str, width: int, height: int) -> str:
    approximate_character_width = (height / 18) * 0.6
    line_width = max(10, int((width * 0.84) / approximate_character_width))
    return "\n".join(
        textwrap.fill(line.strip(), width=line_width, break_long_words=True)
        for line in text.splitlines()
        if line.strip()
    )


def _full_decode(path: Path, timeout_seconds: int) -> None:
    _run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "null", "-"],
        timeout_seconds,
    )


def _probe(path: Path, timeout_seconds: int) -> dict[str, Any]:
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
        timeout_seconds,
    )
    try:
        payload = json.loads(result.stdout)
        streams = payload["streams"]
        video = next(item for item in streams if item.get("codec_type") == "video")
        duration = float(payload["format"]["duration"])
        width = int(video["width"])
        height = int(video["height"])
    except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as error:
        raise VideoCompositionError(
            "Video technical metadata is invalid", code="invalid_video_metadata"
        ) from error
    if duration <= 0 or width <= 0 or height <= 0:
        raise VideoCompositionError(
            "Video technical metadata is invalid", code="invalid_video_metadata"
        )
    return {
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "has_audio": any(item.get("codec_type") == "audio" for item in streams),
    }


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
        raise VideoCompositionError(
            "Video composition command could not complete", code="media_command_failed"
        ) from error
    if result.returncode != 0:
        raise VideoCompositionError("Video composition command failed", code="media_command_failed")
    return result


__all__ = ["FfmpegVideoCompositor"]
