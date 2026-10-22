"""Resolve a curated local source pack; never fetch source or asset URLs."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from ..ports.contracts import ContextPackage, CreativeWorkItemInput, EvidenceRef, SkuInput
from ..ports.preparation import (
    ApprovedClaim,
    ApprovedReference,
    PersonaOption,
    PreparationContext,
    PreparationError,
    SourceDocument,
)


class _LocalContextPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand: str = Field(min_length=1)
    sku_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    sources: tuple[SourceDocument, ...] = Field(min_length=1)
    personas: tuple[PersonaOption, ...] = Field(min_length=1)
    references: tuple[ApprovedReference, ...] = ()
    approved_claims: tuple[ApprovedClaim, ...] = ()

    @model_validator(mode="after")
    def check_registry(self) -> Self:
        for records, key in (
            (self.sources, "source_id"),
            (self.personas, "persona_id"),
            (self.references, "reference_id"),
            (self.approved_claims, "claim_id"),
        ):
            identifiers = [getattr(record, key) for record in records]
            if any(not value.strip() for value in identifiers) or len(set(identifiers)) != len(
                identifiers
            ):
                raise ValueError("Source pack IDs must be nonempty and unique within each registry")
        if any(
            not source.data_version.strip() or not source.content.strip() for source in self.sources
        ):
            raise ValueError("Every source must have a version and readable content")
        if any(
            not persona.name.strip() or not persona.description.strip() for persona in self.personas
        ):
            raise ValueError("Every persona must have a name and readable description")
        source_ids = {f"work-item:{self.sku_id}", *(source.source_id for source in self.sources)}
        for record in (*self.personas, *self.references, *self.approved_claims):
            if not record.evidence_refs or not set(record.evidence_refs).issubset(source_ids):
                raise ValueError("Source pack entries must cite existing sources")
        if any(not claim.proof.verified for claim in self.approved_claims):
            raise ValueError("Approved claims require verified source proofs")
        if any(
            reference.asset.expires_at is not None
            and reference.asset.expires_at.utcoffset() is None
            for reference in self.references
        ):
            raise ValueError("Reference expiration must include a timezone")
        for url in (
            *(reference.asset.url for reference in self.references),
            *(claim.proof.source_url for claim in self.approved_claims if claim.proof.source_url),
        ):
            if "://" not in url:
                continue
            parsed = urlsplit(url)
            if parsed.username or parsed.password or parsed.query:
                raise ValueError("Source pack URLs must not contain credentials or query tokens")
        return self


def load_preparation_context(
    path: Path, work_item: CreativeWorkItemInput, *, max_bytes: int | None = 131072
) -> PreparationContext:
    if len(work_item.target_sku_set) != 1:
        raise PreparationError("M1 preparation requires exactly one SKU", "invalid_scope")
    try:
        with path.open("rb") as source:
            payload = source.read() if max_bytes is None else source.read(max_bytes + 1)
        if max_bytes is not None and len(payload) > max_bytes:
            raise PreparationError(
                "Local context pack exceeds the configured byte limit", "context_too_large"
            )
        pack = _LocalContextPack.model_validate_json(payload)
    except OSError as exc:
        raise PreparationError("Cannot read local context pack", "context_unavailable") from exc
    except (ValidationError, ValueError) as exc:
        raise PreparationError("Invalid local context pack", "context_invalid") from exc
    sku = work_item.target_sku_set[0]
    if pack.brand != work_item.marketing_scope.brand or pack.sku_id != sku.sku_id:
        raise PreparationError(
            "Context pack does not match work item brand and SKU", "scope_mismatch"
        )
    if sku.creative_constraints.brand_guideline_ref and not any(
        source.category == "brand" for source in pack.sources
    ):
        raise PreparationError(
            "Brand guideline content is missing from context", "missing_brand_context"
        )
    product_source_id = f"work-item:{sku.sku_id}"
    if any(source.source_id == product_source_id for source in pack.sources):
        raise PreparationError("Context pack uses a reserved source ID", "context_invalid")
    pack_payload = json.dumps(pack.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    pack_hash = hashlib.sha256(pack_payload.encode("utf-8")).hexdigest()
    product_content = TypeAdapter(SkuInput).dump_json(sku).decode("utf-8")
    product_source = SourceDocument(
        source_id=product_source_id,
        data_version=hashlib.sha256(product_content.encode("utf-8")).hexdigest(),
        content=product_content,
        category="product",
    )
    sources = (product_source, *pack.sources)
    references = tuple(
        replace(
            reference,
            asset=replace(
                reference.asset,
                url=(
                    reference.asset.url
                    if "://" in reference.asset.url
                    else str((path.resolve().parent / reference.asset.url).resolve())
                ),
            ),
        )
        for reference in pack.references
    )
    warnings = []
    if (
        not sku.historical_creative_context.tested_angles
        and not sku.historical_creative_context.performance_notes
    ):
        warnings.append("creative_history_unavailable")
    if references:
        warnings.append("reference_images_not_inspected")
    return PreparationContext(
        package=ContextPackage(
            context_id=f"{work_item.source_run_id}:{sku.sku_id}:{pack_hash[:12]}",
            source_run_id=work_item.source_run_id,
            sku_id=sku.sku_id,
            brand=work_item.marketing_scope.brand,
            evidence=tuple(
                EvidenceRef(source_id=source.source_id, data_version=source.data_version)
                for source in sources
            ),
            historical=sku.historical_creative_context,
            brand_guideline_ref=sku.creative_constraints.brand_guideline_ref,
        ),
        sku=sku,
        sources=sources,
        personas=pack.personas,
        references=references,
        approved_claims=pack.approved_claims,
        warnings=tuple(warnings),
        pack_version=pack.version,
        pack_hash=pack_hash,
    )
