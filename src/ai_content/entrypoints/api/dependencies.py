"""Dependency helpers for API request handlers."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Request

from ai_content.domains.marketing.creative_knowledge.repositories import (
    SqliteCreativeKnowledgeRepository,
)
from ai_content.domains.marketing.creative_knowledge.service import CreativeKnowledgeService
from ai_content.domains.marketing.products.briefing import ContentBriefWriter
from ai_content.domains.marketing.products.clip_check import ClipChecker
from ai_content.domains.marketing.products.clips import VideoClient
from ai_content.domains.marketing.products.embedding import ImageEmbedder
from ai_content.domains.marketing.products.image_review import ReferenceImageReviewer
from ai_content.domains.marketing.products.keyframe_check import KeyframeChecker
from ai_content.domains.marketing.products.keyframes import (
    KeyframeGenerator,
    KeyframeImageClient,
)
from ai_content.domains.marketing.products.knowledge import BamlKnowledgeCurator
from ai_content.domains.marketing.products.media_store import S3RemoteMedia
from ai_content.domains.marketing.products.posting import PostingPackageWriter
from ai_content.domains.marketing.products.reference_picker import ShotReferencePicker
from ai_content.domains.marketing.products.references import ReferenceProfileGenerator
from ai_content.domains.marketing.products.repositories import SqliteProductRepository
from ai_content.domains.marketing.products.service import ProductCatalogService
from ai_content.domains.marketing.products.speech import SpeechClient
from ai_content.domains.marketing.products.storyboard_review import StoryboardReviewer
from ai_content.domains.marketing.products.text_embedding import TextEmbedder
from ai_content.entrypoints.postgres_runtime import PostgresRuntimeContainer
from ai_content.platform.ai_usage import AIUsageRepository, SqliteAIUsageRepository
from ai_content.platform.database import Database
from ai_content.platform.notifications import (
    NotificationRepository,
    SqliteNotificationRepository,
)
from ai_content.platform.observability import ObservabilitySettings, instrument_sqlalchemy
from ai_content.settings import ApplicationSettings


@dataclass(frozen=True)
class ApiRuntimeSettings:
    """Runtime settings used by the dashboard API."""

    db_path: Path
    config_dir: Path
    screening_base_url: str = "http://127.0.0.1:1234/v1"
    screening_api_key: str | None = None
    screening_model: str = "gemini-3.8-flash"
    embedding_model: str = ""
    text_embedding_base_url: str = ""
    text_embedding_api_key: str | None = None
    text_embedding_model: str = ""
    image_base_url: str = ""
    image_api_key: str | None = None
    image_model: str = ""
    video_base_url: str = ""
    video_api_key: str | None = None
    video_model: str = ""
    tts_base_url: str = ""
    tts_api_key: str | None = None
    tts_model: str = ""
    tts_voice: str = ""
    database_backend: Literal["sqlite", "postgresql"] = "sqlite"
    database_url: str | None = None
    media_s3_endpoint_url: str | None = None
    media_s3_bucket: str = ""
    media_s3_access_key: str | None = None
    media_s3_secret_key: str | None = None
    media_s3_region: str = "us-east-1"


@dataclass(frozen=True)
class RuntimeReadiness:
    """Dependency status exposed by the lightweight readiness endpoint."""

    ready: bool
    checks: dict[str, str]


def _media_s3_settings(application: ApplicationSettings) -> dict[str, Any]:
    """Generated images and videos go to object storage when it is the configured backend."""
    if application.object_storage_backend != "s3":
        return {}
    return {
        "media_s3_endpoint_url": application.s3_endpoint_url,
        "media_s3_bucket": application.s3_bucket,
        "media_s3_access_key": application.s3_access_key.get_secret_value()
        if application.s3_access_key
        else None,
        "media_s3_secret_key": application.s3_secret_key.get_secret_value()
        if application.s3_secret_key
        else None,
        "media_s3_region": application.s3_region,
    }


def get_runtime_settings() -> ApiRuntimeSettings:
    """Build default runtime settings for the dashboard API."""
    application = ApplicationSettings()
    return ApiRuntimeSettings(
        db_path=application.data_root / "state.db",
        config_dir=application.config_dir,
        screening_base_url=application.screening_base_url,
        screening_api_key=application.screening_api_key_value,
        screening_model=application.screening_model,
        embedding_model=application.embedding_model,
        text_embedding_base_url=application.text_embedding_base_url
        or application.image_base_url
        or application.screening_base_url,
        text_embedding_api_key=application.text_embedding_api_key_value,
        text_embedding_model=application.text_embedding_model,
        image_base_url=application.image_base_url or application.screening_base_url,
        image_api_key=application.image_api_key_value,
        image_model=application.image_model,
        video_base_url=application.video_base_url
        or application.image_base_url
        or application.screening_base_url,
        video_api_key=application.video_api_key_value,
        video_model=application.video_model,
        tts_base_url=application.tts_base_url
        or application.video_base_url
        or application.image_base_url
        or application.screening_base_url,
        tts_api_key=application.tts_api_key_value,
        tts_model=application.tts_model,
        tts_voice=application.tts_voice,
        database_backend=application.database_backend,
        database_url=(
            application.database_url.get_secret_value() if application.database_url else None
        ),
        **_media_s3_settings(application),
    )


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Own PostgreSQL resources for the lifetime of the API process."""
    settings = get_runtime_settings()
    observability = getattr(
        application.state,
        "observability_settings",
        ObservabilitySettings(service_name="aicontent-api"),
    )
    container = None
    if settings.database_backend == "postgresql":
        assert settings.database_url is not None
        database = Database(settings.database_url)
        container = PostgresRuntimeContainer(database)
        application.state.postgres_runtime = container
        instrument_sqlalchemy(database.engine, observability)
    try:
        yield
    finally:
        if container is not None:
            await container.database.close()
        observability_runtime = getattr(application.state, "observability_runtime", None)
        if observability_runtime is not None:
            observability_runtime.shutdown()


def _postgres_runtime(request: Request) -> PostgresRuntimeContainer | None:
    settings = get_runtime_settings()
    if settings.database_backend == "sqlite":
        return None
    container = getattr(request.app.state, "postgres_runtime", None)
    if container is None:
        raise RuntimeError("PostgreSQL runtime was not initialized")
    return container


async def check_runtime_readiness(
    settings: ApiRuntimeSettings, database: Database | None
) -> RuntimeReadiness:
    """Check the data directory and the selected database backend."""
    checks: dict[str, str] = {}
    try:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        checks["storage"] = "ok"
    except OSError:
        checks["storage"] = "unavailable"
    try:
        if settings.database_backend == "sqlite":
            with sqlite3.connect(settings.db_path, timeout=1) as connection:
                connection.execute("SELECT 1").fetchone()
        else:
            if database is None:
                raise RuntimeError("PostgreSQL runtime is unavailable")
            await database.check()
        checks["database"] = "ok"
    except (OSError, sqlite3.Error, RuntimeError):
        checks["database"] = "unavailable"
    return RuntimeReadiness(
        ready=all(value == "ok" for value in checks.values()),
        checks=checks,
    )


async def get_notification_repository(
    request: Request,
) -> AsyncIterator[NotificationRepository]:
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.notification_repository
        return
    repository = SqliteNotificationRepository(settings.db_path)
    try:
        yield repository
    finally:
        repository.close()


async def get_ai_usage_repository(request: Request) -> AsyncIterator[AIUsageRepository]:
    """Yield the durable usage ledger."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.ai_usage_repository
        return
    repository = SqliteAIUsageRepository(settings.db_path)
    try:
        yield repository
    finally:
        repository.close()


async def get_creative_knowledge_service(
    request: Request,
) -> AsyncIterator[CreativeKnowledgeService]:
    """Yield the scoped knowledge registry."""
    settings = get_runtime_settings()
    postgres = _postgres_runtime(request)
    if postgres is not None:
        yield postgres.creative_knowledge_service
        return
    repository = SqliteCreativeKnowledgeRepository(settings.db_path)
    try:
        yield CreativeKnowledgeService(repository)
    finally:
        repository.close()


def _image_reviewer(settings: ApiRuntimeSettings) -> ReferenceImageReviewer | None:
    if not settings.screening_api_key:
        return None
    return ReferenceImageReviewer.from_settings(
        base_url=settings.screening_base_url,
        api_key=settings.screening_api_key,
        model=settings.screening_model,
    )


@cache
def _embedder_for(model: str, models_dir: Path) -> ImageEmbedder:
    return ImageEmbedder(model, models_dir)


def _image_embedder(settings: ApiRuntimeSettings) -> ImageEmbedder | None:
    if not settings.embedding_model:
        return None
    return _embedder_for(settings.embedding_model, settings.db_path.parent / "models")


def _keyframer(settings: ApiRuntimeSettings) -> KeyframeGenerator | None:
    if not (settings.image_api_key and settings.image_model):
        return None
    return KeyframeGenerator(
        KeyframeImageClient(
            base_url=settings.image_base_url,
            api_key=settings.image_api_key,
            model=settings.image_model,
        )
    )


def _video_client(settings: ApiRuntimeSettings) -> VideoClient | None:
    if not (settings.video_api_key and settings.video_model):
        return None
    return VideoClient(
        base_url=settings.video_base_url,
        api_key=settings.video_api_key,
        model=settings.video_model,
    )


def _speech_client(settings: ApiRuntimeSettings) -> SpeechClient | None:
    if not (settings.tts_api_key and settings.tts_model):
        return None
    return SpeechClient(
        base_url=settings.tts_base_url,
        api_key=settings.tts_api_key,
        model=settings.tts_model,
        voice=settings.tts_voice,
    )


def _remote_media(settings: ApiRuntimeSettings) -> S3RemoteMedia | None:
    if not (
        settings.media_s3_endpoint_url
        and settings.media_s3_bucket
        and settings.media_s3_access_key
        and settings.media_s3_secret_key
    ):
        return None
    return S3RemoteMedia(
        endpoint_url=settings.media_s3_endpoint_url,
        bucket=settings.media_s3_bucket,
        access_key=settings.media_s3_access_key,
        secret_key=settings.media_s3_secret_key,
        region=settings.media_s3_region,
    )


def _posting_writer(settings: ApiRuntimeSettings) -> PostingPackageWriter | None:
    if not settings.screening_api_key:
        return None
    return PostingPackageWriter.from_settings(
        base_url=settings.screening_base_url,
        api_key=settings.screening_api_key,
        model=settings.screening_model,
    )


def knowledge_curator(settings: ApiRuntimeSettings) -> BamlKnowledgeCurator | None:
    if not settings.screening_api_key:
        return None
    return BamlKnowledgeCurator.from_settings(
        base_url=settings.screening_base_url,
        api_key=settings.screening_api_key,
        model=settings.screening_model,
    )


def _clip_checker(settings: ApiRuntimeSettings) -> ClipChecker | None:
    if not settings.screening_api_key:
        return None
    return ClipChecker.from_settings(
        base_url=settings.screening_base_url,
        api_key=settings.screening_api_key,
        model=settings.screening_model,
    )


def _keyframe_checker(settings: ApiRuntimeSettings) -> KeyframeChecker | None:
    if not settings.screening_api_key:
        return None
    return KeyframeChecker.from_settings(
        base_url=settings.screening_base_url,
        api_key=settings.screening_api_key,
        model=settings.screening_model,
    )


def _brief_writer(settings: ApiRuntimeSettings) -> ContentBriefWriter | None:
    if not settings.screening_api_key:
        return None
    return ContentBriefWriter.from_settings(
        base_url=settings.screening_base_url,
        api_key=settings.screening_api_key,
        model=settings.screening_model,
    )


def _text_embedder(settings: ApiRuntimeSettings) -> TextEmbedder | None:
    if not (settings.text_embedding_model and settings.text_embedding_api_key):
        return None
    return TextEmbedder(
        settings.text_embedding_base_url,
        settings.text_embedding_api_key,
        settings.text_embedding_model,
    )


def _reference_picker(settings: ApiRuntimeSettings) -> ShotReferencePicker | None:
    if not settings.screening_api_key:
        return None
    return ShotReferencePicker.from_settings(
        base_url=settings.screening_base_url,
        api_key=settings.screening_api_key,
        model=settings.screening_model,
    )


def _storyboard_reviewer(settings: ApiRuntimeSettings) -> StoryboardReviewer | None:
    if not settings.screening_api_key:
        return None
    return StoryboardReviewer.from_settings(
        base_url=settings.screening_base_url,
        api_key=settings.screening_api_key,
        model=settings.screening_model,
    )


def _profile_generator(settings: ApiRuntimeSettings) -> ReferenceProfileGenerator | None:
    if not settings.screening_api_key:
        return None
    return ReferenceProfileGenerator.from_settings(
        base_url=settings.screening_base_url,
        api_key=settings.screening_api_key,
        model=settings.screening_model,
    )


@asynccontextmanager
async def product_catalog_scope(postgres: Any) -> AsyncIterator[ProductCatalogService]:
    """Open the product catalog service, in a request or in a background task."""
    settings = get_runtime_settings()
    repository = (
        postgres.product_repository
        if postgres is not None
        else SqliteProductRepository(settings.db_path)
    )
    knowledge_repository = (
        None if postgres is not None else SqliteCreativeKnowledgeRepository(settings.db_path)
    )
    knowledge = (
        postgres.creative_knowledge_service
        if postgres is not None
        else CreativeKnowledgeService(knowledge_repository)
    )
    try:
        yield ProductCatalogService(
            repository,
            _profile_generator(settings),
            _image_reviewer(settings),
            _brief_writer(settings),
            _image_embedder(settings),
            _keyframer(settings),
            _keyframe_checker(settings),
            _video_client(settings),
            _posting_writer(settings),
            _speech_client(settings),
            _remote_media(settings),
            _storyboard_reviewer(settings),
            _text_embedder(settings),
            _reference_picker(settings),
            clip_checker=_clip_checker(settings),
            knowledge=knowledge,
        )
    finally:
        if postgres is None:
            repository.close()
            knowledge_repository.close()


def product_catalog_scope_for(request: Request):
    """A scope that stays usable after the request that asked for it has ended."""
    postgres = _postgres_runtime(request)
    return lambda: product_catalog_scope(postgres)


async def get_product_catalog_service(request: Request) -> AsyncIterator[ProductCatalogService]:
    """Yield the collected marketplace product catalog."""
    async with product_catalog_scope(_postgres_runtime(request)) as service:
        yield service
