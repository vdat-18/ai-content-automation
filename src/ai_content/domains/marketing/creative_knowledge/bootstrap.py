"""One-time import boundary for curated Creative knowledge proposals."""

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .models import (
    LEGACY_GENERATION_STAGES,
    AppliedKnowledgeBootstrap,
    CreativeKnowledge,
    KnowledgeAuthority,
    KnowledgeScope,
    KnowledgeStage,
    KnowledgeType,
)
from .service import CreativeKnowledgeService

_SCHEMA_VERSION = "creative-knowledge-bootstrap@2"


@dataclass(frozen=True)
class KnowledgeBootstrapItem:
    knowledge_id: str
    knowledge_type: KnowledgeType
    title: str
    content: str
    scope: KnowledgeScope
    authority: KnowledgeAuthority
    source_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()
    non_conclusions: tuple[str, ...] = ()
    applies_to: tuple[KnowledgeStage, ...] = LEGACY_GENERATION_STAGES


@dataclass(frozen=True)
class KnowledgeBootstrapManifest:
    bootstrap_id: str
    schema_version: str
    checksum: str
    items: tuple[KnowledgeBootstrapItem, ...]


@dataclass(frozen=True)
class KnowledgeBootstrapResult:
    application: AppliedKnowledgeBootstrap
    imported: tuple[CreativeKnowledge, ...]
    applied: bool


def load_knowledge_bootstrap(path: Path) -> KnowledgeBootstrapManifest:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    schema_version = str(payload.get("schema_version", ""))
    if schema_version != _SCHEMA_VERSION:
        raise ValueError(f"Creative knowledge bootstrap requires {_SCHEMA_VERSION}")
    bootstrap_id = str(payload.get("bootstrap_id", "")).strip()
    if not bootstrap_id:
        raise ValueError("Creative knowledge bootstrap requires bootstrap_id")
    records = payload.get("items")
    if not isinstance(records, list):
        raise ValueError("Creative knowledge bootstrap requires an items list")
    items = tuple(_bootstrap_item(record) for record in records)
    if not items:
        raise ValueError("Creative knowledge bootstrap requires at least one item")
    identifiers = [item.knowledge_id for item in items]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Creative knowledge bootstrap IDs must be unique")
    return KnowledgeBootstrapManifest(
        bootstrap_id=bootstrap_id,
        schema_version=schema_version,
        checksum=sha256(raw).hexdigest(),
        items=items,
    )


async def import_knowledge_proposals(
    service: CreativeKnowledgeService,
    manifest: KnowledgeBootstrapManifest,
    *,
    contributor: str,
) -> KnowledgeBootstrapResult:
    previous = await service.repository.get_bootstrap(manifest.bootstrap_id)
    if previous is not None:
        if previous.checksum != manifest.checksum:
            raise ValueError("Applied Creative knowledge bootstrap checksum changed")
        return KnowledgeBootstrapResult(application=previous, imported=(), applied=False)

    existing_items = await service.repository.list()
    existing_by_id: dict[str, list[CreativeKnowledge]] = {}
    for existing_item in existing_items:
        existing_by_id.setdefault(existing_item.knowledge_id, []).append(existing_item)
    imported: list[CreativeKnowledge] = []
    for item in manifest.items:
        versions = existing_by_id.get(item.knowledge_id, [])
        latest = max(versions, key=lambda candidate: candidate.version) if versions else None
        if latest is not None and _matches_bootstrap(latest, item):
            continue
        proposed = await service.propose(
            knowledge_id=item.knowledge_id,
            knowledge_type=item.knowledge_type,
            title=item.title,
            content=item.content,
            scope=item.scope,
            authority=item.authority,
            source_refs=item.source_refs,
            evidence_refs=item.evidence_refs,
            applies_to=item.applies_to,
            contributor=contributor,
            non_conclusions=item.non_conclusions,
        )
        imported.append(proposed)
        existing_by_id.setdefault(item.knowledge_id, []).append(proposed)
    application = AppliedKnowledgeBootstrap(
        bootstrap_id=manifest.bootstrap_id,
        schema_version=manifest.schema_version,
        checksum=manifest.checksum,
        item_count=len(manifest.items),
        applied_by=contributor,
    )
    await service.repository.save_bootstrap(application)
    return KnowledgeBootstrapResult(
        application=application,
        imported=tuple(imported),
        applied=True,
    )


def _matches_bootstrap(item: CreativeKnowledge, expected: KnowledgeBootstrapItem) -> bool:
    return (
        item.knowledge_type == expected.knowledge_type
        and item.title == expected.title
        and item.content == expected.content
        and item.scope == expected.scope
        and item.authority == expected.authority
        and item.source_refs == expected.source_refs
        and item.evidence_refs == expected.evidence_refs
        and item.non_conclusions == expected.non_conclusions
        and item.applies_to == expected.applies_to
    )


def _bootstrap_item(payload: object) -> KnowledgeBootstrapItem:
    if not isinstance(payload, dict):
        raise ValueError("Creative knowledge bootstrap items must be objects")
    scope = payload.get("scope", {})
    if not isinstance(scope, dict):
        raise ValueError("Creative knowledge bootstrap scope must be an object")
    return KnowledgeBootstrapItem(
        knowledge_id=str(payload["knowledge_id"]),
        knowledge_type=KnowledgeType(str(payload["knowledge_type"])),
        title=str(payload["title"]),
        content=str(payload["content"]),
        scope=KnowledgeScope(**scope),
        authority=KnowledgeAuthority(str(payload["authority"])),
        source_refs=tuple(str(value) for value in payload["source_refs"]),
        evidence_refs=tuple(str(value) for value in payload.get("evidence_refs", ())),
        non_conclusions=tuple(str(value) for value in payload.get("non_conclusions", ())),
        applies_to=tuple(
            KnowledgeStage(str(value))
            for value in payload.get("applies_to", LEGACY_GENERATION_STAGES)
        ),
    )
