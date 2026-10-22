"""Technical decoding and normalization for reusable Media Lab assets."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from ..domain.assets import MediaAssetKind, MediaAssetLimits
from ..ports.assets import MediaAssetError, PreprocessedMedia

_IMAGE_FORMATS = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "WEBP": (".webp", "image/webp"),
    "AVIF": (".avif", "image/avif"),
    "TIFF": (".tiff", "image/tiff"),
}
_VIDEO_FORMAT_NAMES = {"mov", "mp4", "matroska", "webm"}


class MediaPreprocessor:
    """Create model-safe working media and lightweight browser/VLM previews."""

    version = "media-preprocessing@1"

    def __init__(self, limits: MediaAssetLimits) -> None:
        self._limits = limits

    def prepare(
        self,
        source: Path,
        media_kind: MediaAssetKind,
        workspace: Path,
    ) -> PreprocessedMedia:
        if media_kind == MediaAssetKind.IMAGE:
            return self._prepare_image(source, workspace)
        if media_kind == MediaAssetKind.VIDEO:
            return self._prepare_video(source, workspace)
        raise MediaAssetError("Media kind is invalid", code="invalid_media_kind")

    def _prepare_image(self, source: Path, workspace: Path) -> PreprocessedMedia:
        try:
            with Image.open(source) as opened:
                image_format = opened.format or ""
                format_details = _IMAGE_FORMATS.get(image_format.upper())
                if format_details is None:
                    raise MediaAssetError(
                        "Image format is not supported. Use JPEG, PNG, WebP, AVIF, or TIFF.",
                        code="unsupported_image_format",
                    )
                frame_count = getattr(opened, "n_frames", 1)
                if frame_count != 1:
                    raise MediaAssetError(
                        "Animated image inputs are not supported",
                        code="unsupported_image_animation",
                    )
                source_width, source_height = opened.size
                if source_width * source_height > self._limits.max_image_pixels:
                    raise MediaAssetError(
                        "Image decoded pixel count exceeds the configured limit",
                        status_code=413,
                        code="image_pixels_too_large",
                    )
                orientation = opened.getexif().get(0x0112, 1)
                opened.load()
                normalized = _normalize_image(opened)
        except (OSError, UnidentifiedImageError) as error:
            raise MediaAssetError(
                "Image bytes could not be decoded", code="invalid_image"
            ) from error

        working = _constrain_image(normalized, self._limits.max_working_image_pixels)
        preview = _constrain_image(normalized, self._limits.max_preview_image_pixels)
        working_path, working_content_type = _write_image_derivative(workspace / "working", working)
        preview_path, preview_content_type = _write_image_derivative(workspace / "preview", preview)
        extension, content_type = format_details
        metadata = (
            ("color_space", "sRGB"),
            ("orientation_applied", str(orientation != 1).lower()),
            ("alpha_handling", "preserved" if "A" in normalized.getbands() else "none"),
            ("working_width", str(working.width)),
            ("working_height", str(working.height)),
            ("preview_width", str(preview.width)),
            ("preview_height", str(preview.height)),
            ("source_format", image_format.upper()),
        )
        return PreprocessedMedia(
            media_kind=MediaAssetKind.IMAGE,
            original_extension=extension,
            detected_content_type=content_type,
            working_path=working_path,
            working_content_type=working_content_type,
            preview_path=preview_path,
            preview_content_type=preview_content_type,
            width=normalized.width,
            height=normalized.height,
            duration_milliseconds=None,
            codec=None,
            transform_metadata=metadata,
        )

    def _prepare_video(self, source: Path, workspace: Path) -> PreprocessedMedia:
        probe = _run_media_command(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=format_name,duration:stream=codec_type,codec_name,width,height",
                "-of",
                "json",
                str(source),
            ],
            self._limits.processing_timeout_seconds,
        )
        try:
            payload = json.loads(probe.stdout)
            format_names = set(str(payload["format"]["format_name"]).split(","))
            streams = payload.get("streams", [])
            video_stream = next(stream for stream in streams if stream.get("codec_type") == "video")
            duration_seconds = float(payload["format"]["duration"])
            width = int(video_stream["width"])
            height = int(video_stream["height"])
        except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as error:
            raise MediaAssetError(
                "Video bytes could not be decoded", code="invalid_video"
            ) from error
        if not format_names.intersection(_VIDEO_FORMAT_NAMES):
            raise MediaAssetError(
                "Video format is not supported. Use MP4, MOV, WebM, or MKV.",
                code="unsupported_video_format",
            )
        if duration_seconds <= 0 or duration_seconds > self._limits.max_video_duration_seconds:
            raise MediaAssetError(
                "Video duration exceeds the configured limit",
                status_code=413,
                code="video_duration_too_large",
            )
        if width <= 0 or height <= 0:
            raise MediaAssetError("Video dimensions are invalid", code="invalid_video")

        working_path = workspace / "working.mp4"
        preview_path = workspace / "preview.jpg"
        _run_media_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(working_path),
            ],
            self._limits.processing_timeout_seconds,
        )
        _run_media_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(working_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(preview_path),
            ],
            self._limits.processing_timeout_seconds,
        )
        if not working_path.is_file() or not preview_path.is_file():
            raise MediaAssetError(
                "Video preprocessing did not produce required derivatives",
                code="video_processing_failed",
            )
        return PreprocessedMedia(
            media_kind=MediaAssetKind.VIDEO,
            original_extension=_video_extension(format_names),
            detected_content_type=_video_content_type(format_names),
            working_path=working_path,
            working_content_type="video/mp4",
            preview_path=preview_path,
            preview_content_type="image/jpeg",
            width=width,
            height=height,
            duration_milliseconds=round(duration_seconds * 1_000),
            codec=str(video_stream.get("codec_name") or "unknown"),
            transform_metadata=(
                ("source_format", ",".join(sorted(format_names))),
                ("working_codec", "h264"),
                ("working_pixel_format", "yuv420p"),
                ("preview_timestamp_seconds", "0"),
            ),
        )


def _normalize_image(image: Image.Image) -> Image.Image:
    transposed = ImageOps.exif_transpose(image)
    has_alpha = "A" in transposed.getbands() or "transparency" in transposed.info
    target_mode = "RGBA" if has_alpha else "RGB"
    icc_profile = transposed.info.get("icc_profile")
    if isinstance(icc_profile, bytes):
        try:
            source_profile = ImageCms.ImageCmsProfile(BytesIO(icc_profile))
            return ImageCms.profileToProfile(
                transposed,
                source_profile,
                ImageCms.createProfile("sRGB"),
                outputMode=target_mode,
            )
        except (ImageCms.PyCMSError, OSError, ValueError):
            pass
    return transposed.convert(target_mode)


def _constrain_image(image: Image.Image, maximum_pixels: int) -> Image.Image:
    if image.width * image.height <= maximum_pixels:
        return image.copy()
    scale = math.sqrt(maximum_pixels / (image.width * image.height))
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def _write_image_derivative(target: Path, image: Image.Image) -> tuple[Path, str]:
    output = BytesIO()
    if "A" in image.getbands():
        path = target.with_suffix(".png")
        image.save(output, format="PNG", optimize=True)
        content_type = "image/png"
    else:
        path = target.with_suffix(".jpg")
        image.save(output, format="JPEG", quality=95, optimize=True, progressive=True)
        content_type = "image/jpeg"
    path.write_bytes(output.getvalue())
    return path, content_type


def _run_media_command(
    command: list[str], timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    executable = command[0]
    if shutil.which(executable) is None:
        raise MediaAssetError(
            f"{executable} is required for video ingestion",
            status_code=503,
            code="media_tool_unavailable",
        )
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise MediaAssetError(
            "Video preprocessing timed out", status_code=504, code="media_timeout"
        ) from error
    except subprocess.CalledProcessError as error:
        raise MediaAssetError("Video preprocessing failed", code="invalid_video") from error


def _video_extension(format_names: set[str]) -> str:
    if "webm" in format_names:
        return ".webm"
    if "matroska" in format_names:
        return ".mkv"
    return ".mp4"


def _video_content_type(format_names: set[str]) -> str:
    if "webm" in format_names:
        return "video/webm"
    if "matroska" in format_names:
        return "video/x-matroska"
    return "video/mp4"


__all__ = ["MediaPreprocessor", "PreprocessedMedia"]
