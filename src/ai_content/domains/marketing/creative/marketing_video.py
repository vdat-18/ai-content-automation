"""Bounded multi-shot Marketing video pilot with exact input and output artifacts."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_content.platform.artifacts.store import ArtifactStore

from .config.videos import VideoBackendConfig
from .ports.videos import IVideoBackend, VideoGenerationError, VideoGenerationRequest, VideoMode


class VideoShot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    shot_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1)
    mode: VideoMode
    prompt: str = Field(min_length=1)
    seconds: int = Field(gt=0)
    seed: int | None = Field(default=None, ge=0, lt=2**64)
    input_path: Path | None = None
    on_screen_text: str | None = None
    candidate_count: int = Field(default=1, ge=1, le=3)
    trim_start_seconds: float = Field(default=0, ge=0)
    trim_end_seconds: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def check_input(self) -> VideoShot:
        if (self.mode == "text_to_video") != (self.input_path is None):
            raise ValueError("Only text_to_video can omit input_path")
        trim_end = self.trim_end_seconds if self.trim_end_seconds is not None else self.seconds
        if trim_end > self.seconds or self.trim_start_seconds >= trim_end:
            raise ValueError("Shot trim window must stay inside the generated clip")
        return self

    @property
    def selected_duration_seconds(self) -> float:
        trim_end = self.trim_end_seconds if self.trim_end_seconds is not None else self.seconds
        return trim_end - self.trim_start_seconds


class VideoMarketingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_run_id: str = Field(min_length=1)
    brand: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    angle: str = Field(min_length=1)
    size: str = Field(pattern=r"^\d+x\d+$")
    shots: tuple[VideoShot, ...] = Field(min_length=1, max_length=8)
    hook_variants: tuple[VideoShot, ...] = Field(default=(), max_length=3)
    target_duration_seconds: float | None = Field(default=None, ge=20, le=30)
    cta_text: str | None = None
    font_path: Path | None = None
    voice_path: Path | None = None
    music_path: Path | None = None

    @model_validator(mode="after")
    def check_shots(self) -> VideoMarketingPlan:
        all_shots = (*self.hook_variants, *self.shots)
        if len({shot.shot_id for shot in all_shots}) != len(all_shots):
            raise ValueError("shot_id must be unique")
        if self.target_duration_seconds is not None:
            hooks = self.hook_variants or (None,)
            for hook in hooks:
                planned = sum(shot.selected_duration_seconds for shot in self.shots)
                if hook is not None:
                    planned += hook.selected_duration_seconds
                if abs(planned - self.target_duration_seconds) > 1:
                    raise ValueError("Each final variant must match target_duration_seconds")
        return self


@dataclass(frozen=True)
class VideoMarketingResult:
    final_path: Path
    manifest_path: Path
    final_paths: tuple[Path, ...] = ()


def load_video_marketing_plan(path: Path) -> VideoMarketingPlan:
    """Resolve local media paths against the plan, never the process working directory."""
    plan = VideoMarketingPlan.model_validate_json(path.read_text(encoding="utf-8"))
    shots = tuple(
        shot.model_copy(update={"input_path": (path.parent / shot.input_path).resolve()})
        if shot.input_path is not None and not shot.input_path.is_absolute()
        else shot
        for shot in plan.shots
    )
    updates: dict[str, object] = {"shots": shots}
    for name in ("font_path", "voice_path", "music_path"):
        value = getattr(plan, name)
        if value is not None and not value.is_absolute():
            updates[name] = (path.parent / value).resolve()
    return plan.model_copy(update=updates)


def _read_input(path: Path, *, max_bytes: int) -> bytes:
    if not path.is_file():
        raise VideoGenerationError("Video plan input file is missing")
    with path.open("rb") as source:
        content = source.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise VideoGenerationError("Video plan input exceeds byte limit")
    return content


def _run_media_command(args: list[str], *, cwd: Path, timeout: float = 120) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VideoGenerationError("Video media tool is unavailable or timed out") from exc
    if result.returncode != 0:
        raise VideoGenerationError("Video media processing failed")
    return result.stdout


def _probe_mp4(path: Path, *, cwd: Path, expected_size: str) -> dict[str, Any]:
    output = _run_media_command(
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
        cwd=cwd,
    )
    try:
        probe = json.loads(output)
        streams = probe["streams"]
        video = next(stream for stream in streams if stream["codec_type"] == "video")
        duration = float(probe["format"]["duration"])
        width, height = map(int, expected_size.split("x"))
        if video["width"] != width or video["height"] != height or duration <= 0:
            raise ValueError("invalid dimensions or duration")
    except (KeyError, TypeError, ValueError, StopIteration) as exc:
        raise VideoGenerationError("Video output failed duration or dimension QA") from exc
    return {
        "duration_seconds": duration,
        "has_audio": any(stream.get("codec_type") == "audio" for stream in streams),
    }


def _decode_mp4(path: Path, *, cwd: Path) -> None:
    """Decode the complete candidate so truncated MP4 files cannot win selection."""
    _run_media_command(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-f", "null", "-"],
        cwd=cwd,
        timeout=600,
    )


def _trim_clip(path: Path, shot: VideoShot, *, cwd: Path, label: str) -> Path:
    trim_end = shot.trim_end_seconds if shot.trim_end_seconds is not None else shot.seconds
    if shot.trim_start_seconds == 0 and trim_end == shot.seconds:
        return path
    output = cwd / f"{label}.mp4"
    _run_media_command(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-ss",
            str(shot.trim_start_seconds),
            "-i",
            str(path),
            "-t",
            str(trim_end - shot.trim_start_seconds),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(output),
        ],
        cwd=cwd,
        timeout=600,
    )
    return output


def _overlay_text(
    path: Path, text: str, *, cwd: Path, label: str, font_path: Path | None = None
) -> Path:
    text_path = cwd / f"{label}.txt"
    text_path.write_text(text, encoding="utf-8")
    output = cwd / f"{label}.mp4"
    font_option = f"fontfile={font_path.relative_to(cwd).as_posix()}:" if font_path else ""
    filter_value = (
        f"drawtext={font_option}textfile={text_path.name}:fontcolor=white:fontsize=40:"
        "box=1:boxcolor=black@0.55:x=(w-text_w)/2:y=h*0.82"
    )
    _run_media_command(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-i",
            str(path),
            "-vf",
            filter_value,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(output),
        ],
        cwd=cwd,
    )
    return output


def _assemble(clips: list[Path], probes: list[dict[str, Any]], output: Path, *, cwd: Path) -> None:
    args = ["ffmpeg", "-nostdin", "-y"]
    filters: list[str] = []
    has_audio = any(probe["has_audio"] for probe in probes)
    for index, (clip, probe) in enumerate(zip(clips, probes, strict=True)):
        args.extend(["-i", str(clip)])
        filters.append(f"[{index}:v]setpts=PTS-STARTPTS,fps=24,format=yuv420p[v{index}]")
        if has_audio:
            if probe["has_audio"]:
                filters.append(
                    f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,"
                    f"asetpts=PTS-STARTPTS[a{index}]"
                )
            else:
                filters.append(
                    f"anullsrc=r=48000:cl=stereo,atrim=duration={probe['duration_seconds']},"
                    f"asetpts=PTS-STARTPTS[a{index}]"
                )
    streams = "".join(
        f"[v{index}][a{index}]" if has_audio else f"[v{index}]" for index in range(len(clips))
    )
    filters.append(
        f"{streams}concat=n={len(clips)}:v=1:a={int(has_audio)}[v]" + ("[a]" if has_audio else "")
    )
    args.extend(["-filter_complex", ";".join(filters), "-map", "[v]"])
    if has_audio:
        args.extend(["-map", "[a]", "-c:a", "aac"])
    args.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)])
    _run_media_command(args, cwd=cwd, timeout=600)


def _add_audio(
    source: Path,
    output: Path,
    *,
    voice: Path | None,
    music: Path | None,
    duration: float,
    cwd: Path,
) -> None:
    args = ["ffmpeg", "-nostdin", "-y", "-i", str(source)]
    if voice is not None:
        args.extend(["-i", str(voice)])
    if music is not None:
        args.extend(["-stream_loop", "-1", "-i", str(music)])
    if voice is not None and music is not None:
        args.extend(
            [
                "-filter_complex",
                "[1:a]apad,aresample=48000[voice];"
                "[2:a]volume=0.22,aresample=48000[music];"
                "[music][voice]sidechaincompress=threshold=0.03:ratio=8:attack=20:"
                "release=300[ducked];[voice][ducked]amix=inputs=2:duration=first:"
                "normalize=0,loudnorm=I=-16:LRA=11:TP=-1.5[a]",
                "-map",
                "0:v:0",
                "-map",
                "[a]",
            ]
        )
    elif voice is not None:
        args.extend(
            [
                "-filter_complex",
                "[1:a]apad,loudnorm=I=-16:LRA=11:TP=-1.5[a]",
                "-map",
                "0:v:0",
                "-map",
                "[a]",
            ]
        )
    else:
        args.extend(
            [
                "-filter_complex",
                "[1:a]loudnorm=I=-18:LRA=11:TP=-1.5[a]",
                "-map",
                "0:v:0",
                "-map",
                "[a]",
            ]
        )
    args.extend(["-c:v", "copy", "-c:a", "aac", "-t", str(duration), str(output)])
    _run_media_command(args, cwd=cwd, timeout=600)


def _candidate_seed(seed: int | None, candidate_index: int) -> int | None:
    if seed is None:
        return None
    return (seed + candidate_index - 1) % (2**64)


async def _generate_shot(
    shot: VideoShot,
    *,
    shot_number: int,
    plan: VideoMarketingPlan,
    backend: IVideoBackend,
    inputs: dict[str, bytes],
    store: ArtifactStore,
    output_dir: Path,
    font_path: Path | None,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    candidates: list[tuple[float, int, Path, dict[str, Any], Any]] = []
    candidate_records: list[dict[str, Any]] = []
    last_error: Exception | None = None
    for candidate_index in range(1, shot.candidate_count + 1):
        input_path = None
        if shot.shot_id in inputs:
            suffix = shot.input_path.suffix.lower() if shot.input_path else ".bin"
            input_path = store.write_bytes(
                inputs[shot.shot_id],
                "inputs",
                f"shot-{shot_number}{suffix}",
            )
        seed = _candidate_seed(shot.seed, candidate_index)
        request = VideoGenerationRequest(
            shot.prompt,
            shot.seconds,
            plan.size,
            mode=shot.mode,
            input_path=input_path,
            seed=seed,
        )
        record: dict[str, Any] = {
            "candidate_index": candidate_index,
            "seed_requested": seed,
            "status": "failed",
        }
        try:
            generated = await backend.generate(request)
            clip = store.write_bytes(
                generated.content,
                "candidates",
                f"shot-{shot_number}-candidate-{candidate_index}.mp4",
            )
            probe = _probe_mp4(clip, cwd=output_dir, expected_size=plan.size)
            _decode_mp4(clip, cwd=output_dir)
            duration_delta = abs(probe["duration_seconds"] - shot.seconds)
            if duration_delta > 1.5:
                raise VideoGenerationError("Video shot duration differs from requested duration")
            record.update(
                {
                    "status": "valid",
                    "artifact": str(clip.relative_to(output_dir)),
                    "sha256": hashlib.sha256(clip.read_bytes()).hexdigest(),
                    "provider_job_id": generated.service_job_id,
                    "model": generated.model,
                    "model_revision": generated.model_revision,
                    "runtime_version": generated.runtime_version,
                    "seed": generated.seed,
                    "workflow_hash": generated.workflow_hash,
                    "elapsed_seconds": generated.elapsed_seconds,
                    "selection_score": duration_delta,
                    **probe,
                }
            )
            candidates.append((duration_delta, candidate_index, clip, probe, generated))
        except VideoGenerationError as error:
            last_error = error
            record["error_code"] = type(error).__name__
            candidate_records.append(record)
            if "submission=unknown_check_service" in str(error):
                raise
            continue
        candidate_records.append(record)

    if not candidates:
        if last_error is not None:
            raise last_error
        raise VideoGenerationError(f"No technically valid candidate for shot {shot.shot_id}")
    _, selected_index, selected_clip, selected_probe, generated = min(
        candidates, key=lambda item: (item[0], item[1])
    )
    for record in candidate_records:
        record["selected"] = record["candidate_index"] == selected_index
    selected_clip = store.write_bytes(
        selected_clip.read_bytes(),
        "shots",
        f"shot-{shot_number}.mp4",
    )
    selected_clip = _trim_clip(
        selected_clip,
        shot,
        cwd=output_dir,
        label=f"shot-{shot_number}-selected-trimmed",
    )
    selected_probe = _probe_mp4(selected_clip, cwd=output_dir, expected_size=plan.size)
    if shot.on_screen_text:
        selected_clip = _overlay_text(
            selected_clip,
            shot.on_screen_text,
            cwd=output_dir,
            label=f"shot-{shot_number}-text",
            font_path=font_path,
        )
    selected = {
        "shot_id": shot.shot_id,
        "mode": shot.mode,
        "artifact": str(selected_clip.relative_to(output_dir)),
        "sha256": hashlib.sha256(selected_clip.read_bytes()).hexdigest(),
        "prompt_sha256": hashlib.sha256(shot.prompt.encode()).hexdigest(),
        "input_sha256": (
            hashlib.sha256(inputs[shot.shot_id]).hexdigest() if shot.shot_id in inputs else None
        ),
        "provider_job_id": generated.service_job_id,
        "model": generated.model,
        "model_revision": generated.model_revision,
        "runtime_version": generated.runtime_version,
        "seed": generated.seed,
        "workflow_hash": generated.workflow_hash,
        "elapsed_seconds": generated.elapsed_seconds,
        "trim_start_seconds": shot.trim_start_seconds,
        "trim_end_seconds": (
            shot.trim_end_seconds if shot.trim_end_seconds is not None else shot.seconds
        ),
        "candidate_count": shot.candidate_count,
        "selected_candidate_index": selected_index,
        "candidates": candidate_records,
        **selected_probe,
    }
    return selected_clip, selected_probe, selected


async def run_video_marketing(
    plan: VideoMarketingPlan,
    config: VideoBackendConfig,
    backend: IVideoBackend,
    output_dir: Path,
) -> VideoMarketingResult:
    """Generate candidates, select valid shots and render final variants without a mid-flow gate."""
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"Video output directory already exists: {output_dir}")
    if plan.size not in config.supported_sizes:
        raise VideoGenerationError("Video plan size is not supported")
    all_shots = (*plan.hook_variants, *plan.shots)
    for shot in all_shots:
        if shot.mode != "text_to_video":
            raise VideoGenerationError("Video plan mode is not supported by selected backend")
        if shot.seconds not in config.supported_seconds:
            raise VideoGenerationError("Video shot duration is not supported")
        if shot.mode != "text_to_video" and shot.input_path is None:
            raise VideoGenerationError("Video shot input is missing")
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise VideoGenerationError("ffmpeg and ffprobe are required before generating paid shots")

    inputs: dict[str, bytes] = {}
    for shot in all_shots:
        if shot.input_path is not None:
            inputs[shot.shot_id] = _read_input(shot.input_path, max_bytes=config.max_video_bytes)
    audio_inputs = {
        name: _read_input(path, max_bytes=config.max_video_bytes)
        for name in ("voice_path", "music_path")
        if (path := getattr(plan, name)) is not None
    }
    font_input = (
        _read_input(plan.font_path, max_bytes=config.max_video_bytes)
        if plan.font_path is not None
        else None
    )
    for name in audio_inputs:
        path = getattr(plan, name)
        audio_probe = _run_media_command(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "json",
                str(path),
            ],
            cwd=path.parent,
        )
        try:
            if not any(
                stream.get("codec_type") == "audio" for stream in json.loads(audio_probe)["streams"]
            ):
                raise ValueError("no audio stream")
        except (KeyError, TypeError, ValueError) as exc:
            raise VideoGenerationError("Video plan audio file is invalid") from exc

    output_dir.mkdir(parents=True, exist_ok=False)
    store = ArtifactStore(output_dir)
    font_path = (
        store.write_bytes(font_input, "inputs", "overlay-font.ttf")
        if font_input is not None
        else None
    )
    manifest: dict[str, Any] = {
        "schema_version": 2,
        "source_run_id": plan.source_run_id,
        "brand": plan.brand,
        "sku": plan.sku,
        "angle": plan.angle,
        "size": plan.size,
        "target_duration_seconds": plan.target_duration_seconds,
        "selection_policy": "full_decode_then_closest_duration_then_candidate_order",
        "status": "running",
        "shots": [],
        "final_variants": [],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    selected: dict[str, tuple[Path, dict[str, Any]]] = {}
    try:
        for shot_number, shot in enumerate(all_shots, start=1):
            clip, probe, record = await _generate_shot(
                shot,
                shot_number=shot_number,
                plan=plan,
                backend=backend,
                inputs=inputs,
                store=store,
                output_dir=output_dir,
                font_path=font_path,
            )
            selected[shot.shot_id] = (clip, probe)
            manifest["shots"].append(record)
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        audio_paths = {
            name: store.write_bytes(content, "inputs", f"{name}{getattr(plan, name).suffix}")
            for name, content in audio_inputs.items()
        }
        variants = plan.hook_variants or (None,)
        final_paths: list[Path] = []
        for variant_number, hook in enumerate(variants, start=1):
            variant_id = hook.shot_id if hook is not None else "default"
            variant_shots = ((hook,) if hook is not None else ()) + plan.shots
            clips = [selected[shot.shot_id][0] for shot in variant_shots]
            probes = [selected[shot.shot_id][1] for shot in variant_shots]
            if plan.cta_text:
                clips[-1] = _overlay_text(
                    clips[-1],
                    plan.cta_text,
                    cwd=output_dir,
                    label=f"cta-{variant_id}",
                    font_path=font_path,
                )
            assembled_name = (
                "assembled.mp4" if len(variants) == 1 else f"assembled-{variant_id}.mp4"
            )
            assembled = output_dir / assembled_name
            _assemble(clips, probes, assembled, cwd=output_dir)
            final_name = "final.mp4" if len(variants) == 1 else f"final-{variant_id}.mp4"
            final = output_dir / final_name
            assembled_probe = _probe_mp4(assembled, cwd=output_dir, expected_size=plan.size)
            if audio_inputs:
                _add_audio(
                    assembled,
                    final,
                    voice=audio_paths.get("voice_path"),
                    music=audio_paths.get("music_path"),
                    duration=assembled_probe["duration_seconds"],
                    cwd=output_dir,
                )
            else:
                shutil.copyfile(assembled, final)
            final_probe = _probe_mp4(final, cwd=output_dir, expected_size=plan.size)
            _decode_mp4(final, cwd=output_dir)
            expected_duration = sum(shot.selected_duration_seconds for shot in variant_shots)
            if abs(final_probe["duration_seconds"] - expected_duration) > len(variant_shots) * 1.5:
                raise VideoGenerationError("Final video duration differs from shot plan")
            if (
                plan.target_duration_seconds is not None
                and abs(final_probe["duration_seconds"] - plan.target_duration_seconds) > 1.5
            ):
                raise VideoGenerationError("Final video duration differs from target duration")
            final_paths.append(final)
            manifest["final_variants"].append(
                {
                    "variant_id": variant_id,
                    "hook_shot_id": hook.shot_id if hook is not None else None,
                    "shot_ids": [shot.shot_id for shot in variant_shots],
                    "artifact": final.name,
                    "sha256": hashlib.sha256(final.read_bytes()).hexdigest(),
                    "duration_seconds": final_probe["duration_seconds"],
                    "has_audio": final_probe["has_audio"],
                    "variant_number": variant_number,
                }
            )

        manifest["status"] = "awaiting_human_review"
        if len(final_paths) == 1:
            final_variant = manifest["final_variants"][0]
            manifest.update(
                {
                    "final_artifact": final_variant["artifact"],
                    "final_sha256": final_variant["sha256"],
                    "final_duration_seconds": final_variant["duration_seconds"],
                    "final_has_audio": final_variant["has_audio"],
                }
            )
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return VideoMarketingResult(final_paths[0], manifest_path, tuple(final_paths))
    except Exception:
        manifest["status"] = "failed"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        raise


def review_video_marketing(output_dir: Path, decision: str, reason: str) -> Path:
    """Pin the final-only human decision to every exact rendered variant."""
    if decision not in {"accept", "revise", "reject"} or not reason.strip():
        raise ValueError("A valid video review decision and reason are required")
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest["status"] != "awaiting_human_review":
        raise ValueError("Video run is not awaiting review")
    final_variants = manifest.get("final_variants") or [
        {
            "variant_id": "default",
            "artifact": manifest["final_artifact"],
            "sha256": manifest["final_sha256"],
        }
    ]
    checksums: dict[str, str] = {}
    for variant in final_variants:
        final = output_dir / variant["artifact"]
        checksum = hashlib.sha256(final.read_bytes()).hexdigest()
        if checksum != variant["sha256"]:
            raise ValueError("Final video changed after generation")
        checksums[variant["variant_id"]] = checksum
    review = output_dir / "review.json"
    with review.open("x", encoding="utf-8") as stream:
        json.dump(
            {
                "decision": decision,
                "reason": reason,
                "final_sha256": next(iter(checksums.values())),
                "final_variant_sha256": checksums,
            },
            stream,
            indent=2,
        )
    return review


__all__ = [
    "VideoMarketingPlan",
    "VideoMarketingResult",
    "VideoShot",
    "load_video_marketing_plan",
    "review_video_marketing",
    "run_video_marketing",
]
