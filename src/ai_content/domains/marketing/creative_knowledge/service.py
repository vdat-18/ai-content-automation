"""Application service for knowledge proposal, review and resolution."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from .models import (
    LEGACY_GENERATION_STAGES,
    CreativeKnowledge,
    KnowledgeAuthority,
    KnowledgeScope,
    KnowledgeStage,
    KnowledgeStatus,
    KnowledgeType,
)
from .repository import CreativeKnowledgeRepository, resolve_approved_knowledge


class CreativeKnowledgeService:
    def __init__(self, repository: CreativeKnowledgeRepository) -> None:
        self.repository = repository

    async def propose(
        self,
        *,
        knowledge_id: str | None,
        knowledge_type: KnowledgeType,
        title: str,
        content: str,
        scope: KnowledgeScope,
        authority: KnowledgeAuthority,
        source_refs: tuple[str, ...],
        evidence_refs: tuple[str, ...] = (),
        applies_to: tuple[KnowledgeStage, ...] = LEGACY_GENERATION_STAGES,
        contributor: str | None = None,
        non_conclusions: tuple[str, ...] = (),
    ) -> CreativeKnowledge:
        identifier = knowledge_id or f"knowledge-{uuid4().hex}"
        versions = [
            item for item in await self.repository.list() if item.knowledge_id == identifier
        ]
        latest = max(versions, key=lambda item: item.version) if versions else None
        item = CreativeKnowledge(
            knowledge_id=identifier,
            version=(latest.version + 1 if latest else 1),
            knowledge_type=knowledge_type,
            title=title,
            content=content,
            scope=scope,
            status=KnowledgeStatus.PROPOSED,
            authority=authority,
            source_refs=source_refs,
            evidence_refs=evidence_refs,
            applies_to=applies_to,
            contributor=contributor,
            non_conclusions=non_conclusions,
            supersedes=latest.version_ref if latest else None,
        )
        await self.repository.save(item)
        return item

    async def decide(
        self,
        knowledge_id: str,
        version: int,
        *,
        status: KnowledgeStatus,
        reviewer: str,
    ) -> CreativeKnowledge:
        item = await self.repository.get(knowledge_id, version)
        if item is None:
            raise ValueError("Creative knowledge version not found")
        decided = item.decide(status, reviewer)
        if status == KnowledgeStatus.APPROVED:
            for previous in await self.repository.list():
                if (
                    previous.knowledge_id == knowledge_id
                    and previous.version != version
                    and previous.status == KnowledgeStatus.APPROVED
                ):
                    await self.repository.save(previous.supersede())
        await self.repository.save(decided)
        return decided

    async def mark_conflict(self, knowledge_id: str, version: int) -> CreativeKnowledge:
        item = await self.repository.get(knowledge_id, version)
        if item is None:
            raise ValueError("Creative knowledge version not found")
        if item.status not in {KnowledgeStatus.DRAFT, KnowledgeStatus.PROPOSED}:
            raise ValueError("Only draft or proposed knowledge can be marked as conflict")
        conflicted = replace(item, status=KnowledgeStatus.CONFLICT)
        await self.repository.save(conflicted)
        return conflicted

    async def resolve(
        self,
        scope: KnowledgeScope,
        *,
        stage: KnowledgeStage | None = None,
    ) -> tuple[CreativeKnowledge, ...]:
        return resolve_approved_knowledge(
            await self.repository.list(),
            scope,
            stage=stage,
        )

    async def record_feedback(
        self,
        *,
        feedback_id: str,
        title: str,
        content: str,
        scope: KnowledgeScope,
        reviewer: str,
        source_refs: tuple[str, ...],
        non_conclusions: tuple[str, ...],
    ) -> CreativeKnowledge:
        """Persist trusted human feedback once at its exact Creative scope."""

        existing = await self.repository.get(feedback_id, 1)
        if existing is not None:
            if (
                existing.knowledge_type != KnowledgeType.FEEDBACK
                or existing.title != title
                or existing.content != content
                or existing.scope != scope
                or existing.contributor != reviewer
                or existing.source_refs != source_refs
                or existing.non_conclusions != non_conclusions
            ):
                raise ValueError("Feedback identity was already used for different content")
            return existing
        item = CreativeKnowledge(
            knowledge_id=feedback_id,
            version=1,
            knowledge_type=KnowledgeType.FEEDBACK,
            title=title,
            content=content,
            scope=scope,
            status=KnowledgeStatus.APPROVED,
            authority=KnowledgeAuthority.INDIVIDUAL,
            source_refs=source_refs,
            evidence_refs=source_refs,
            applies_to=(
                KnowledgeStage.PREPARATION,
                KnowledgeStage.ORCHESTRATION,
                KnowledgeStage.REVISION,
            ),
            contributor=reviewer,
            non_conclusions=non_conclusions,
            approved_by=reviewer,
            approved_at=datetime.now(UTC),
        )
        await self.repository.save(item)
        return item
