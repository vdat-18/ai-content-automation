"""Persistence and resolution contracts for Creative knowledge."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from .models import (
    AUTHORITY_RANK,
    TYPE_RANK,
    AppliedKnowledgeBootstrap,
    CreativeKnowledge,
    KnowledgeScope,
    KnowledgeStage,
)


class CreativeKnowledgeRepository(Protocol):
    async def save(self, item: CreativeKnowledge) -> None: ...
    async def get(self, knowledge_id: str, version: int) -> CreativeKnowledge | None: ...
    async def list(self) -> list[CreativeKnowledge]: ...
    async def get_bootstrap(self, bootstrap_id: str) -> AppliedKnowledgeBootstrap | None: ...
    async def save_bootstrap(self, bootstrap: AppliedKnowledgeBootstrap) -> None: ...


def resolve_approved_knowledge(
    items: list[CreativeKnowledge],
    scope: KnowledgeScope,
    *,
    as_of: datetime | None = None,
    stage: KnowledgeStage | None = None,
) -> tuple[CreativeKnowledge, ...]:
    now = as_of or datetime.now(UTC)
    latest: dict[str, CreativeKnowledge] = {}
    for item in (candidate for candidate in items if candidate.active_at(now)):
        current = latest.get(item.knowledge_id)
        if current is None or item.version > current.version:
            latest[item.knowledge_id] = item
    matched = [
        item
        for item in latest.values()
        if item.scope.matches(scope) and (stage is None or stage in item.applies_to)
    ]
    return tuple(
        sorted(
            matched,
            key=lambda item: (
                -TYPE_RANK[item.knowledge_type],
                -item.scope.specificity(),
                -AUTHORITY_RANK[item.authority],
                item.knowledge_id,
            ),
        )
    )
