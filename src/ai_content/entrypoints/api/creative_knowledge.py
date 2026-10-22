"""Admin API for versioned Marketing Creative knowledge."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ai_content.domains.marketing.creative_knowledge.bootstrap import (
    import_knowledge_proposals,
    load_knowledge_bootstrap,
)
from ai_content.domains.marketing.creative_knowledge.models import (
    LEGACY_GENERATION_STAGES,
    CreativeKnowledge,
    KnowledgeAuthority,
    KnowledgeScope,
    KnowledgeStage,
    KnowledgeStatus,
    KnowledgeType,
)
from ai_content.domains.marketing.creative_knowledge.service import CreativeKnowledgeService

from .dependencies import get_creative_knowledge_service, get_runtime_settings

router = APIRouter(prefix="/api/v1/marketing/creative-knowledge", tags=["creative-knowledge"])


class KnowledgeScopePayload(BaseModel):
    niche_id: str | None = None
    brand_id: str | None = None
    product_archetype: str | None = None
    product_family_id: str | None = None
    variant_id: str | None = None
    platform: str | None = None
    market: str | None = None
    asset_type: str | None = None
    task_type: str | None = None

    def to_domain(self) -> KnowledgeScope:
        return KnowledgeScope(**self.model_dump())


class KnowledgeProposalRequest(BaseModel):
    knowledge_id: str | None = None
    knowledge_type: KnowledgeType
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    scope: KnowledgeScopePayload = Field(default_factory=KnowledgeScopePayload)
    authority: KnowledgeAuthority
    source_refs: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    applies_to: list[KnowledgeStage] = Field(
        default_factory=lambda: list(LEGACY_GENERATION_STAGES),
        min_length=1,
    )
    contributor: str | None = None
    non_conclusions: list[str] = Field(default_factory=list)


class KnowledgeDecisionRequest(BaseModel):
    decision: KnowledgeStatus
    reviewer: str = Field(min_length=1)


class KnowledgeBootstrapRequest(BaseModel):
    contributor: str = Field(min_length=1)
    manifest_id: str = Field(
        default="creative_v3_2026_10_22",
        pattern=r"^[a-z0-9][a-z0-9_-]{0,127}$",
    )


class KnowledgeResponse(BaseModel):
    knowledge_id: str
    version: int
    version_ref: str
    knowledge_type: KnowledgeType
    title: str
    content: str
    scope: KnowledgeScopePayload
    status: KnowledgeStatus
    authority: KnowledgeAuthority
    source_refs: list[str]
    evidence_refs: list[str]
    applies_to: list[KnowledgeStage]
    contributor: str | None
    non_conclusions: list[str]
    supersedes: str | None
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime


class KnowledgeBootstrapResponse(BaseModel):
    bootstrap_id: str
    checksum: str
    applied: bool
    items: list[KnowledgeResponse]
    total: int


class KnowledgeListResponse(BaseModel):
    items: list[KnowledgeResponse]
    total: int


def _response(item: CreativeKnowledge) -> KnowledgeResponse:
    return KnowledgeResponse(
        knowledge_id=item.knowledge_id,
        version=item.version,
        version_ref=item.version_ref,
        knowledge_type=item.knowledge_type,
        title=item.title,
        content=item.content,
        scope=KnowledgeScopePayload(**item.scope.__dict__),
        status=item.status,
        authority=item.authority,
        source_refs=list(item.source_refs),
        evidence_refs=list(item.evidence_refs),
        applies_to=list(item.applies_to),
        contributor=item.contributor,
        non_conclusions=list(item.non_conclusions),
        supersedes=item.supersedes,
        approved_by=item.approved_by,
        approved_at=item.approved_at,
        created_at=item.created_at,
    )


@router.post("/bootstrap", response_model=KnowledgeBootstrapResponse)
async def bootstrap_knowledge(
    payload: KnowledgeBootstrapRequest,
    service: CreativeKnowledgeService = Depends(get_creative_knowledge_service),
) -> KnowledgeBootstrapResponse:
    path = get_runtime_settings().config_dir / "creative_knowledge" / f"{payload.manifest_id}.json"
    try:
        result = await import_knowledge_proposals(
            service,
            load_knowledge_bootstrap(path),
            contributor=payload.contributor,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Creative knowledge bootstrap configuration is invalid",
        ) from exc
    responses = [_response(item) for item in result.imported]
    return KnowledgeBootstrapResponse(
        bootstrap_id=result.application.bootstrap_id,
        checksum=result.application.checksum,
        applied=result.applied,
        items=responses,
        total=len(responses),
    )


@router.post("", response_model=KnowledgeResponse, status_code=status.HTTP_201_CREATED)
async def propose_knowledge(
    payload: KnowledgeProposalRequest,
    service: CreativeKnowledgeService = Depends(get_creative_knowledge_service),
) -> KnowledgeResponse:
    item = await service.propose(
        knowledge_id=payload.knowledge_id,
        knowledge_type=payload.knowledge_type,
        title=payload.title,
        content=payload.content,
        scope=payload.scope.to_domain(),
        authority=payload.authority,
        source_refs=tuple(payload.source_refs),
        evidence_refs=tuple(payload.evidence_refs),
        applies_to=tuple(payload.applies_to),
        contributor=payload.contributor,
        non_conclusions=tuple(payload.non_conclusions),
    )
    return _response(item)


@router.get("", response_model=KnowledgeListResponse)
async def list_knowledge(
    status_filter: KnowledgeStatus | None = Query(default=None, alias="status"),
    service: CreativeKnowledgeService = Depends(get_creative_knowledge_service),
) -> KnowledgeListResponse:
    items = await service.repository.list()
    if status_filter is not None:
        items = [item for item in items if item.status == status_filter]
    responses = [_response(item) for item in items]
    return KnowledgeListResponse(items=responses, total=len(responses))


@router.post("/{knowledge_id}/versions/{version}/decision", response_model=KnowledgeResponse)
async def decide_knowledge(
    knowledge_id: str,
    version: int,
    payload: KnowledgeDecisionRequest,
    service: CreativeKnowledgeService = Depends(get_creative_knowledge_service),
) -> KnowledgeResponse:
    if payload.decision not in {KnowledgeStatus.APPROVED, KnowledgeStatus.REJECTED}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="decision must be approved or rejected",
        )
    try:
        item = await service.decide(
            knowledge_id,
            version,
            status=payload.decision,
            reviewer=payload.reviewer,
        )
    except ValueError as exc:
        code = status.HTTP_404_NOT_FOUND if "not found" in str(exc) else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return _response(item)


@router.post("/{knowledge_id}/versions/{version}/conflict", response_model=KnowledgeResponse)
async def mark_knowledge_conflict(
    knowledge_id: str,
    version: int,
    service: CreativeKnowledgeService = Depends(get_creative_knowledge_service),
) -> KnowledgeResponse:
    try:
        return _response(await service.mark_conflict(knowledge_id, version))
    except ValueError as exc:
        code = status.HTTP_404_NOT_FOUND if "not found" in str(exc) else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/resolve", response_model=KnowledgeListResponse)
async def resolve_knowledge(
    scope: KnowledgeScopePayload,
    stage: KnowledgeStage | None = Query(default=None),
    service: CreativeKnowledgeService = Depends(get_creative_knowledge_service),
) -> KnowledgeListResponse:
    responses = [_response(item) for item in await service.resolve(scope.to_domain(), stage=stage)]
    return KnowledgeListResponse(items=responses, total=len(responses))
