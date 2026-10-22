"""SQLite-backed ICreativeRepository for the local pilot harness.

Schema is pilot-local (SQLite); production moves to PostgreSQL via migration
when needed. Job rows exclude versions; versions live in their own table and
are reassembled on load ordered by attempt number.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..domain.entities import (
    ApprovalCard,
    ApprovalDecision,
    AssetVersion,
    AuditEntry,
    Cost,
    CreativeJob,
    CreativeJobId,
    CreativeJobStatus,
    LineageEntry,
    VersionId,
)
from ..domain.reviews import (
    CriterionReview,
    CriterionStatus,
    IssueSeverity,
    RepairAction,
    ReviewEvidence,
    ReviewOutcome,
    SemanticIssue,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    source_run_id TEXT,
    status TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_source_run_id
    ON jobs(source_run_id) WHERE source_run_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS versions (
    version_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    payload TEXT NOT NULL
);
"""


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _cost_to_dict(cost: Cost | None) -> dict[str, str] | None:
    if cost is None:
        return None
    return {"amount": str(cost.amount), "currency": cost.currency}


def _cost_from_dict(data: dict[str, str] | None) -> Cost | None:
    if data is None:
        return None
    return Cost(Decimal(data["amount"]), data["currency"])


def _details_to_list(details: tuple[tuple[str, Any], ...]) -> list[list[Any]]:
    return [[k, v] for k, v in details]


def _details_from_list(data: list[list[Any]] | None) -> tuple[tuple[str, Any], ...]:
    return tuple((str(k), v) for k, v in data or ())


def _criterion_to_dict(item: CriterionReview) -> dict[str, Any]:
    return {
        "criterion_id": item.criterion_id,
        "status": item.status.value,
        "reason": item.reason,
        "score": str(item.score) if item.score is not None else None,
        "confidence": str(item.confidence) if item.confidence is not None else None,
        "evidence_refs": list(item.evidence_refs),
    }


def _criterion_from_dict(data: dict[str, Any]) -> CriterionReview:
    return CriterionReview(
        criterion_id=data["criterion_id"],
        status=CriterionStatus(data["status"]),
        reason=data["reason"],
        score=Decimal(data["score"]) if data.get("score") is not None else None,
        confidence=(Decimal(data["confidence"]) if data.get("confidence") is not None else None),
        evidence_refs=tuple(data.get("evidence_refs", ())),
    )


def _evidence_to_dict(item: ReviewEvidence) -> dict[str, Any]:
    return {
        "evidence_id": item.evidence_id,
        "description": item.description,
        "source_ref": item.source_ref,
        "region": [str(value) for value in item.region] if item.region else None,
    }


def _evidence_from_dict(data: dict[str, Any]) -> ReviewEvidence:
    region = data.get("region")
    return ReviewEvidence(
        evidence_id=data["evidence_id"],
        description=data["description"],
        source_ref=data["source_ref"],
        region=tuple(Decimal(value) for value in region) if region else None,
    )


def _semantic_issue_to_dict(item: SemanticIssue) -> dict[str, Any]:
    return {
        "code": item.code,
        "criterion_id": item.criterion_id,
        "severity": item.severity.value,
        "repair_action": item.repair_action.value,
        "description": item.description,
        "evidence_refs": list(item.evidence_refs),
    }


def _semantic_issue_from_dict(data: dict[str, Any]) -> SemanticIssue:
    return SemanticIssue(
        code=data["code"],
        criterion_id=data["criterion_id"],
        severity=IssueSeverity(data["severity"]),
        repair_action=RepairAction(data["repair_action"]),
        description=data["description"],
        evidence_refs=tuple(data.get("evidence_refs", ())),
    )


def _version_to_dict(version: AssetVersion) -> dict[str, Any]:
    return {
        "version_id": version.version_id.value,
        "attempt_number": version.attempt_number,
        "input_ref": version.input_ref,
        "artifact_url": version.artifact_url,
        "artifact_path": version.artifact_path,
        "cost": _cost_to_dict(version.cost),
        "input_hash": version.input_hash,
        "prompt_version": version.prompt_version,
        "rubric_version": version.rubric_version,
        "policy_version": version.policy_version,
        "workflow_version": version.workflow_version,
        "generator_version": version.generator_version,
        "seed": version.seed,
        "qa_passed": version.qa_passed,
        "qa_score": str(version.qa_score) if version.qa_score is not None else None,
        "qa_issues": list(version.qa_issues),
        "qa_warnings": list(version.qa_warnings),
        "qa_feedback": version.qa_feedback,
        "qa_outcome": version.qa_outcome.value if version.qa_outcome else None,
        "qa_retryable": version.qa_retryable,
        "qa_requires_human_review": version.qa_requires_human_review,
        "qa_repair_actions": [item.value for item in version.qa_repair_actions],
        "qa_evidence_refs": list(version.qa_evidence_refs),
        "qa_reviewer_version": version.qa_reviewer_version,
        "qa_criteria": [_criterion_to_dict(item) for item in version.qa_criteria],
        "qa_semantic_issues": [
            _semantic_issue_to_dict(item) for item in version.qa_semantic_issues
        ],
        "qa_evidence": [_evidence_to_dict(item) for item in version.qa_evidence],
        "creative_set_id": version.creative_set_id,
        "variation_id": version.variation_id,
        "variation_attempt_number": version.variation_attempt_number,
        "created_at": _iso(version.created_at),
    }


def _version_from_dict(data: dict[str, Any]) -> AssetVersion:
    return AssetVersion(
        version_id=VersionId.from_string(data["version_id"]),
        attempt_number=data["attempt_number"],
        input_ref=data["input_ref"],
        artifact_url=data.get("artifact_url"),
        artifact_path=data.get("artifact_path"),
        cost=_cost_from_dict(data.get("cost")),
        input_hash=data.get("input_hash"),
        prompt_version=data.get("prompt_version"),
        rubric_version=data.get("rubric_version"),
        policy_version=data.get("policy_version"),
        workflow_version=data.get("workflow_version"),
        generator_version=data.get("generator_version"),
        seed=data.get("seed"),
        qa_passed=data.get("qa_passed"),
        qa_score=Decimal(data["qa_score"]) if data.get("qa_score") is not None else None,
        qa_issues=tuple(data.get("qa_issues", ())),
        qa_warnings=tuple(data.get("qa_warnings", ())),
        qa_feedback=data.get("qa_feedback"),
        qa_outcome=ReviewOutcome(data["qa_outcome"]) if data.get("qa_outcome") else None,
        qa_retryable=data.get("qa_retryable", True),
        qa_requires_human_review=data.get("qa_requires_human_review", False),
        qa_repair_actions=tuple(RepairAction(value) for value in data.get("qa_repair_actions", ())),
        qa_evidence_refs=tuple(data.get("qa_evidence_refs", ())),
        qa_reviewer_version=data.get("qa_reviewer_version"),
        qa_criteria=tuple(_criterion_from_dict(item) for item in data.get("qa_criteria", ())),
        qa_semantic_issues=tuple(
            _semantic_issue_from_dict(item) for item in data.get("qa_semantic_issues", ())
        ),
        qa_evidence=tuple(_evidence_from_dict(item) for item in data.get("qa_evidence", ())),
        creative_set_id=data.get("creative_set_id"),
        variation_id=data.get("variation_id"),
        variation_attempt_number=data.get("variation_attempt_number", 1),
        created_at=_parse_dt(data.get("created_at")) or datetime.now(),
    )


def _audit_to_dict(entry: AuditEntry) -> dict[str, Any]:
    return {
        "timestamp": _iso(entry.timestamp),
        "action": entry.action,
        "actor": entry.actor,
        "details": _details_to_list(entry.details),
    }


def _audit_from_dict(data: dict[str, Any]) -> AuditEntry:
    return AuditEntry(
        timestamp=_parse_dt(data["timestamp"]) or datetime.now(),
        action=data["action"],
        actor=data["actor"],
        details=_details_from_list(data["details"]),
    )


def _lineage_to_dict(entry: LineageEntry) -> dict[str, Any]:
    return {
        "entry_type": entry.entry_type,
        "ref": entry.ref,
        "parent_ref": entry.parent_ref,
        "details": _details_to_list(entry.details),
        "recorded_at": _iso(entry.recorded_at),
    }


def _lineage_from_dict(data: dict[str, Any]) -> LineageEntry:
    return LineageEntry(
        entry_type=data["entry_type"],
        ref=data["ref"],
        parent_ref=data["parent_ref"],
        details=_details_from_list(data["details"]),
        recorded_at=_parse_dt(data["recorded_at"]) or datetime.now(),
    )


def _card_to_dict(card: ApprovalCard) -> dict[str, Any]:
    return {
        "work_item_id": card.work_item_id,
        "candidate_summary": card.candidate_summary,
        "final_version_ref": card.final_version_ref,
        "final_version_refs": list(card.final_version_refs),
        "creative_set_id": card.creative_set_id,
        "thumbnail_ref": card.thumbnail_ref,
        "warnings": list(card.warnings),
        "score": str(card.score) if card.score is not None else None,
        "evidence_refs": list(card.evidence_refs),
        "decision": card.decision.value if card.decision is not None else None,
        "reviewer_id": card.reviewer_id,
        "decided_at": _iso(card.decided_at),
        "reason": card.reason,
    }


def _card_from_dict(data: dict[str, Any]) -> ApprovalCard:
    return ApprovalCard(
        work_item_id=data["work_item_id"],
        candidate_summary=data["candidate_summary"],
        final_version_ref=data["final_version_ref"],
        final_version_refs=tuple(data.get("final_version_refs", ())),
        creative_set_id=data.get("creative_set_id"),
        thumbnail_ref=data["thumbnail_ref"],
        warnings=tuple(data["warnings"]),
        score=Decimal(data["score"]) if data["score"] is not None else None,
        evidence_refs=tuple(data["evidence_refs"]),
        decision=ApprovalDecision(data["decision"]) if data["decision"] else None,
        reviewer_id=data["reviewer_id"],
        decided_at=_parse_dt(data["decided_at"]),
        reason=data["reason"],
    )


def _job_to_dict(job: CreativeJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id.value,
        "source_run_id": job.source_run_id,
        "status": job.status.value,
        "context_ref": job.context_ref,
        "idea_id": job.idea_id,
        "brief_ref": job.brief_ref,
        "preparation_hash": job.preparation_hash,
        "creative_set_id": job.creative_set_id,
        "total_cost": _cost_to_dict(job.total_cost),
        "audit_log": [_audit_to_dict(e) for e in job.audit_log],
        "lineage": [_lineage_to_dict(e) for e in job.lineage],
        "card": _card_to_dict(job.card) if job.card is not None else None,
        "approval_decision": (
            job.approval_decision.value if job.approval_decision is not None else None
        ),
        "approved_by": job.approved_by,
        "approved_at": _iso(job.approved_at),
        "rejection_reason": job.rejection_reason,
    }


def _job_from_dict(data: dict[str, Any]) -> CreativeJob:
    return CreativeJob(
        job_id=CreativeJobId.from_string(data["job_id"]),
        status=CreativeJobStatus(data["status"]),
        source_run_id=data["source_run_id"],
        context_ref=data["context_ref"],
        idea_id=data["idea_id"],
        brief_ref=data.get("brief_ref"),
        preparation_hash=data.get("preparation_hash"),
        creative_set_id=data.get("creative_set_id"),
        total_cost=_cost_from_dict(data["total_cost"]),
        audit_log=[_audit_from_dict(e) for e in data["audit_log"]],
        lineage=[_lineage_from_dict(e) for e in data["lineage"]],
        card=_card_from_dict(data["card"]) if data["card"] is not None else None,
        approval_decision=(
            ApprovalDecision(data["approval_decision"]) if data["approval_decision"] else None
        ),
        approved_by=data["approved_by"],
        approved_at=_parse_dt(data["approved_at"]),
        rejection_reason=data["rejection_reason"],
    )


class SqliteCreativeRepository:
    """Persistent ICreativeRepository backed by a single SQLite file."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    async def save_job(self, job: CreativeJob) -> None:
        payload = json.dumps(_job_to_dict(job), ensure_ascii=False)
        self._conn.execute(
            "INSERT OR REPLACE INTO jobs (job_id, source_run_id, status, payload) "
            "VALUES (?, ?, ?, ?)",
            (job.job_id.value, job.source_run_id, job.status.value, payload),
        )
        self._conn.commit()

    async def get_job(self, job_id: CreativeJobId) -> CreativeJob | None:
        row = self._conn.execute(
            "SELECT payload FROM jobs WHERE job_id = ?",
            (job_id.value,),
        ).fetchone()
        if row is None:
            return None
        job = _job_from_dict(json.loads(row["payload"]))
        for version in await self.get_versions_for_job(job_id):
            job.versions.append(version)
        return job

    async def get_job_by_source_run_id(self, source_run_id: str) -> CreativeJob | None:
        row = self._conn.execute(
            "SELECT payload FROM jobs WHERE source_run_id = ?",
            (source_run_id,),
        ).fetchone()
        if row is None:
            return None
        job = _job_from_dict(json.loads(row["payload"]))
        for version in await self.get_versions_for_job(job.job_id):
            job.versions.append(version)
        return job

    async def list_jobs(self) -> list[CreativeJob]:
        rows = self._conn.execute("SELECT payload FROM jobs ORDER BY rowid").fetchall()
        version_rows = self._conn.execute(
            "SELECT job_id, payload FROM versions ORDER BY job_id, attempt_number"
        ).fetchall()
        versions_by_job: dict[str, list[AssetVersion]] = {}
        for row in version_rows:
            versions_by_job.setdefault(row["job_id"], []).append(
                _version_from_dict(json.loads(row["payload"]))
            )

        jobs = [_job_from_dict(json.loads(row["payload"])) for row in rows]
        for job in jobs:
            job.versions.extend(versions_by_job.get(job.job_id.value, ()))
        return jobs

    async def save_version(self, version: AssetVersion) -> None:
        payload = json.dumps(_version_to_dict(version), ensure_ascii=False)
        self._conn.execute(
            "INSERT OR REPLACE INTO versions "
            "(version_id, job_id, attempt_number, payload) VALUES (?, ?, ?, ?)",
            (
                version.version_id.value,
                version.version_id.job_id.value,
                version.attempt_number,
                payload,
            ),
        )
        self._conn.commit()

    async def get_version(self, version_id: VersionId) -> AssetVersion | None:
        row = self._conn.execute(
            "SELECT payload FROM versions WHERE version_id = ?",
            (version_id.value,),
        ).fetchone()
        if row is None:
            return None
        return _version_from_dict(json.loads(row["payload"]))

    async def get_versions_for_job(self, job_id: CreativeJobId) -> list[AssetVersion]:
        rows = self._conn.execute(
            "SELECT payload FROM versions WHERE job_id = ? ORDER BY attempt_number",
            (job_id.value,),
        ).fetchall()
        return [_version_from_dict(json.loads(row["payload"])) for row in rows]


__all__ = ["SqliteCreativeRepository"]
