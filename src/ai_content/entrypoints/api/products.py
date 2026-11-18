"""Collected marketplace products: browser-extension intake, queue and export."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel, Field

from ai_content.domains.marketing.creative_knowledge.models import (
    KnowledgeAuthority,
    KnowledgeStatus,
)
from ai_content.domains.marketing.creative_knowledge.service import CreativeKnowledgeService
from ai_content.domains.marketing.products.briefing import BriefGenerationError, BriefUnavailable
from ai_content.domains.marketing.products.clips import StitchUnavailable
from ai_content.domains.marketing.products.knowledge import propose_feedback
from ai_content.domains.marketing.products.pipeline import (
    EXPECTED_STOPS,
    PipelineStopped,
    run_pipeline,
)
from ai_content.domains.marketing.products.posting import PostingPackageError
from ai_content.domains.marketing.products.references import (
    ProfileGenerationError,
    ReferenceProfile,
)
from ai_content.domains.marketing.products.service import (
    VOICEOVER_TYPES,
    KeyframeUnavailable,
    ProductCatalogService,
)
from ai_content.platform.notifications import Notification

from .dependencies import (
    get_creative_knowledge_service,
    get_product_catalog_service,
    get_runtime_settings,
    knowledge_curator,
    notification_scope_for,
    product_catalog_scope_for,
)

router = APIRouter(prefix="/api/v1/products", tags=["products"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.post("/ingest")
async def ingest_capture(
    payload: dict[str, Any],
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    try:
        return await service.ingest(payload)
    except ProfileGenerationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/queue")
async def capture_queue(
    limit: int = Query(20, ge=1, le=100_000),
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[str]:
    return await service.queue(limit)


@router.get("")
async def list_products(
    include_junk: bool = False,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    # The page never reads the raw TikTok payload, which is most of the data (about 57 KB each)
    return await service.details(include_junk, lean=True)


# Routes of the one shared person come first: `/persona` must not be read as a product id
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_PERSONA_BYTES = 10 * 1024 * 1024


class PersonaCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


# The people a video can follow are shared by every product, so these routes have no product id
@router.get("/persona")
async def list_personas(
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    return await service.list_personas(_media_root())


@router.post("/persona")
async def create_persona(
    body: PersonaCreate,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    return await service.create_persona(_media_root(), body.name)


@router.put("/persona/{persona_id}/image")
async def upload_persona_image(
    persona_id: str,
    request: Request,
    rights: str = Query(default=""),
    add: bool = Query(default=False),
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    """Use the user's own photo as this person (the user confirms the rights).

    With add=true the photo joins the ones already uploaded instead of replacing them.
    """
    if rights != "confirmed":
        raise HTTPException(
            status_code=422, detail="Confirm that you have the right to use this person's image"
        )
    kind = request.headers.get("content-type", "").split(";")[0].strip()
    if kind not in IMAGE_TYPES:
        raise HTTPException(status_code=415, detail=f"Use one of {sorted(IMAGE_TYPES)}")
    content = await request.body()
    if not content:
        raise HTTPException(status_code=422, detail="The file is empty")
    if len(content) > MAX_PERSONA_BYTES:
        raise HTTPException(status_code=413, detail="The photo is larger than 10 MB")
    persona = await service.upload_persona(_media_root(), persona_id, content, add)
    if persona is None:
        raise HTTPException(status_code=404, detail="No such person")
    return persona


@router.get("/persona/{persona_id}/image")
async def persona_image(
    persona_id: str,
    n: int = Query(default=0, ge=0),
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> FileResponse:
    persona = await service.get_persona(_media_root(), persona_id)
    paths = persona["image_paths"] if persona else []
    path = await service.media(_media_root()).fetch(paths[n]) if n < len(paths) else None
    if path is None:
        raise HTTPException(status_code=404, detail="No person portrait yet")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


@router.put("/persona/{persona_id}/default")
async def set_default_persona(
    persona_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    """New videos follow this person unless one is chosen."""
    if not await service.set_default_persona(_media_root(), persona_id):
        raise HTTPException(status_code=404, detail="No such person")
    return await service.list_personas(_media_root())


@router.delete("/persona/{persona_id}")
async def delete_persona(
    persona_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    if not await service.delete_persona(_media_root(), persona_id):
        raise HTTPException(status_code=404, detail="No such person")
    return await service.list_personas(_media_root())


@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, bool]:
    """Delete a product and everything made from it; the collector will not bring it back."""
    if not await service.delete_product(product_id, _media_root()):
        raise HTTPException(status_code=404, detail="No such product")
    return {"deleted": True}


@router.post("/media/download")
async def download_media(
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, int]:
    """Save images and videos of captured products under <data root>/media."""
    root = get_runtime_settings().data_root / "media"
    return (await service.download_media(root)).as_dict()


class ProfileUpdate(BaseModel):
    keywords: list[str]
    status: str = "draft"


@router.get("/selections")
async def list_selections(
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, str | None]:
    return await service.selections()


@router.get("/reference-profiles")
async def list_reference_profiles(
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    return [profile.as_dict() for profile in await service.profiles()]


@router.put("/reference-profiles/{product_type}")
async def update_reference_profile(
    product_type: str,
    body: ProfileUpdate,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    profile = ReferenceProfile(product_type, body.keywords, body.status)
    if not await service.update_profile(profile):
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile.as_dict()


@router.get("/reference-queue")
async def reference_queue(
    limit: int = Query(20, ge=1, le=200),
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, str]]:
    return await service.reference_queue(limit)


@router.post("/reference-images/redescribe")
async def redescribe_reference_images(
    limit: int = Query(30, ge=1, le=200),
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, int]:
    """Give images reviewed before detailed reviews existed a full description."""
    try:
        return await service.redescribe_images(limit)
    except ProfileGenerationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/reference-images/recheck-duplicates")
async def recheck_duplicates(
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, int]:
    """Apply the current similarity threshold to the reference images already stored."""
    return await service.recheck_duplicates()


@router.get("/reference-images")
async def list_reference_images(
    status: str | None = None,
    product_type: str | None = None,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    return await service.reference_images(status, product_type)


# The review of every waiting picture runs here in batches, so closing the page does not stop it.
# It stops by itself when the model stops answering (quota); the next press carries on.
_screen_tasks: set[asyncio.Task[None]] = set()
_screen_run: dict[str, Any] = {
    "status": "idle",
    "total": 0,
    "reviewed": 0,
    "usable": 0,
    "rejected": 0,
    "failed": 0,
    "message": "",
}


async def _run_screening(open_scope: Any) -> None:
    try:
        async with open_scope() as service:
            finished = await service.screen_pending(_screen_run.update)
    except Exception as error:  # noqa: BLE001
        logger.exception("Reference image review crashed")
        _screen_run.update(status="failed", message=str(error)[:300])
        return
    if finished:
        _screen_run.update(status="done", message="")
    else:
        _screen_run.update(
            status="stopped",
            message="The AI stopped answering (its quota may be used up). "
            "Press the button again later: the pictures left are still waiting.",
        )


@router.post("/reference-images/screen")
async def screen_reference_images(
    request: Request,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    """Start reviewing every waiting picture in the background."""
    if not service.can_review_images:
        raise HTTPException(status_code=503, detail="LLM is not configured (AIC_SCREENING_API_KEY)")
    if _screen_run["status"] == "running":
        raise HTTPException(status_code=409, detail="The review is already running")
    _screen_run.update(
        status="running", total=0, reviewed=0, usable=0, rejected=0, failed=0, message=""
    )
    task = asyncio.create_task(_run_screening(product_catalog_scope_for(request)))
    _screen_tasks.add(task)
    task.add_done_callback(_screen_tasks.discard)
    return dict(_screen_run)


@router.get("/reference-images/screen")
async def screen_reference_images_status() -> dict[str, Any]:
    return dict(_screen_run)


@router.post("/reference-images/backfill-fingerprints")
async def backfill_fingerprints(
    limit: int = Query(500, ge=1, le=2000),
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, int]:
    """Embed images stored before duplicate detection existed (also warms the model)."""
    try:
        return {"fingerprinted": await service.backfill_fingerprints(limit)}
    except ProfileGenerationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.delete("/reference-images/{image_id}")
async def remove_reference_image(
    image_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, str]:
    """Remove an image from the corpus; it stays recorded so a crawl never adds it back."""
    if not await service.set_image_status(image_id, "removed"):
        raise HTTPException(status_code=404, detail="Reference image not found")
    return {"image_id": image_id, "status": "removed"}


class BriefRequest(BaseModel):
    idea: str = ""
    video_seconds: Literal[15, 30, 45, 60, 75, 90] = 15
    persona_id: str | None = None  # the default person when empty


class BriefUpdate(BaseModel):
    brief: dict[str, Any]
    status: Literal["draft", "approved"] = "draft"


@router.post("/{product_id}/references/match")
async def match_references(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    """Choose the reference photo of every shot again, without rewriting the storyboard."""
    record = await service.match_references(product_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No brief for this product")
    return record


@router.get("/briefs")
async def list_briefs(
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    return await service.list_briefs()


@router.post("/{product_id}/brief")
async def create_brief(
    product_id: str,
    body: BriefRequest,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    try:
        persona_id, photos = await service.brief_persona(_media_root(), body.persona_id)
        record = await service.create_brief(
            product_id, body.idea, body.video_seconds, photos, persona_id
        )
    except BriefUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (BriefGenerationError, ProfileGenerationError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if record is None:
        raise HTTPException(status_code=404, detail="Product not captured")
    return record


@router.get("/{product_id}/brief")
async def get_brief(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    record = await service.get_brief(product_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No brief for this product")
    return record


@router.put("/{product_id}/brief")
async def update_brief(
    product_id: str,
    body: BriefUpdate,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    record = await service.update_brief(product_id, body.brief, body.status)
    if record is None:
        raise HTTPException(status_code=404, detail="No brief for this product")
    return record


@router.delete("/{product_id}/brief")
async def start_over(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, bool]:
    """Remove the script and everything made from it, to write a new one."""
    if _pipeline_runs.get(product_id, {}).get("status") == "running":
        raise HTTPException(status_code=409, detail="This product is being made right now")
    if not await service.start_over(product_id, _media_root()):
        raise HTTPException(status_code=404, detail="No brief for this product")
    _pipeline_runs.pop(product_id, None)  # the last run belonged to the script that is gone
    return {"deleted": True}


@router.post("/{product_id}/select")
async def select_product(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    """Mark a product for content."""
    if not await service.select(product_id):
        raise HTTPException(status_code=404, detail="Product not captured")
    return {"product_id": product_id}


# The whole video pipeline runs here, not in the browser, so closing the tab does not stop it.
# A run is remembered in memory only: after a restart the product shows no run, and running
# again resumes what is already made.
_pipeline_tasks: set[asyncio.Task[None]] = set()
_pipeline_runs: dict[str, dict[str, str]] = {}


class PipelineRequest(BaseModel):
    idea: str = ""
    video_seconds: Literal[15, 30, 45, 60, 75, 90] = 60
    until: Literal["script", "images", "video"] = "video"
    persona_id: str | None = None  # the default person when empty


_DONE_TITLES = {
    "script": "The script is ready to read",
    "images": "The images are ready to review",
    "video": "The video is ready",
}


async def _announce(
    open_notifications: Any, open_scope: Any, product_id: str, until: str, run: dict[str, str]
) -> None:
    """Keep how a run ended and leave a notification, so nobody has to watch the page."""
    try:
        async with open_scope() as service:
            await service.save_run(product_id, run["status"], run["message"])
            product = await service.detail(product_id) or {}
        title = {"done": _DONE_TITLES[until], "paused": "The video needs a look"}.get(
            run["status"], "The video could not be made"
        )
        name = product.get("title") or product_id
        now = datetime.now(UTC)
        async with open_notifications() as repository:
            await repository.save(
                Notification(
                    notification_id=f"pipeline-{product_id}-{uuid4().hex}",
                    scope_type="product",
                    scope_id=product_id,
                    kind=f"pipeline_{run['status']}",
                    title=title,
                    detail=f"{name}: {run['message']}" if run["message"] else str(name),
                    created_at=now,
                    updated_at=now,
                    action_path=f"/studio/{product_id}",
                )
            )
    except Exception as error:  # noqa: BLE001
        logger.warning("Could not leave a notification for product {}: {}", product_id, error)


async def _run_pipeline(
    open_scope: Any,
    product_id: str,
    body: PipelineRequest,
    media_root: Path,
    open_notifications: Any,
) -> None:
    run = _pipeline_runs[product_id]

    def report(step: str) -> None:
        run["step"] = step
        logger.info("Pipeline {} ({}): {}", product_id, body.until, step)

    try:
        async with open_scope() as service:
            await run_pipeline(
                service,
                product_id,
                media_root,
                idea=body.idea,
                video_seconds=body.video_seconds,
                report=report,
                until=body.until,
                persona_id=body.persona_id,
            )
    except (PipelineStopped, *EXPECTED_STOPS) as error:
        logger.warning("Pipeline {} stopped: {}", product_id, str(error)[:500])
        run.update(status="paused", message=str(error)[:500])
    except Exception as error:  # noqa: BLE001
        logger.exception("Pipeline for product {} crashed", product_id)
        run.update(status="failed", message=str(error)[:300])
    else:
        run.update(status="done", step="", message="")
    await _announce(open_notifications, open_scope, product_id, body.until, run)


@router.post("/{product_id}/pipeline")
async def start_pipeline(
    product_id: str,
    body: PipelineRequest,
    request: Request,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, str]:
    """Run every stage in the background: brief, person, images, clips, voice, video, post."""
    if await service.detail(product_id) is None:
        raise HTTPException(status_code=404, detail="Product not captured")
    if _pipeline_runs.get(product_id, {}).get("status") == "running":
        raise HTTPException(status_code=409, detail="This product is already being made")
    _pipeline_runs[product_id] = {
        "status": "running",
        "step": "Starting automated creation",
        "message": "",
    }
    await service.save_run(product_id, "running")
    task = asyncio.create_task(
        _run_pipeline(
            product_catalog_scope_for(request),
            product_id,
            body,
            _media_root(),
            notification_scope_for(request),
        )
    )
    _pipeline_tasks.add(task)
    task.add_done_callback(_pipeline_tasks.discard)
    return _pipeline_runs[product_id]


@router.get("/{product_id}/pipeline")
async def pipeline_status(product_id: str, request: Request) -> dict[str, str]:
    """The run in progress, else how the last one ended (it survives a restart).

    The page asks every two seconds while a run goes on, so the database is only opened when the
    run is not in memory.
    """
    if product_id in _pipeline_runs:
        return _pipeline_runs[product_id]
    async with product_catalog_scope_for(request)() as service:
        return await service.get_run(product_id) or {"status": "idle", "step": "", "message": ""}


@router.get("/outputs")
async def list_outputs(
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    """The finished videos."""
    return await service.list_outputs(_media_root())


@router.get("/export")
async def export_products(
    format: str = Query("json", pattern="^(json|xlsx)$"),
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> Response:
    if format == "xlsx":
        return Response(
            await service.export_workbook(),
            media_type=XLSX,
            headers={"Content-Disposition": 'attachment; filename="products.xlsx"'},
        )
    return Response(
        _json(await service.details()),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="products.json"'},
    )


@router.get("/{product_id}")
async def get_product(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    detail = await service.detail(product_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Product not captured")
    return detail


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


class KeyframeRequest(BaseModel):
    shot_index: int | None = None
    note: str = ""  # what to change when one shot is made again


class KeyframeReview(BaseModel):
    status: str


def _media_root() -> Path:
    return get_runtime_settings().data_root / "media"


@router.get("/{product_id}/keyframes")
async def list_keyframes(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    return await service.list_keyframes(product_id)


@router.post("/{product_id}/keyframes")
async def generate_keyframes(
    product_id: str,
    body: KeyframeRequest,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    """Run the next keyframe step; the master must be approved before the other shots."""
    try:
        keyframes = await service.generate_keyframes(
            product_id, _media_root(), body.shot_index, body.note.strip()
        )
    except KeyframeUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if keyframes is None:
        raise HTTPException(status_code=404, detail="No brief for this product")
    return keyframes


@router.put("/{product_id}/keyframes/{shot_index}")
async def review_keyframe(
    product_id: str,
    shot_index: int,
    body: KeyframeReview,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, str]:
    try:
        found = await service.set_keyframe_status(product_id, shot_index, body.status)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not found:
        raise HTTPException(status_code=404, detail="No such keyframe")
    return {"status": body.status}


@router.post("/{product_id}/keyframes/{shot_index}/check")
async def recheck_keyframe(
    product_id: str,
    shot_index: int,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    """Run the AI check again on an image that is made, without making a new one."""
    keyframe = await service.recheck_keyframe(product_id, shot_index, _media_root())
    if keyframe is None:
        raise HTTPException(status_code=404, detail="No such keyframe")
    return keyframe


@router.get("/{product_id}/keyframes/{shot_index}/image")
async def keyframe_image(
    product_id: str,
    shot_index: int,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> FileResponse:
    for keyframe in await service.list_keyframes(product_id):
        if keyframe["shot_index"] == shot_index and keyframe["image_path"]:
            path = await service.media(_media_root()).fetch(keyframe["image_path"])
            if path is not None:
                return FileResponse(path, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="No image for this keyframe")


class ClipRequest(BaseModel):
    shot_index: int | None = None


@router.get("/{product_id}/clips")
async def list_clips(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    return await service.clips(product_id, _media_root())


@router.post("/{product_id}/clips")
async def generate_clips(
    product_id: str,
    body: ClipRequest,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    """Start video jobs for approved keyframes; poll GET clips until they are ready."""
    try:
        clips = await service.generate_clips(product_id, _media_root(), body.shot_index)
    except KeyframeUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if clips is None:
        raise HTTPException(status_code=404, detail="No brief for this product")
    return clips


@router.put("/{product_id}/clips/{shot_index}/review")
async def accept_clip(
    product_id: str,
    shot_index: int,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, str]:
    """Accept a flagged clip as it is, so the video can be made with it."""
    if not await service.accept_clip(product_id, shot_index):
        raise HTTPException(status_code=404, detail="No such clip")
    return {"status": "accepted"}


@router.post("/{product_id}/clips/{shot_index}/check")
async def recheck_clip(
    product_id: str,
    shot_index: int,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    """Run the AI check again on a clip that is made, without making a new one."""
    clip = await service.recheck_clip(product_id, shot_index, _media_root())
    if clip is None:
        raise HTTPException(status_code=404, detail="No such clip")
    return clip


@router.get("/{product_id}/clips/{shot_index}/video")
async def clip_video(
    product_id: str,
    shot_index: int,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> FileResponse:
    for clip in await service.clips(product_id, _media_root()):
        if clip["shot_index"] == shot_index and clip["video_path"]:
            path = await service.media(_media_root()).fetch(clip["video_path"])
            if path is not None:
                return FileResponse(path, media_type="video/mp4")
    raise HTTPException(status_code=404, detail="No video for this clip")


class VideoRequest(BaseModel):
    captions: bool = False
    stickers: bool = False
    music: bool = True  # false leaves the background music out


@router.post("/{product_id}/video")
async def build_video(
    product_id: str,
    payload: VideoRequest | None = None,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, str]:
    """Stitch the ready clips into one video; captions are burned in only on request."""
    try:
        path = await service.build_video(
            product_id,
            _media_root(),
            payload.captions if payload else False,
            payload.stickers if payload else False,
            music=payload.music if payload else True,
        )
    except StitchUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if path is None:
        raise HTTPException(status_code=404, detail="No brief for this product")
    return {"video": f"/api/v1/products/{product_id}/video"}


@router.get("/{product_id}/events")
async def run_log(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> list[dict[str, Any]]:
    """The step-by-step log of what ran for this product's video."""
    return await service.events(product_id)


@router.get("/{product_id}/video-info")
async def video_info(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, bool | str]:
    store = service.media(_media_root())
    return {
        "exists": await store.exists(f"videos/{product_id}/video.mp4"),
        "voiceover": any(
            [
                await store.exists(f"videos/{product_id}/voiceover.{ext}")
                for ext in VOICEOVER_TYPES.values()
            ]
        ),
        "voice_id": await service.last_voice(product_id, _media_root()),
    }


@router.get("/{product_id}/video")
async def final_video(
    product_id: str,
    download: bool = False,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> FileResponse:
    path = await service.media(_media_root()).fetch(f"videos/{product_id}/video.mp4")
    if path is None:
        raise HTTPException(status_code=404, detail="No stitched video yet")
    return FileResponse(
        path,
        media_type="video/mp4",
        headers={"Cache-Control": "no-cache"},
        filename=f"{product_id}.mp4" if download else None,
    )


@router.get("/{product_id}/cover")
async def cover_image(
    product_id: str,
    download: bool = False,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> FileResponse:
    path = await service.media(_media_root()).fetch(f"videos/{product_id}/cover.jpg")
    if path is None:
        raise HTTPException(status_code=404, detail="No cover yet; stitch the video first")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache"},
        filename=f"{product_id}.jpg" if download else None,
    )


@router.get("/{product_id}/output")
async def get_output(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    """What this product's video is made from."""
    output = await service.get_output(product_id, _media_root())
    if output is None:
        raise HTTPException(status_code=404, detail="No brief for this product")
    return output


@router.post("/{product_id}/post-package")
async def create_post_package(
    product_id: str,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    """Write caption options and hashtags for the finished video."""
    try:
        package = await service.create_post_package(product_id)
    except KeyframeUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except PostingPackageError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if package is None:
        raise HTTPException(status_code=404, detail="No brief for this product")
    return package


class FeedbackRequest(BaseModel):
    text: str = Field(min_length=1)
    contributor: str = Field(default="user", min_length=1)
    asset_type: Literal["brief", "keyframe"] = "keyframe"


@router.post("/{product_id}/feedback")
async def send_feedback(
    product_id: str,
    payload: FeedbackRequest,
    knowledge: CreativeKnowledgeService = Depends(get_creative_knowledge_service),
) -> dict[str, str]:
    """Turn feedback on a generated image or video into a rule: the AI rewrites it into the
    rulebook's form, replaces the rules it contradicts and approves it. Without the AI it stays
    proposed."""
    item = await propose_feedback(
        knowledge,
        product_id=product_id,
        text=payload.text,
        contributor=payload.contributor,
        authority=KnowledgeAuthority.INDIVIDUAL,
        asset_type=payload.asset_type,
    )
    curator = knowledge_curator(get_runtime_settings())
    if curator is not None and item.status == KnowledgeStatus.PROPOSED:
        item = await knowledge.learn(item.knowledge_id, curator, "feedback")
    return {"knowledge_id": item.knowledge_id, "status": item.status.value, "rule": item.title}


VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm"}
MAX_EXAMPLE_AD_BYTES = 100 * 1024 * 1024


@router.put("/reference-ad")
async def learn_from_reference_ad(
    request: Request,
    service: ProductCatalogService = Depends(get_product_catalog_service),
) -> dict[str, Any]:
    """Describe how an example ad is built and propose that as rules; the video is not kept."""
    kind = request.headers.get("content-type", "").split(";")[0].strip()
    if kind not in VIDEO_TYPES:
        raise HTTPException(status_code=415, detail=f"Use one of {sorted(VIDEO_TYPES)}")
    content = await request.body()
    if not content:
        raise HTTPException(status_code=422, detail="The file is empty")
    if len(content) > MAX_EXAMPLE_AD_BYTES:
        raise HTTPException(status_code=413, detail="The video is larger than 100 MB")
    try:
        rules = await service.learn_from_reference_ad(content)
    except KeyframeUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"rules": rules}
