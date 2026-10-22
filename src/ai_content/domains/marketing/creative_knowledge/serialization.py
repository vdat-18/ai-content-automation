"""Stable JSON representation for Creative knowledge."""

from dataclasses import asdict
from datetime import datetime

from .models import (
    LEGACY_GENERATION_STAGES,
    CreativeKnowledge,
    KnowledgeAuthority,
    KnowledgeScope,
    KnowledgeStage,
    KnowledgeStatus,
    KnowledgeType,
)


def knowledge_to_dict(item: CreativeKnowledge) -> dict[str, object]:
    payload = asdict(item)
    for key in ("effective_from", "valid_until", "approved_at", "created_at"):
        value = payload[key]
        payload[key] = value.isoformat() if isinstance(value, datetime) else None
    return payload


def knowledge_from_dict(payload: dict[str, object]) -> CreativeKnowledge:
    scope = payload["scope"]
    if not isinstance(scope, dict):
        raise ValueError("Knowledge scope must be an object")
    return CreativeKnowledge(
        knowledge_id=str(payload["knowledge_id"]),
        version=int(payload["version"]),
        knowledge_type=KnowledgeType(str(payload["knowledge_type"])),
        title=str(payload["title"]),
        content=str(payload["content"]),
        scope=KnowledgeScope(**scope),
        status=KnowledgeStatus(str(payload["status"])),
        authority=KnowledgeAuthority(str(payload["authority"])),
        source_refs=tuple(str(value) for value in payload["source_refs"]),
        evidence_refs=tuple(str(value) for value in payload.get("evidence_refs", ())),
        applies_to=tuple(
            KnowledgeStage(str(value))
            for value in payload.get("applies_to", LEGACY_GENERATION_STAGES)
        ),
        contributor=str(payload["contributor"]) if payload.get("contributor") else None,
        non_conclusions=tuple(str(value) for value in payload.get("non_conclusions", ())),
        effective_from=_datetime(payload.get("effective_from")),
        valid_until=_datetime(payload.get("valid_until")),
        supersedes=str(payload["supersedes"]) if payload.get("supersedes") else None,
        approved_by=str(payload["approved_by"]) if payload.get("approved_by") else None,
        approved_at=_datetime(payload.get("approved_at")),
        created_at=_datetime(payload.get("created_at")) or datetime.now().astimezone(),
    )


def _datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None
