"""Stable JSON serialization for Creator Operations runs."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any

from ..domain.models import (
    CampaignRequirement,
    CandidateDecision,
    CreatorEvaluationRun,
    CreatorProfile,
    CriterionAssessment,
    CriterionOutcome,
    EvaluationState,
    EvaluationVersion,
    HandoffState,
    LarkDataPreview,
    PreviewAction,
    PreviewField,
)


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def run_to_dict(run: CreatorEvaluationRun) -> dict[str, Any]:
    return {"schema_version": 1, **_json_value(asdict(run))}


def run_from_dict(data: dict[str, Any]) -> CreatorEvaluationRun:
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported Creator Operations schema version")
    campaign = CampaignRequirement(**data["campaign"])
    creator = CreatorProfile(**data["creator"])
    evaluations = tuple(
        EvaluationVersion(
            evaluation_id=item["evaluation_id"],
            version_number=item["version_number"],
            package_id=item["package_id"],
            state=EvaluationState(item["state"]),
            criteria=tuple(
                CriterionAssessment(
                    criterion=criterion["criterion"],
                    outcome=CriterionOutcome(criterion["outcome"]),
                    evidence_refs=tuple(criterion["evidence_refs"]),
                    detail=criterion["detail"],
                    missing_fields=tuple(criterion.get("missing_fields", ())),
                )
                for criterion in item["criteria"]
            ),
            created_at=datetime.fromisoformat(item["created_at"]),
            policy_version=item["policy_version"],
        )
        for item in data["evaluations"]
    )
    preview_data = data["preview"]
    preview = LarkDataPreview(
        mapping_version=preview_data["mapping_version"],
        target_base_ref=preview_data["target_base_ref"],
        state=HandoffState(preview_data["state"]),
        fields=tuple(
            PreviewField(
                target_field=item["target_field"],
                current_value=item.get("current_value"),
                proposed_value=item.get("proposed_value"),
                action=PreviewAction(item["action"]),
                source_ref=item.get("source_ref"),
            )
            for item in preview_data["fields"]
        ),
    )
    return CreatorEvaluationRun(
        run_id=data["run_id"],
        source_run_id=data["source_run_id"],
        source_checksum_sha256=data["source_checksum_sha256"],
        campaign=campaign,
        creator=creator,
        candidate_id=data["candidate_id"],
        policy_version=data["policy_version"],
        location_reference_store_id=data["location_reference_store_id"],
        location_reference_version=data["location_reference_version"],
        evaluations=evaluations,
        preview=preview,
        created_at=datetime.fromisoformat(data["created_at"]),
        decision=CandidateDecision(data["decision"]) if data.get("decision") else None,
        decision_version_id=data.get("decision_version_id"),
        reviewer_alias=data.get("reviewer_alias"),
        decision_reason=data.get("decision_reason"),
        decided_at=datetime.fromisoformat(data["decided_at"]) if data.get("decided_at") else None,
        audit_log=tuple(data.get("audit_log", ())),
    )


__all__ = ["run_from_dict", "run_to_dict"]
