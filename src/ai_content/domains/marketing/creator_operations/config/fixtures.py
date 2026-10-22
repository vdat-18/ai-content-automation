"""Strict synthetic fixture loader for Creator Operations."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..application.evaluation import CreatorRunRequest
from ..domain.models import (
    CampaignRequirement,
    CreatorProfile,
    EvidenceFact,
    EvidencePackage,
    FieldStatus,
)


class CampaignFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: str
    brand_id: str
    store_id: str
    sku_id: str
    market: str
    target_creators: int = Field(ge=1)
    brief: str
    version: str


class CreatorFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    creator_id: str
    source_platform: str
    source_creator_id: str
    display_alias: str


class EvidenceFactFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_name: str
    status: FieldStatus
    value: str | None = None
    source_ref: str | None = None
    observed_at: datetime
    supports_criterion: bool | None = None


class EvidencePackageFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_id: str
    stage: str
    facts: list[EvidenceFactFixture] = Field(min_length=1)


class CreatorEvaluationFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_run_id: str
    candidate_id: str
    policy_version: str
    campaign: CampaignFixture
    creator: CreatorFixture
    location_reference_store_id: str
    location_reference_version: str
    evidence_packages: list[EvidencePackageFixture] = Field(min_length=1)
    mapping_version: str
    target_base_ref: str
    field_mapping: dict[str, str]
    existing_record: dict[str, str] = Field(default_factory=dict)
    source_checksum_sha256: str = Field(default="", exclude=True)

    @model_validator(mode="after")
    def validate_package_order(self) -> CreatorEvaluationFixture:
        package_ids = [item.package_id for item in self.evidence_packages]
        if len(package_ids) != len(set(package_ids)):
            raise ValueError("Evidence package IDs must be unique")
        if len(set(self.field_mapping.values())) != len(self.field_mapping):
            raise ValueError("Lark target fields must be mapped once")
        return self

    def request(self) -> CreatorRunRequest:
        campaign = CampaignRequirement(**self.campaign.model_dump())
        creator = CreatorProfile(**self.creator.model_dump())
        packages = tuple(
            EvidencePackage(
                package_id=package.package_id,
                stage=package.stage,
                facts=tuple(EvidenceFact(**fact.model_dump()) for fact in package.facts),
            )
            for package in self.evidence_packages
        )
        return CreatorRunRequest(
            source_run_id=self.source_run_id,
            source_checksum_sha256=self.source_checksum_sha256,
            campaign=campaign,
            creator=creator,
            candidate_id=self.candidate_id,
            policy_version=self.policy_version,
            location_reference_store_id=self.location_reference_store_id,
            location_reference_version=self.location_reference_version,
            evidence_packages=packages,
            mapping_version=self.mapping_version,
            target_base_ref=self.target_base_ref,
            field_mapping=tuple(self.field_mapping.items()),
            existing_record=tuple(self.existing_record.items()),
        )


def load_creator_fixture(path: Path) -> CreatorEvaluationFixture:
    content = path.read_bytes()
    fixture = CreatorEvaluationFixture.model_validate_json(content)
    return fixture.model_copy(
        update={"source_checksum_sha256": hashlib.sha256(content).hexdigest()}
    )


__all__ = ["CreatorEvaluationFixture", "load_creator_fixture"]
