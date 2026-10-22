"""Runtime input contracts shared by Creative intake entrypoints."""

import hashlib
import json
from dataclasses import asdict, dataclass

from ai_content.domains.marketing.creative.ports.contracts import CreativeWorkItemInput
from ai_content.domains.marketing.creative.ports.preparation import PreparationContext

from ..domain.models import CreativeContextSnapshot, CreativeTaskTrigger
from .resolution import CreativeIntakeRequest


@dataclass(frozen=True)
class CreativeIntakeCase:
    request: CreativeIntakeRequest
    work_item_template: CreativeWorkItemInput
    context_template: PreparationContext


@dataclass(frozen=True)
class CreativeIntakeFixture:
    cases: tuple[CreativeIntakeCase, ...]


def intake_fingerprint(
    trigger: CreativeTaskTrigger,
    context: CreativeContextSnapshot,
    work_item: CreativeWorkItemInput,
    preparation: PreparationContext,
) -> str:
    work_payload = asdict(work_item)
    work_payload.pop("created_at")
    work_payload.pop("created_by")
    preparation_payload = asdict(preparation)
    preparation_payload["package"].pop("collected_at")
    payload = {
        "trigger": asdict(trigger),
        "context": asdict(context),
        "work_item": work_payload,
        "preparation": preparation_payload,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def case_for_trigger(
    fixture: CreativeIntakeFixture,
    context_snapshot_id: str,
    trigger: CreativeTaskTrigger,
) -> CreativeIntakeCase:
    source = next(
        (case for case in fixture.cases if case.request.context.snapshot_id == context_snapshot_id),
        None,
    )
    if source is None:
        raise ValueError("Creative context snapshot not found")
    checksum = intake_fingerprint(
        trigger,
        source.request.context,
        source.work_item_template,
        source.context_template,
    )
    return CreativeIntakeCase(
        CreativeIntakeRequest(trigger, source.request.context, checksum),
        source.work_item_template,
        source.context_template,
    )


__all__ = [
    "CreativeIntakeCase",
    "CreativeIntakeFixture",
    "case_for_trigger",
    "intake_fingerprint",
]
