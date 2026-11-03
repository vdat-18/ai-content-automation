"""PostgreSQL-backed repositories shared by API request handlers."""

from __future__ import annotations

from ai_content.domains.marketing.creative_knowledge.repositories import (
    PostgresCreativeKnowledgeRepository,
)
from ai_content.domains.marketing.creative_knowledge.service import CreativeKnowledgeService
from ai_content.domains.marketing.products.repositories import PostgresProductRepository
from ai_content.platform.ai_usage import PostgresAIUsageRepository
from ai_content.platform.database import Database
from ai_content.platform.notifications import PostgresNotificationRepository


class PostgresRuntimeContainer:
    """Own the repositories created from one PostgreSQL engine."""

    def __init__(self, database: Database) -> None:
        self.database = database
        engine = database.engine
        self.ai_usage_repository = PostgresAIUsageRepository(engine)
        self.notification_repository = PostgresNotificationRepository(engine)
        self.creative_knowledge_service = CreativeKnowledgeService(
            PostgresCreativeKnowledgeRepository(engine)
        )
        self.product_repository = PostgresProductRepository(engine)
