"""PostgreSQL-backed runtime composition for API and worker entrypoints."""

from __future__ import annotations

from pathlib import Path

from ai_content.domains.marketing.creative.adapters.automation_job_repositories import (
    PostgresCreativeAutomationJobRepository,
)
from ai_content.domains.marketing.creative.adapters.automation_state_repositories import (
    PostgresMarketingCreativeAutomationStateRepository,
)
from ai_content.domains.marketing.creative.adapters.automation_storage import (
    FileMarketingCreativeAutomationStorage,
    ObjectStorageMarketingCreativeAutomationStorage,
)
from ai_content.domains.marketing.creative.adapters.postgres_repository import (
    PostgresCreativeRepository,
)
from ai_content.domains.marketing.creative.bootstrap import CreativeRuntime
from ai_content.domains.marketing.creative.bootstrap import build_runtime as build_creative
from ai_content.domains.marketing.creative_feedback.adapters.baml_learning import (
    BamlPerformanceLearningAnalyzer,
)
from ai_content.domains.marketing.creative_feedback.adapters.postgres_repository import (
    PostgresCreativeFeedbackRepository,
)
from ai_content.domains.marketing.creative_feedback.application.evaluation import (
    RunCreativeFeedback,
)
from ai_content.domains.marketing.creative_feedback.bootstrap import CreativeFeedbackRuntime
from ai_content.domains.marketing.creative_feedback.config.learning import (
    PerformanceLearningConfig,
    load_performance_learning_config,
)
from ai_content.domains.marketing.creative_intake.adapters.postgres_repository import (
    PostgresCreativeIntakeRepository,
)
from ai_content.domains.marketing.creative_intake.application.resolution import (
    ResolveCreativeIntake,
)
from ai_content.domains.marketing.creative_intake.bootstrap import CreativeIntakeRuntime
from ai_content.domains.marketing.creative_knowledge.repositories import (
    PostgresCreativeKnowledgeRepository,
)
from ai_content.domains.marketing.creative_knowledge.service import CreativeKnowledgeService
from ai_content.domains.marketing.creative_loop.adapters.postgres_repository import (
    PostgresCreativeLoopRepository,
)
from ai_content.domains.marketing.creative_loop.application.workflow import RunCreativeLoop
from ai_content.domains.marketing.creative_loop.bootstrap import CreativeLoopRuntime
from ai_content.domains.marketing.creative_loop.config.fixtures import (
    load_creative_loop_fixture,
)
from ai_content.domains.marketing.data_sources.adapters.postgres_repository import (
    PostgresDataSourceRepository,
)
from ai_content.domains.marketing.media_lab.adapters.asset_postgres_repository import (
    PostgresMediaAssetRepository,
)
from ai_content.domains.marketing.performance_data.adapters.postgres_repository import (
    PostgresGmcRunRepository,
)
from ai_content.domains.marketing.performance_decisions.adapters.postgres_repository import (
    PostgresPerformanceDecisionRepository,
)
from ai_content.domains.marketing.performance_decisions.application.evaluation import (
    RunPerformanceDecision,
)
from ai_content.domains.marketing.performance_decisions.bootstrap import (
    PerformanceDecisionRuntime,
)
from ai_content.domains.marketing.research_crawler.repositories import (
    PostgresResearchCrawlRepository,
)
from ai_content.platform.ai_usage import AIUsageTracker, PostgresAIUsageRepository
from ai_content.platform.artifacts import (
    ArtifactService,
    ArtifactStore,
    ObjectStorage,
    PostgresArtifactCatalog,
)
from ai_content.platform.database import Database
from ai_content.platform.execution import CeleryCommandScheduler, PostgresCommandQueue
from ai_content.platform.notifications import PostgresNotificationRepository


class PostgresRuntimeContainer:
    """Compose request-scoped facades over one shared database engine."""

    def __init__(
        self,
        database: Database,
        artifacts_root: Path,
        config_dir: Path,
        preparation_config_path: Path | None = None,
        preparation_api_key: str | None = None,
        learning_config_path: Path | None = None,
        learning_api_key: str | None = None,
        execution_backend: str = "lease_worker",
        object_storage: ObjectStorage | None = None,
        object_storage_bucket: str | None = None,
    ) -> None:
        self.database = database
        self.artifacts_root = artifacts_root
        self.config_dir = config_dir
        self.preparation_config_path = (
            preparation_config_path or config_dir / "preparation/synthetic.json"
        )
        self.preparation_api_key = preparation_api_key
        self.learning_config: PerformanceLearningConfig | None = (
            load_performance_learning_config(learning_config_path)
            if learning_config_path is not None
            else None
        )
        self.learning_api_key = learning_api_key
        self.artifacts = ArtifactStore(artifacts_root)
        engine = database.engine
        self.ai_usage_repository = PostgresAIUsageRepository(engine)
        self.notification_repository = PostgresNotificationRepository(engine)
        self.ai_usage_tracker = AIUsageTracker(self.ai_usage_repository)
        self.object_storage = object_storage
        self.artifact_service = (
            ArtifactService(
                PostgresArtifactCatalog(engine),
                object_storage,
                object_storage_bucket,
            )
            if object_storage is not None and object_storage_bucket is not None
            else None
        )
        self.creative_repository = PostgresCreativeRepository(engine)
        self.creative_automation_job_repository = PostgresCreativeAutomationJobRepository(engine)
        self.creative_automation_state_repository = (
            PostgresMarketingCreativeAutomationStateRepository(engine)
        )
        self.creative_automation_storage = (
            ObjectStorageMarketingCreativeAutomationStorage(
                self.creative_automation_state_repository,
                self.artifact_service,
                artifacts_root / "scratch" / "creative-packages",
            )
            if self.artifact_service is not None
            else FileMarketingCreativeAutomationStorage(self.artifacts)
        )
        self.creative_loop_repository = PostgresCreativeLoopRepository(engine)
        self.creative_intake_repository = PostgresCreativeIntakeRepository(engine)
        self.creative_feedback_repository = PostgresCreativeFeedbackRepository(engine)
        self.creative_knowledge_repository = PostgresCreativeKnowledgeRepository(engine)
        self.creative_knowledge_service = CreativeKnowledgeService(
            self.creative_knowledge_repository
        )
        self.performance_repository = PostgresPerformanceDecisionRepository(engine)
        self.gmc_repository = PostgresGmcRunRepository(engine)
        self.data_source_repository = PostgresDataSourceRepository(engine)
        self.research_crawl_repository = PostgresResearchCrawlRepository(engine)
        self.media_lab_asset_repository = PostgresMediaAssetRepository(engine)
        self.execution_status_store = PostgresCommandQueue(engine)
        if execution_backend == "celery":
            self.execution_scheduler = CeleryCommandScheduler(engine)
        elif execution_backend == "lease_worker":
            self.execution_scheduler = self.execution_status_store
        else:
            raise ValueError("Execution backend must be lease_worker or celery")
        self.execution_queue = self.execution_scheduler

    def close(self) -> None:
        self.execution_scheduler.close()

    def creative(self) -> CreativeRuntime:
        return build_creative(
            None,
            self.artifacts_root,
            config_dir=self.config_dir,
            repository=self.creative_repository,
        )

    def performance(self) -> PerformanceDecisionRuntime:
        return PerformanceDecisionRuntime(
            self.performance_repository,
            self.artifacts,
            RunPerformanceDecision(self.performance_repository),
        )

    def intake(self) -> CreativeIntakeRuntime:
        return CreativeIntakeRuntime(
            self.creative_intake_repository,
            self.artifacts,
            ResolveCreativeIntake(self.creative_intake_repository),
            None,
            self.artifacts_root,
            self.creative_repository,
            self.preparation_api_key,
            self.ai_usage_tracker,
        )

    def feedback(self) -> CreativeFeedbackRuntime:
        analyzer = (
            BamlPerformanceLearningAnalyzer(
                self.learning_config,
                api_key=self.learning_api_key,
            )
            if self.learning_config is not None
            else None
        )
        return CreativeFeedbackRuntime(
            self.creative_feedback_repository,
            self.artifacts,
            RunCreativeFeedback(self.creative_feedback_repository, analyzer),
        )

    def creative_loop(self) -> CreativeLoopRuntime:
        performance = self.performance()
        intake = self.intake()
        creative = self.creative()
        feedback = self.feedback()
        fixture_path = self.config_dir / "fixtures/creative_loop_synthetic.json"
        preparation_config = self.preparation_config_path
        fixture = load_creative_loop_fixture(fixture_path)
        workflow = RunCreativeLoop(
            self.creative_loop_repository,
            performance,
            intake,
            creative,
            feedback,
            preparation_config=preparation_config,
            config_dir=self.config_dir,
        )
        return CreativeLoopRuntime(
            self.creative_loop_repository,
            self.artifacts,
            fixture,
            workflow,
            performance,
            intake,
            creative,
            feedback,
            self.artifact_service,
        )


__all__ = ["PostgresRuntimeContainer"]
