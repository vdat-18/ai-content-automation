"""Approved SecondBrain rules for product ads, and the LLM that keeps them tidy."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import NamedTuple

from baml_py.baml_py import BamlError
from loguru import logger

from ai_content.domains.marketing.creative_knowledge.models import (
    CreativeKnowledge,
    KnowledgeAuthority,
    KnowledgeScope,
    KnowledgeStage,
    KnowledgeType,
)
from ai_content.domains.marketing.creative_knowledge.service import (
    CreativeKnowledgeService,
    CuratedKnowledge,
)
from ai_content.domains.marketing.products.adapters.baml_client.async_client import b
from ai_content.domains.marketing.products.adapters.baml_registry import build_client_registry

PRODUCT_AD_SCOPE = KnowledgeScope(task_type="product_ad")
FEEDBACK_SOURCE = "feedback:"  # source_refs prefix of items that came from feedback
_FEEDBACK_STAGES = {
    "brief": (KnowledgeStage.PREPARATION, KnowledgeStage.REVIEW),
    "keyframe": (KnowledgeStage.ORCHESTRATION, KnowledgeStage.REVIEW),
}


class ApprovedRules(NamedTuple):
    text: str  # a bullet list for the prompt
    ids: list[str]  # which rules were used, kept with the result so it can be traced


async def approved_rules(
    knowledge: CreativeKnowledgeService | None, stage: KnowledgeStage, asset_type: str
) -> ApprovedRules:
    """The approved rules for one stage of making one kind of asset (brief, keyframe)."""
    if knowledge is None:
        return ApprovedRules("", [])
    scope = replace(PRODUCT_AD_SCOPE, asset_type=asset_type)
    items = await knowledge.resolve(scope, stage=stage)
    text = "\n".join(f"- {item.title}: {item.content}" for item in items)
    return ApprovedRules(text, [item.knowledge_id for item in items])


async def propose_feedback(
    knowledge: CreativeKnowledgeService,
    *,
    product_id: str,
    text: str,
    contributor: str,
    authority: KnowledgeAuthority,
    asset_type: str = "keyframe",
) -> CreativeKnowledge:
    """Store feedback on a generated image or video as a proposal that a human must approve."""
    text = text.strip()
    digest = hashlib.sha1(f"{asset_type}:{text}".casefold().encode()).hexdigest()[:12]
    return await knowledge.propose(
        knowledge_id=f"feedback-{digest}",
        knowledge_type=KnowledgeType.LESSON,
        title=text[:80],
        content=text,
        scope=replace(PRODUCT_AD_SCOPE, asset_type=asset_type),
        authority=authority,
        source_refs=(f"{FEEDBACK_SOURCE}{product_id}",),
        applies_to=_FEEDBACK_STAGES[asset_type],
        contributor=contributor,
    )


class BamlKnowledgeCurator:
    """Rewrite an approved rule into the rulebook's form and find the rules it replaces."""

    def __init__(self, client: object) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, *, base_url: str, api_key: str, model: str) -> BamlKnowledgeCurator:
        registry = build_client_registry(
            name="KnowledgeCuration",
            base_url=base_url,
            model=model,
            api_key=api_key,
            reasoning_effort=None,
            temperature=0,
            max_output_tokens=2000,
        )
        return cls(b.with_options(client_registry=registry))

    async def rewrite(
        self, item: CreativeKnowledge, others: tuple[CreativeKnowledge, ...]
    ) -> CuratedKnowledge | None:
        existing = "\n".join(f"{o.knowledge_id}: {o.title}: {o.content}" for o in others)
        try:
            result = await self._client.CurateKnowledge(  # type: ignore[attr-defined]
                f"{item.title}: {item.content}", existing or "(none)"
            )
        except BamlError as error:
            logger.warning("Knowledge curation failed: {}", str(error)[:300])
            return None
        return CuratedKnowledge(
            title=result.title.strip(),
            content=result.content.strip(),
            replaces=tuple(result.replaces),
        )
