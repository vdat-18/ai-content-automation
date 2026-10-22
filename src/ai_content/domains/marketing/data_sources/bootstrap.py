"""Composition root for read-only sandbox data source integrations."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path

from ai_content.platform.artifacts import ArtifactService, ArtifactStore

from .adapters import (
    FilesystemSnapshotArtifactWriter,
    GoogleAdsConnector,
    GoogleConnector,
    GoogleMerchantConnector,
    KlaviyoConnector,
    LarkConnector,
    MetaAdsConnector,
    MockAwareConnector,
    MockDataConnector,
    PinterestAdsConnector,
    ServiceSnapshotArtifactWriter,
    ShopifyConnector,
    SqliteDataSourceRepository,
)
from .application.compile_context import CreativeSourceContextCompiler
from .application.compile_performance import SourcePerformanceCompiler
from .application.sync import DataSourceSyncService
from .domain.models import DataSourceDefinition, SourceSnapshot, SyncRun
from .ports.interfaces import IDataSourceRepository


class DataSourceRuntime:
    def __init__(
        self,
        service: DataSourceSyncService,
        repository: IDataSourceRepository,
    ) -> None:
        self.service = service
        self.repository = repository
        self.compiler = CreativeSourceContextCompiler()
        self.performance_compiler = SourcePerformanceCompiler()

    @property
    def definitions(self) -> tuple[DataSourceDefinition, ...]:
        return tuple(self.service.definitions.values())

    async def sync(self, source_id: str) -> SyncRun:
        return await self.service.sync(source_id)

    async def sync_all(self) -> tuple[SyncRun, ...]:
        return await self.service.sync_all()

    async def import_normalized_backup(self, path: Path) -> SyncRun:
        return await self.service.import_normalized_backup(path)

    async def latest_snapshot(self, source_id: str) -> SourceSnapshot | None:
        return await self.repository.latest_snapshot(source_id)

    async def refresh_shopify_products(
        self,
        snapshots: list[SourceSnapshot],
        products: tuple[tuple[str, str], ...],
    ) -> list[SourceSnapshot]:
        """Replace catalog rows with request-scoped live Shopify product snapshots."""
        unique_products = tuple(dict.fromkeys(products))
        if not unique_products:
            return snapshots
        refreshed = await asyncio.gather(
            *(
                self.service.live_product_snapshot(source_id, product_id)
                for source_id, product_id in unique_products
            )
        )
        await asyncio.gather(*(self.repository.save_snapshot(item) for item in refreshed))
        refreshed_sources = {source_id for source_id, _ in unique_products}
        return [item for item in snapshots if item.source_id not in refreshed_sources] + list(
            refreshed
        )

    async def close(self) -> None:
        self.repository.close()


def build_runtime(
    definitions: tuple[DataSourceDefinition, ...],
    db_path: Path,
    artifacts_root: Path,
    *,
    shopify_token: str | None,
    shopify_source_tokens: Mapping[str, str | None] | None = None,
    shopify_source_client_credentials: Mapping[str, tuple[str | None, str | None]] | None = None,
    lark_token: str | None,
    lark_app_id: str | None,
    lark_app_secret: str | None,
    google_token: str | None,
    meta_token: str | None,
    google_ads_token: str | None,
    google_ads_client_id: str | None,
    google_ads_client_secret: str | None,
    google_ads_refresh_token: str | None,
    google_ads_developer_token: str | None,
    google_ads_login_customer_id: str | None,
    pinterest_token: str | None,
    google_merchant_token: str | None,
    klaviyo_api_key: str | None,
    timeout_seconds: float,
    repository: IDataSourceRepository | None = None,
    artifact_service: ArtifactService | None = None,
) -> DataSourceRuntime:
    source_repository = repository or SqliteDataSourceRepository(db_path)
    artifacts = (
        ServiceSnapshotArtifactWriter(artifact_service)
        if artifact_service is not None
        else FilesystemSnapshotArtifactWriter(ArtifactStore(artifacts_root))
    )
    mock = MockDataConnector()
    real_connectors = {
        "shopify": ShopifyConnector(
            shopify_token,
            timeout_seconds,
            source_tokens=shopify_source_tokens,
            source_client_credentials=shopify_source_client_credentials,
        ),
        "lark": LarkConnector(lark_token, lark_app_id, lark_app_secret, timeout_seconds),
        "google": GoogleConnector(google_token, timeout_seconds),
        "meta_ads": MetaAdsConnector(meta_token, timeout_seconds),
        "google_ads": GoogleAdsConnector(
            google_ads_token,
            google_ads_developer_token,
            google_ads_login_customer_id,
            timeout_seconds,
            client_id=google_ads_client_id,
            client_secret=google_ads_client_secret,
            refresh_token=google_ads_refresh_token,
        ),
        "pinterest_ads": PinterestAdsConnector(pinterest_token, timeout_seconds),
        "google_merchant": GoogleMerchantConnector(google_merchant_token, timeout_seconds),
        "klaviyo": KlaviyoConnector(klaviyo_api_key, timeout_seconds),
    }
    mockable = ("shopify", "meta_ads", "google_ads")
    connectors = {
        provider: MockAwareConnector(connector, mock) if provider in mockable else connector
        for provider, connector in real_connectors.items()
    }
    return DataSourceRuntime(
        DataSourceSyncService(definitions, connectors, source_repository, artifacts),
        source_repository,
    )


__all__ = ["DataSourceRuntime", "build_runtime"]
