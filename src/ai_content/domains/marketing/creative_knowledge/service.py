"""Application service for knowledge proposal, review and resolution."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
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


@dataclass(frozen=True)
class CuratedKnowledge:
    """A cleaned rewrite of an approved item and the older items it makes redundant."""

    title: str
    content: str
    replaces: tuple[str, ...] = ()


class KnowledgeCurator(Protocol):
    async def rewrite(
        self, item: CreativeKnowledge, others: tuple[CreativeKnowledge, ...]
    ) -> CuratedKnowledge | None: ...


class CreativeKnowledgeService:
    def __init__(self, repository: CreativeKnowledgeRepository) -> None:
        self.repository = repository

    async def _curable_others(self, item: CreativeKnowledge) -> tuple[CreativeKnowledge, ...]:
        """The approved rules a new rule may be folded into; hard rules are never touched."""
        return tuple(
            other
            for other in await self.resolve(item.scope)
            if other.knowledge_id != item.knowledge_id
            and other.knowledge_type != KnowledgeType.HARD_RULE
        )

    async def curate(self, knowledge_id: str, curator: KnowledgeCurator) -> CreativeKnowledge:
        """Let the curator rewrite an approved item and retire the items it replaces."""
        item = await self.repository.get(knowledge_id)
        if item is None:
            raise ValueError("Creative knowledge not found")
        if item.status != KnowledgeStatus.APPROVED:
            raise ValueError("Only approved knowledge can be curated")
        others = await self._curable_others(item)
        curated = await curator.rewrite(item, others)
        if curated is None:
            return item
        for other in others:
            if other.knowledge_id in curated.replaces:
                await self.repository.save(replace(other, status=KnowledgeStatus.EXPIRED))
        rewritten = replace(item, title=curated.title, content=curated.content)
        await self.repository.save(rewritten)
        return rewritten

    async def learn(
        self, knowledge_id: str, curator: KnowledgeCurator, reviewer: str
    ) -> CreativeKnowledge:
        """Turn a proposed item into a rule in the rulebook's form and approve it in one step.

        The item is approved only with the curator's rewrite: when the curator cannot answer the
        item stays proposed instead of entering the rulebook as raw feedback.
        """
        item = await self.repository.get(knowledge_id)
        if item is None:
            raise ValueError("Creative knowledge not found")
        others = await self._curable_others(item)
        curated = await curator.rewrite(item, others)
        if curated is None:
            return item
        for other in others:
            if other.knowledge_id in curated.replaces:
                await self.repository.save(replace(other, status=KnowledgeStatus.EXPIRED))
        rule = replace(
            item.decide(KnowledgeStatus.APPROVED, reviewer),
            title=curated.title,
            content=curated.content,
        )
        await self.repository.save(rule)
        return rule

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
        existing = await self.repository.get(identifier)
        item = CreativeKnowledge(
            knowledge_id=identifier,
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
            created_at=existing.created_at if existing else datetime.now(UTC),
        )
        await self.repository.save(item)
        return item

    async def decide(
        self,
        knowledge_id: str,
        *,
        status: KnowledgeStatus,
        reviewer: str,
    ) -> CreativeKnowledge:
        item = await self.repository.get(knowledge_id)
        if item is None:
            raise ValueError("Creative knowledge not found")
        decided = item.decide(status, reviewer)
        await self.repository.save(decided)
        return decided

    async def retire(self, knowledge_id: str) -> CreativeKnowledge:
        """Turn an approved item off so it is no longer used."""
        item = await self.repository.get(knowledge_id)
        if item is None:
            raise ValueError("Creative knowledge not found")
        if item.status != KnowledgeStatus.APPROVED:
            raise ValueError("Only approved knowledge can be turned off")
        retired = replace(item, status=KnowledgeStatus.EXPIRED)
        await self.repository.save(retired)
        return retired

    async def mark_conflict(self, knowledge_id: str) -> CreativeKnowledge:
        item = await self.repository.get(knowledge_id)
        if item is None:
            raise ValueError("Creative knowledge not found")
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

        existing = await self.repository.get(feedback_id)
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
