"""Composition root for an opt-in, supervised brief-only run."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from ai_content.platform.ai_usage import AIUsageTracker
from ai_content.platform.artifacts.store import ArtifactStore

from .adapters.preparation_artifacts import FilePreparationStore
from .adapters.sqlite_repository import SqliteCreativeRepository
from .application.preparation import PreparationResult, PrepareCreativeBrief
from .config.loader import ConfigLoader
from .config.preparation import PreparationConfig
from .ports.contracts import CreativeWorkItemInput
from .ports.interfaces import ICreativeRepository
from .ports.preparation import IPreparationModel, PreparationContext


def preparation_fingerprint(
    work_item: CreativeWorkItemInput, context: PreparationContext, config: PreparationConfig
) -> str:
    work = asdict(work_item)
    work.pop("created_at")
    work.pop("created_by")
    pack = asdict(context)
    pack["package"].pop("collected_at")
    payload = {"work_item": work, "context": pack, "config_hash": config.config_hash}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


class PreparationRuntime:
    def __init__(
        self,
        repository: ICreativeRepository,
        store: FilePreparationStore,
        config: PreparationConfig,
        context: PreparationContext,
        use_case: PrepareCreativeBrief,
        config_loader: ConfigLoader,
    ) -> None:
        self.repository = repository
        self.store = store
        self.config = config
        self.context = context
        self.use_case = use_case
        self.config_loader = config_loader

    async def prepare(self, work_item: CreativeWorkItemInput) -> PreparationResult:
        self.config_loader.validate_work_item_versions(
            prompt_id=work_item.prompt_version.prompt_id,
            prompt_version=work_item.prompt_version.version,
            rubric_id=work_item.rubric_version.rubric_id,
            rubric_version=work_item.rubric_version.version,
            policy_id=work_item.policy_version.policy_id,
            policy_version=work_item.policy_version.version,
            rule_id=work_item.rule_version.rule_id,
            rule_version=work_item.rule_version.version,
            workflow_id=work_item.workflow_version.workflow_id,
            workflow_version=work_item.workflow_version.version,
        )
        fingerprint = preparation_fingerprint(work_item, self.context, self.config)
        try:
            async with asyncio.timeout(self.config.run_timeout_seconds):
                return await self.use_case.execute(work_item, fingerprint)
        except TimeoutError:
            job = await self.repository.get_job_by_source_run_id(work_item.source_run_id)
            if job is None:
                raise
            return await self.use_case.record_failure(
                job, "preparation_timeout", "Preparation deadline exceeded", []
            )


def build_preparation_runtime(
    db_path: Path | None,
    artifacts_root: Path,
    config: PreparationConfig,
    context: PreparationContext,
    *,
    model: IPreparationModel | None = None,
    api_key: str | None = None,
    config_dir: Path = Path("config"),
    repository: ICreativeRepository | None = None,
    usage_tracker: AIUsageTracker | None = None,
    image_reader: Callable[[str], bytes] | None = None,
) -> PreparationRuntime:
    if model is None:
        if config.backend == "fake":
            from .adapters.fake_preparation import FakePreparationModel

            model = FakePreparationModel(config)
        else:
            from .adapters.baml_preparation import BamlPreparationModel

            model = BamlPreparationModel(
                config,
                api_key=api_key,
                usage_tracker=usage_tracker,
                image_reader=image_reader,
            )
    if repository is None:
        if db_path is None:
            raise ValueError("db_path is required when no repository is provided")
        repository = SqliteCreativeRepository(db_path)
    store = FilePreparationStore(ArtifactStore(artifacts_root))
    use_case = PrepareCreativeBrief(
        repository,
        store,
        context,
        model,
        max_ideas=config.max_ideas,
        max_brief_revisions=config.max_brief_revisions,
        max_critique_attempts=config.max_attempts,
        selection_rule_version=config.selection_rule_version,
        configuration=config.model_dump(mode="json"),
    )
    return PreparationRuntime(
        repository, store, config, context, use_case, ConfigLoader(config_dir)
    )
