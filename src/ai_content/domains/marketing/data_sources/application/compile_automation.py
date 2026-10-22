"""Compile Lead Marketing SKU selections into the existing Creative intake path."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace

from ai_content.domains.marketing.creative.application.model_context import (
    product_family_for_model,
)
from ai_content.domains.marketing.creative.application.routing import decide_production_route
from ai_content.domains.marketing.creative.ports.contracts import (
    AssetReference,
    ContextPackage,
    CreativeConstraints,
    CreativeReferenceSelectionMode,
    CreativeWorkItemInput,
    CustomerContext,
    EvidenceRef,
    HistoricalCreativeContext,
    MarketingCreativeAutomationRequest,
    MarketingScope,
    OutputSpec,
    PolicyVersion,
    ProductMetadata,
    PromptVersion,
    ProofReference,
    ProofType,
    ProvenanceSource,
    RubricVersion,
    RuleVersion,
    SkuInput,
    WorkflowVersionRef,
)
from ai_content.domains.marketing.creative.ports.media_production import (
    IFrozenProductMediaResolver,
    ProductMediaSourceRef,
)
from ai_content.domains.marketing.creative.ports.preparation import (
    ApprovedClaim,
    ApprovedReference,
    BrandProfile,
    CreativeStrategySelection,
    IPersonaResolver,
    PersonaOption,
    PersonaResolution,
    PreparationContext,
    PreparationError,
    SourceDocument,
)
from ai_content.domains.marketing.creative.ports.preparation_store import (
    ProductionReadyCreativePackage,
)
from ai_content.domains.marketing.creative_intake.application.contracts import (
    CreativeIntakeCase,
    CreativeIntakeFixture,
    intake_fingerprint,
)
from ai_content.domains.marketing.creative_intake.application.resolution import (
    CreativeIntakeRequest,
)
from ai_content.domains.marketing.creative_intake.domain.models import (
    ComponentStatus,
    ContextComponent,
    ContextEvidence,
    CreativeContextSnapshot,
    CreativeTaskTrigger,
    TriggerSource,
)

from ..domain.models import NormalizedRecord, SourceSnapshot
from .compile_context import (
    CreativeContextUnavailableError,
    CreativeSourceContextCompiler,
    record_matches_brand,
)


@dataclass(frozen=True)
class MarketingAutomationCompilation:
    package: ProductionReadyCreativePackage
    intake: CreativeIntakeFixture


def register_context_sources(
    compilation: MarketingAutomationCompilation,
    sources: tuple[SourceDocument, ...],
) -> MarketingAutomationCompilation:
    """Register model-visible sources in every immutable evidence view."""

    if not sources:
        return compilation
    case = compilation.intake.cases[0]
    context = case.context_template
    snapshot = case.request.context
    trigger = case.request.trigger
    existing_sources = {item.source_id: item for item in context.sources}
    evidence_by_id = {item.source_id: item for item in context.package.evidence}
    source_additions: list[SourceDocument] = []
    registrations: list[SourceDocument] = []
    for source in sources:
        existing = existing_sources.get(source.source_id)
        if existing is not None and existing != source:
            raise PreparationError(
                "A context source ID was reused with different content",
                "context_source_version_conflict",
            )
        evidence = evidence_by_id.get(source.source_id)
        if evidence is not None and evidence.data_version != source.data_version:
            raise PreparationError(
                "A context source does not match its registered evidence version",
                "context_source_version_conflict",
            )
        if existing is None:
            source_additions.append(source)
            existing_sources[source.source_id] = source
        resolved_ref = f"{source.source_id}:{source.data_version}"
        if (
            evidence is None
            or source.source_id not in snapshot.evidence_refs
            or source.source_id not in trigger.evidence_refs
            or resolved_ref not in snapshot.resolved_context_refs
        ):
            registrations.append(source)

    if not source_additions and not registrations:
        return compilation
    changed_sources = tuple(dict.fromkeys((*source_additions, *registrations)))
    registered_evidence = tuple(
        EvidenceRef(
            source_id=item.source_id,
            data_version=item.data_version,
            retrieved_at=compilation.package.request.requested_at,
        )
        for item in registrations
        if item.source_id not in evidence_by_id
    )
    prepared_context = replace(
        context,
        sources=(*context.sources, *source_additions),
        package=replace(
            context.package,
            evidence=(*context.package.evidence, *registered_evidence),
        ),
        pack_hash=hashlib.sha256(
            (
                context.pack_hash
                + ":"
                + ":".join(f"{item.source_id}@{item.data_version}" for item in changed_sources)
            ).encode()
        ).hexdigest(),
    )
    source_ids = tuple(item.source_id for item in registrations)
    resolved_refs = tuple(f"{item.source_id}:{item.data_version}" for item in registrations)
    snapshot = replace(
        snapshot,
        evidence_refs=tuple(dict.fromkeys((*snapshot.evidence_refs, *source_ids))),
        resolved_context_refs=tuple(
            dict.fromkeys((*snapshot.resolved_context_refs, *resolved_refs))
        ),
    )
    trigger = replace(
        trigger,
        evidence_refs=tuple(dict.fromkeys((*trigger.evidence_refs, *source_ids))),
    )
    request = CreativeIntakeRequest(
        trigger=trigger,
        context=snapshot,
        source_checksum_sha256=intake_fingerprint(
            trigger,
            snapshot,
            case.work_item_template,
            prepared_context,
        ),
    )
    return replace(
        compilation,
        package=replace(compilation.package, context=prepared_context.package),
        intake=CreativeIntakeFixture(
            (CreativeIntakeCase(request, case.work_item_template, prepared_context),)
        ),
    )


def _normalized_evidence_refs(evidence_refs: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in evidence_refs if item.strip()))


async def resolve_missing_persona(
    compilation: MarketingAutomationCompilation,
    resolver: IPersonaResolver,
    *,
    pinned: PersonaResolution | None = None,
) -> MarketingAutomationCompilation:
    """Resolve and pin one evidence-linked Creative hypothesis when Persona is absent."""

    case = compilation.intake.cases[0]
    context = case.context_template
    if context.personas and pinned is None:
        return compilation
    if pinned is None:
        result = await resolver.resolve_persona(context, case.work_item_template)
        hypothesis = result.output
        evidence_refs = _normalized_evidence_refs(hypothesis.evidence_refs)
        known_refs = {item.source_id for item in context.sources}.intersection(
            case.request.context.evidence_refs
        )
        if not evidence_refs or not set(evidence_refs).issubset(known_refs):
            raise PreparationError(
                "Persona resolution cited unavailable or empty evidence",
                "persona_resolution_invalid_evidence",
                trace=result.trace,
            )
        digest = _persona_resolution_checksum(
            compilation.package.request.request_id,
            hypothesis.name,
            hypothesis.description,
            hypothesis.rationale,
            evidence_refs,
            hypothesis.uncertainties,
        )
        persona = PersonaOption(
            persona_id=f"persona-hypothesis:{digest[:20]}",
            name=hypothesis.name,
            description=hypothesis.description,
            evidence_refs=evidence_refs,
        )
        resolution = PersonaResolution(
            persona=persona,
            rationale=hypothesis.rationale,
            uncertainties=hypothesis.uncertainties,
            trace=result.trace,
        )
    else:
        resolution = pinned
        evidence_refs = _normalized_evidence_refs(resolution.persona.evidence_refs)
        persona = replace(resolution.persona, evidence_refs=evidence_refs)
        resolution = replace(resolution, persona=persona)
        digest = _persona_resolution_checksum(
            compilation.package.request.request_id,
            persona.name,
            persona.description,
            resolution.rationale,
            persona.evidence_refs,
            resolution.uncertainties,
        )
        known_refs = {item.source_id for item in context.sources}.intersection(
            case.request.context.evidence_refs
        )
        if not persona.evidence_refs or not set(persona.evidence_refs).issubset(known_refs):
            raise PreparationError(
                "Pinned Persona resolution no longer matches the pinned context",
                "persona_resolution_context_drift",
                trace=resolution.trace,
            )

    persona_source = SourceDocument(
        source_id=persona.persona_id,
        data_version=digest,
        content=json.dumps(
            {
                "kind": "creative_persona_hypothesis",
                "name": persona.name,
                "description": persona.description,
                "rationale": resolution.rationale,
                "uncertainties": resolution.uncertainties,
                "evidence_refs": persona.evidence_refs,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        category="persona",
    )
    evidence = EvidenceRef(
        source_id=persona_source.source_id,
        data_version=persona_source.data_version,
        retrieved_at=compilation.package.request.requested_at,
    )
    prepared_context = replace(
        context,
        package=replace(context.package, evidence=context.package.evidence + (evidence,)),
        sources=context.sources + (persona_source,),
        personas=(persona,),
        warnings=tuple(item for item in context.warnings if item != "persona_context_missing")
        + ("persona_inferred_by_agent",),
        pack_hash=hashlib.sha256(
            f"{context.pack_hash}:{persona_source.source_id}:{persona_source.data_version}".encode()
        ).hexdigest(),
    )
    snapshot = case.request.context
    components = tuple(
        replace(
            item,
            status=ComponentStatus.KNOWN,
            evidence_refs=tuple(dict.fromkeys((*persona.evidence_refs, persona_source.source_id))),
            detail=None,
        )
        if item.component == ContextComponent.PERSONA
        else item
        for item in snapshot.components
    )
    snapshot = replace(
        snapshot,
        persona_count=1,
        components=components,
        evidence_refs=tuple(dict.fromkeys((*snapshot.evidence_refs, persona_source.source_id))),
        resolved_context_refs=tuple(
            dict.fromkeys(
                (
                    *snapshot.resolved_context_refs,
                    f"{persona_source.source_id}:{persona_source.data_version}",
                )
            )
        ),
    )
    trigger = replace(
        case.request.trigger,
        evidence_refs=tuple(
            dict.fromkeys((*case.request.trigger.evidence_refs, persona_source.source_id))
        ),
    )
    request = CreativeIntakeRequest(
        trigger=trigger,
        context=snapshot,
        source_checksum_sha256=intake_fingerprint(
            trigger,
            snapshot,
            case.work_item_template,
            prepared_context,
        ),
    )
    return replace(
        compilation,
        package=replace(
            compilation.package,
            context=prepared_context.package,
            persona_resolution=resolution,
        ),
        intake=CreativeIntakeFixture(
            (CreativeIntakeCase(request, case.work_item_template, prepared_context),)
        ),
    )


def _persona_resolution_checksum(
    request_id: str,
    name: str,
    description: str,
    rationale: str,
    evidence_refs: tuple[str, ...],
    uncertainties: tuple[str, ...],
) -> str:
    return _checksum(
        {
            "request_id": request_id,
            "name": name,
            "description": description,
            "rationale": rationale,
            "evidence_refs": evidence_refs,
            "uncertainties": uncertainties,
        }
    )


class MarketingCreativeAutomationCompiler:
    """Build an immutable, single-SKU intake from synchronized source snapshots."""

    def __init__(self, context_compiler: CreativeSourceContextCompiler | None = None) -> None:
        self._context_compiler = context_compiler or CreativeSourceContextCompiler()

    def compile(
        self,
        snapshots: list[SourceSnapshot],
        request: MarketingCreativeAutomationRequest,
    ) -> MarketingAutomationCompilation:
        width, height = _dimensions(request.output.aspect_ratio)
        try:
            sku, context = self._context_compiler.compile(
                snapshots,
                brand=request.brand,
                sku_id=request.sku_id,
                market=request.market,
                width=width,
                height=height,
                product_family_ref=request.product_family,
                selection_scope=request.selection_scope,
                selected_variant_id=request.selected_variant_id,
                selected_product_media_ids=request.selected_product_media_ids,
            )
        except CreativeContextUnavailableError as error:
            return self._compile_unavailable(request, width, height, str(error))
        context = replace(context, collected_at=request.requested_at)
        human_source = _human_direction_source(request)
        if human_source is not None:
            context = replace(
                context,
                evidence=(
                    *context.evidence,
                    EvidenceRef(
                        source_id=human_source.source_id,
                        data_version=human_source.data_version,
                        retrieved_at=request.requested_at,
                    ),
                ),
            )
        routing = decide_production_route(request)
        evidence_refs = tuple(item.source_id for item in context.evidence)
        selected_strategy = _select_strategy(snapshots, request, sku, evidence_refs)
        selected_strategy = _apply_human_strategy(
            request,
            selected_strategy,
            sku,
            human_source.source_id if human_source is not None else None,
        )
        sku = _compact_sku_strategy(sku, selected_strategy)
        if request.human_offer:
            sku = replace(
                sku,
                product_metadata=replace(sku.product_metadata, offer=request.human_offer),
            )
        context = replace(context, historical=sku.historical_creative_context)
        brand_profile = _brand_profile(
            snapshots,
            request,
            sku,
            evidence_refs,
            human_source.source_id if human_source is not None else None,
        )
        personas = _personas(sku, evidence_refs, selected_strategy)
        sources = _source_documents(
            snapshots,
            evidence_refs,
            sku,
            brand_profile,
            selected_strategy,
        )
        if human_source is not None:
            sources += (human_source,)
        research_sources, research_references = _research_references(request)
        sources += research_sources
        pack_hash = _checksum(
            {
                "request": asdict(request),
                "context": asdict(context),
                "source_checksums": [item.checksum_sha256 for item in snapshots],
            }
        )
        preparation = PreparationContext(
            package=context,
            sku=sku,
            sources=sources,
            personas=personas,
            references=research_references,
            approved_claims=_human_claims(request, human_source),
            brand_profile=brand_profile,
            selected_strategy=selected_strategy,
            warnings=_context_warnings(brand_profile, selected_strategy, personas),
            pack_version="marketing-automation@3",
            pack_hash=pack_hash,
        )
        work_item = _work_item(request, sku)
        context_snapshot = _context_snapshot(
            request,
            context,
            sku,
            personas,
            evidence_refs,
            routing,
            brand_profile=brand_profile,
        )
        trigger = CreativeTaskTrigger(
            trigger_id=f"marketing-request:{request.request_id}",
            source=TriggerSource.MARKETING_REQUEST,
            source_preview_id=request.request_id,
            source_decision_ref=f"marketing-request:{request.request_id}",
            source_released=True,
            brand_id=request.brand,
            sku_id=request.sku_id,
            action="produce_overflow_creative",
            objective=request.objective,
            channel=request.platform,
            evidence_refs=evidence_refs,
            requested_at=request.requested_at,
        )
        intake_request = CreativeIntakeRequest(
            trigger=trigger,
            context=context_snapshot,
            source_checksum_sha256=intake_fingerprint(
                trigger,
                context_snapshot,
                work_item,
                preparation,
            ),
        )
        package = ProductionReadyCreativePackage(
            package_id=f"creative-package:{request.request_id}",
            request=request,
            routing=routing,
            sku=sku,
            context=context,
            work_item=work_item,
        )
        return MarketingAutomationCompilation(
            package=package,
            intake=CreativeIntakeFixture(
                (CreativeIntakeCase(intake_request, work_item, preparation),)
            ),
        )

    def _compile_unavailable(
        self,
        request: MarketingCreativeAutomationRequest,
        width: int,
        height: int,
        detail: str,
    ) -> MarketingAutomationCompilation:
        routing = decide_production_route(request)
        request_ref = f"marketing-request:{request.request_id}"
        request_checksum = _checksum(asdict(request))
        evidence = EvidenceRef(request_ref, request_checksum, request.requested_at)
        sku = SkuInput(
            sku_id=request.sku_id,
            sku_name=request.sku_id,
            product_metadata=ProductMetadata(image_refs=()),
            creative_constraints=CreativeConstraints(
                OutputSpec(width, height, "png", request.output.aspect_ratio)
            ),
            customer_context=CustomerContext(),
            historical_creative_context=HistoricalCreativeContext(),
        )
        context = ContextPackage(
            context_id=f"unavailable:{request.brand}:{request.market}:{request.sku_id}",
            source_run_id=request_ref,
            sku_id=request.sku_id,
            brand=request.brand,
            evidence=(evidence,),
            historical=sku.historical_creative_context,
            risk_flags=("synchronized_context_unavailable",),
            collected_at=request.requested_at,
        )
        source = SourceDocument(
            source_id=request_ref,
            data_version=request_checksum,
            content=json.dumps(asdict(request), sort_keys=True, default=str),
            category="reference",
        )
        preparation = PreparationContext(
            package=context,
            sku=sku,
            sources=(source,),
            personas=(),
            warnings=("synchronized_context_unavailable",),
            pack_version="marketing-automation@1",
            pack_hash=request_checksum,
        )
        work_item = _work_item(request, sku)
        context_snapshot = _unavailable_context_snapshot(
            request,
            width,
            height,
            request_ref,
            routing,
            detail,
        )
        trigger = CreativeTaskTrigger(
            trigger_id=request_ref,
            source=TriggerSource.MARKETING_REQUEST,
            source_preview_id=request.request_id,
            source_decision_ref=request_ref,
            source_released=True,
            brand_id=request.brand,
            sku_id=request.sku_id,
            action="produce_overflow_creative",
            objective=request.objective,
            channel=request.platform,
            evidence_refs=(request_ref,),
            requested_at=request.requested_at,
        )
        intake_request = CreativeIntakeRequest(
            trigger=trigger,
            context=context_snapshot,
            source_checksum_sha256=intake_fingerprint(
                trigger,
                context_snapshot,
                work_item,
                preparation,
            ),
        )
        return MarketingAutomationCompilation(
            package=ProductionReadyCreativePackage(
                package_id=f"creative-package:{request.request_id}",
                request=request,
                routing=routing,
                sku=sku,
                context=context,
                work_item=work_item,
            ),
            intake=CreativeIntakeFixture(
                (CreativeIntakeCase(intake_request, work_item, preparation),)
            ),
        )


def _dimensions(aspect_ratio: str) -> tuple[int, int]:
    return {
        "1:1": (1080, 1080),
        "4:5": (1080, 1350),
        "9:16": (1080, 1920),
        "16:9": (1920, 1080),
        "4:3": (1440, 1080),
        "3:4": (1080, 1440),
        "3:2": (1620, 1080),
        "2:3": (1080, 1620),
    }[aspect_ratio]


def _work_item(
    request: MarketingCreativeAutomationRequest,
    sku: SkuInput,
) -> CreativeWorkItemInput:
    return CreativeWorkItemInput(
        source_run_id=f"marketing-automation:{request.request_id}",
        marketing_scope=MarketingScope(request.brand, request.market),
        objective=request.objective,
        channel=request.platform,
        time_window="latest-synchronized-context",
        target_sku_set=(sku,),
        rubric_version=RubricVersion("rubric-static-creative-qa", "1.0-draft", is_draft=True),
        rule_version=RuleVersion("rule-static-creative", "1.0-draft"),
        prompt_version=PromptVersion("prompt-static-creative-generation", "1.0-draft"),
        policy_version=PolicyVersion("policy-static-creative", "1.0-draft"),
        workflow_version=WorkflowVersionRef("workflow-static-creative-generation", "1.0-draft"),
        campaign_notes=request.notes or request.brand_instructions,
        variation_count=max(
            1,
            request.output.image_output_count,
            request.output.video_output_count,
        ),
        requested_image_count=request.output.image_output_count,
        requested_video_count=request.output.video_output_count,
        created_by=request.requested_by,
        created_at=request.requested_at,
    )


def _human_claims(
    request: MarketingCreativeAutomationRequest,
    source: SourceDocument | None,
) -> tuple[ApprovedClaim, ...]:
    if source is None:
        return ()
    return tuple(
        ApprovedClaim(
            claim_id=f"human-claim:{request.request_id}:{index}",
            proof=ProofReference(ProofType.CLAIM, claim, verified=True),
            evidence_refs=(source.source_id,),
        )
        for index, claim in enumerate(request.human_claims, 1)
    )


def _human_direction_source(
    request: MarketingCreativeAutomationRequest,
) -> SourceDocument | None:
    payload = {
        "additional_requirements": request.notes,
        "brand_instructions": request.brand_instructions,
        "persona": request.human_persona,
        "angle": request.human_angle,
        "hooks": request.human_hooks,
        "offer": request.human_offer,
        "claims": request.human_claims,
    }
    if not any(payload.values()):
        return None
    return SourceDocument(
        source_id=f"human-input:{request.request_id}",
        data_version=_checksum(payload),
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        category=(
            "brand"
            if request.brand_instructions
            else "claim"
            if request.human_claims
            else "reference"
        ),
    )


def _brand_profile(
    snapshots: list[SourceSnapshot],
    request: MarketingCreativeAutomationRequest,
    sku: SkuInput,
    evidence_refs: tuple[str, ...],
    human_source_id: str | None,
) -> BrandProfile | None:
    brand = request.brand
    matched = [
        (snapshot, record)
        for snapshot in snapshots
        if snapshot.source_id in evidence_refs
        for record in snapshot.records
        if record.kind == "brand_guideline" and record_matches_brand(record, brand)
    ]
    if not matched and not request.brand_instructions:
        return None
    visual_rules: list[str] = []
    production_rules: list[str] = []
    visual_keys = {
        "color",
        "colors",
        "palette",
        "typography",
        "font",
        "fonts",
        "logo",
        "visual",
        "visual_style",
        "photography",
        "image_style",
        "tone",
    }
    production_keys = {
        "aspect_ratio",
        "cta",
        "duration",
        "format",
        "hook",
        "image_rules",
        "placement",
        "production_rules",
        "text_rules",
        "video_rules",
    }
    for _, record in matched:
        for key, value in record.data.items():
            normalized_key = _key(key)
            values = _flatten_values(value)
            if normalized_key in visual_keys:
                _extend_unique(visual_rules, values, limit=12)
            elif normalized_key in production_keys:
                _extend_unique(production_rules, values, limit=12)
        content = _first_value(record.data, ("content", "summary", "guideline"))
        if content:
            for line in (item.strip(" -•\t") for item in content.splitlines()):
                if not line or len(line) > 240:
                    continue
                category = _brand_rule_category(line)
                if category == "production":
                    _extend_unique(production_rules, (line,), limit=12)
                elif category == "visual":
                    _extend_unique(visual_rules, (line,), limit=12)
    if request.brand_instructions:
        _extend_unique(visual_rules, (request.brand_instructions.strip(),), limit=12)
    source_ids = tuple(
        dict.fromkeys(
            (
                *(snapshot.source_id for snapshot, _ in matched),
                *(
                    (human_source_id,)
                    if request.brand_instructions and human_source_id is not None
                    else ()
                ),
            )
        )
    )
    profile_key = (
        sku.creative_constraints.brand_guideline_ref or f"human-brand:{request.request_id}"
    )
    return BrandProfile(
        profile_id=profile_key,
        brand=brand,
        visual_rules=tuple(visual_rules),
        production_rules=tuple(production_rules),
        prohibited_claims=sku.creative_constraints.banned_claims,
        evidence_refs=source_ids,
    )


def _select_strategy(
    snapshots: list[SourceSnapshot],
    request: MarketingCreativeAutomationRequest,
    sku: SkuInput,
    evidence_refs: tuple[str, ...],
) -> CreativeStrategySelection | None:
    targets = {
        _key(request.sku_id),
        _key(sku.sku_id),
        _key(sku.sku_name),
        *(_key(tag) for tag in (sku.product_family.tags if sku.product_family else ())),
    }
    if request.selected_variant_id:
        targets.add(_key(request.selected_variant_id))
    if sku.product_family is not None:
        targets.update(
            {
                _key(sku.product_family.ref.product_id),
                _key(sku.product_family.handle),
                *(_key(item.sku or "") for item in sku.product_family.variants),
            }
        )
    targets.discard("")
    candidates: list[tuple[int, SourceSnapshot, NormalizedRecord]] = []
    scope_aliases = (
        "sku",
        "variant_sku",
        "product_id",
        "product",
        "product_name",
        "product_family",
        "collection",
    )
    for snapshot in snapshots:
        if snapshot.source_id not in evidence_refs:
            continue
        for record in snapshot.records:
            if record.kind != "creative_strategy" or not record_matches_brand(
                record, request.brand
            ):
                continue
            scoped_values = {_key(value) for value in _field_values(record.data, scope_aliases)}
            scoped_values.discard("")
            if scoped_values and not scoped_values.intersection(targets):
                continue
            exact_score = 100 if scoped_values else 0
            completeness = sum(
                bool(_first_value(record.data, aliases))
                for aliases in (
                    ("persona", "persona_name", "persona_code", "customer"),
                    ("angle", "marketing_angle"),
                    ("hook", "hook_1", "suggested_first_3s_hook"),
                    ("pain_point", "desire", "promise", "benefit"),
                )
            )
            candidates.append((exact_score + completeness, snapshot, record))
    if not candidates:
        return None
    scoped_candidates = [item for item in candidates if item[0] >= 100]
    if scoped_candidates:
        candidates = scoped_candidates
    elif len(candidates) != 1:
        return None
    _, snapshot, record = max(candidates, key=lambda item: item[0])
    data = record.data
    persona_name = _first_value(
        data,
        ("persona", "persona_name", "persona_code", "customer", "sub_avatar"),
    )
    persona_signals = _field_values(
        data,
        ("snapshot", "pain_point", "desire", "barrier", "lf8"),
    )
    if not persona_name and persona_signals:
        persona_name = "Evidence-backed customer"
    angle = _first_value(data, ("angle", "marketing_angle")) or next(
        iter(sku.historical_creative_context.tested_angles), ""
    )
    if not persona_name or not angle:
        return None
    hooks = _field_values(
        data,
        (
            "hook",
            "hook_1",
            "hook_2",
            "hook_3",
            "suggested_first_3s_hook",
            "suggested_hook",
        ),
    )[:3]
    digest = _checksum(
        {
            "source_id": snapshot.source_id,
            "provider_id": record.provider_id,
            "data": data,
        }
    )[:16]
    persona_code = _first_value(data, ("persona_code", "persona_id"))
    return CreativeStrategySelection(
        strategy_id=f"strategy:{digest}",
        persona_id=f"persona:{_safe_identifier(persona_code or digest)}",
        persona_name=persona_name,
        angle=angle,
        hooks=hooks,
        persona_context=persona_signals,
        awareness_stage=_first_value(data, ("awareness", "awareness_stage")) or None,
        offer=sku.product_metadata.offer,
        evidence_refs=(snapshot.source_id,),
    )


def _apply_human_strategy(
    request: MarketingCreativeAutomationRequest,
    strategy: CreativeStrategySelection | None,
    sku: SkuInput,
    source_id: str | None,
) -> CreativeStrategySelection | None:
    if source_id is None:
        return strategy
    persona_name = request.human_persona or (strategy.persona_name if strategy else "")
    angle = request.human_angle or (
        strategy.angle
        if strategy
        else next(iter(sku.historical_creative_context.tested_angles), "")
    )
    if not persona_name or not angle:
        return strategy
    return CreativeStrategySelection(
        strategy_id=f"human-strategy:{request.request_id}",
        persona_id=f"human-persona:{request.request_id}",
        persona_name=persona_name,
        angle=angle,
        hooks=request.human_hooks or (strategy.hooks if strategy else ()),
        evidence_refs=(source_id,),
        persona_context=strategy.persona_context if strategy else (),
        awareness_stage=strategy.awareness_stage if strategy else None,
        offer=request.human_offer or sku.product_metadata.offer,
        claims=request.human_claims,
    )


def _strategy_persona_description(
    strategy: CreativeStrategySelection,
    sku: SkuInput,
) -> str:
    details = strategy.persona_context or (
        *sku.customer_context.pain_points,
        *sku.customer_context.promises,
    )
    suffix = f"; {'; '.join(details)}" if details else ""
    return f"Angle: {strategy.angle}{suffix}"


def _compact_sku_strategy(
    sku: SkuInput,
    strategy: CreativeStrategySelection | None,
) -> SkuInput:
    if strategy is None:
        return sku
    return replace(
        sku,
        product_metadata=replace(
            sku.product_metadata,
            differentiators=(),
        ),
        customer_context=CustomerContext(pain_points=strategy.persona_context),
        historical_creative_context=HistoricalCreativeContext(
            tested_angles=(strategy.angle,),
        ),
    )


def _context_warnings(
    brand_profile: BrandProfile | None,
    selected_strategy: CreativeStrategySelection | None,
    personas: tuple[PersonaOption, ...],
) -> tuple[str, ...]:
    warnings: list[str] = []
    if brand_profile is None:
        warnings.append("brand_profile_missing")
    if not personas:
        warnings.append("persona_context_missing")
    if selected_strategy is None:
        warnings.append("strategy_context_missing")
    elif not selected_strategy.hooks:
        warnings.append("hook_context_missing")
    return tuple(warnings)


def _first_value(data: dict[str, object], aliases: tuple[str, ...]) -> str:
    values = _field_values(data, aliases)
    return values[0] if values else ""


def _field_values(data: dict[str, object], aliases: tuple[str, ...]) -> tuple[str, ...]:
    by_key = {_key(key): value for key, value in data.items()}
    values: list[str] = []
    for alias in aliases:
        normalized_alias = _key(alias)
        if normalized_alias in by_key:
            _extend_unique(values, _flatten_values(by_key[normalized_alias]), limit=20)
    return tuple(values)


def _flatten_values(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return tuple(f"{key}: {item}" for key, item in value.items() if str(item).strip())
    text = str(value).strip()
    return (text,) if text else ()


def _extend_unique(target: list[str], values: tuple[str, ...], *, limit: int) -> None:
    known = {item.casefold() for item in target}
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned.casefold() not in known and len(target) < limit:
            target.append(cleaned)
            known.add(cleaned.casefold())


def _key(value: object) -> str:
    normalized = "".join(
        character if character.isalnum() else " " for character in str(value).casefold()
    )
    return "_".join(normalized.split())


def _safe_identifier(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "._:-" else "-" for character in value
    )
    return cleaned[:120] or "unknown"


def _brand_rule_category(value: str) -> str | None:
    normalized = value.casefold()
    if any(
        keyword in normalized
        for keyword in ("second", "duration", "ratio", "format", "cta", "hook", "placement")
    ):
        return "production"
    if any(
        keyword in normalized
        for keyword in (
            "color",
            "font",
            "image",
            "layout",
            "logo",
            "minimal",
            "palette",
            "photo",
            "style",
            "typography",
            "visual",
        )
    ):
        return "visual"
    return None


def _personas(
    sku,
    evidence_refs: tuple[str, ...],
    selected_strategy: CreativeStrategySelection | None,
) -> tuple[PersonaOption, ...]:
    if selected_strategy is not None:
        return (
            PersonaOption(
                persona_id=selected_strategy.persona_id,
                name=selected_strategy.persona_name,
                description=_strategy_persona_description(selected_strategy, sku),
                evidence_refs=selected_strategy.evidence_refs,
            ),
        )
    customer = sku.customer_context
    details = (*customer.pain_points, *customer.promises)
    if not details:
        return ()
    return (
        PersonaOption(
            persona_id=f"persona:{sku.sku_id}",
            name="Evidence-backed customer",
            description="; ".join(details),
            evidence_refs=evidence_refs,
        ),
    )


def _source_documents(
    snapshots: list[SourceSnapshot],
    evidence_refs: tuple[str, ...],
    sku: SkuInput,
    brand_profile: BrandProfile | None,
    selected_strategy: CreativeStrategySelection | None,
) -> tuple[SourceDocument, ...]:
    relevant = [snapshot for snapshot in snapshots if snapshot.source_id in evidence_refs]
    product_ref = sku.product_family.ref if sku.product_family is not None else None
    documents = []
    for snapshot in relevant:
        product_records = [
            record
            for record in snapshot.records
            if record.kind == "product"
            and product_ref is not None
            and snapshot.source_id == product_ref.source_id
            and str(record.data.get("product_id") or record.provider_id) == product_ref.product_id
        ]
        payload: dict[str, object] = {}
        if product_records and sku.product_family is not None:
            payload["product_truth"] = product_family_for_model(sku.product_family)
        if brand_profile is not None and snapshot.source_id in brand_profile.evidence_refs:
            payload["brand_profile"] = asdict(brand_profile)
        if selected_strategy is not None and snapshot.source_id in selected_strategy.evidence_refs:
            payload["selected_strategy"] = asdict(selected_strategy)
        if not payload:
            continue
        documents.append(
            SourceDocument(
                source_id=snapshot.source_id,
                data_version=snapshot.checksum_sha256,
                content=json.dumps(
                    payload,
                    sort_keys=True,
                    default=str,
                    separators=(",", ":"),
                ),
                category=(
                    "product"
                    if product_records
                    else "brand"
                    if "brand_profile" in payload
                    else "persona"
                ),
            )
        )
    return tuple(documents)


def _research_references(
    request: MarketingCreativeAutomationRequest,
) -> tuple[tuple[SourceDocument, ...], tuple[ApprovedReference, ...]]:
    if request.reference_selection_mode == CreativeReferenceSelectionMode.AGENT:
        return (), ()
    sources: list[SourceDocument] = []
    references: list[ApprovedReference] = []
    for candidate in request.reference_candidates:
        label_text = ", ".join(f"{key}={value}" for key, value in candidate.labels)
        content = candidate.description
        if label_text:
            content = f"{content}\nTaxonomy: {label_text}"
        sources.append(
            SourceDocument(
                source_id=candidate.reference_id,
                data_version=candidate.checksum_sha256,
                content=content,
                category="reference",
            )
        )
        references.append(
            ApprovedReference(
                reference_id=candidate.reference_id,
                asset=AssetReference(
                    url=candidate.artifact_ref,
                    provenance=ProvenanceSource.TEAM_PROVIDED,
                    license_info="Public ad research reference; inspiration only",
                ),
                description=(
                    f"Competitor creative reference from {candidate.platform}. "
                    "Use layout, styling, framing, and visual pattern only; never copy "
                    f"the product, logo, brand, or claims. {content} "
                    f"Source: {candidate.source_url or 'captured public page'}"
                ),
                evidence_refs=(candidate.reference_id,),
            )
        )
    return tuple(sources), tuple(references)


def _context_snapshot(
    request,
    context,
    sku,
    personas,
    evidence_refs,
    routing,
    *,
    brand_profile: BrandProfile | None,
):
    now = request.requested_at
    known = ComponentStatus.KNOWN
    unknown = ComponentStatus.UNKNOWN
    brand_known = brand_profile is not None
    component_specs = (
        (ContextComponent.BRAND, known if brand_known else unknown, "Brand guideline is missing."),
        (ContextComponent.PRODUCT, known, None),
        (ContextComponent.PERSONA, known if personas else unknown, "Persona context is missing."),
        (ContextComponent.POLICY, known if brand_known else unknown, "Brand policy is missing."),
        (ContextComponent.OUTPUT, known, None),
        (ContextComponent.VERSIONS, known, None),
        (
            ContextComponent.HISTORY,
            known if sku.historical_creative_context.tested_angles else unknown,
            "Creative history is not available.",
        ),
    )
    components = tuple(
        ContextEvidence(
            component=component,
            status=status,
            evidence_refs=evidence_refs if status == known else (),
            observed_at=now,
            detail=detail if status == unknown else None,
        )
        for component, status, detail in component_specs
    )
    versions = (
        "prompt-static-creative-generation@1.0-draft",
        "rubric-static-creative-qa@1.0-draft",
        "policy-static-creative@1.0-draft",
        "rule-static-creative@1.0-draft",
        "workflow-static-creative-generation@1.0-draft",
    )
    return CreativeContextSnapshot(
        snapshot_id=f"marketing-context:{request.request_id}",
        version="marketing-automation-context@1",
        brand_id=request.brand,
        sku_id=request.sku_id,
        market=request.market,
        objective=request.objective,
        channel=request.platform,
        product_image_count=len(sku.product_metadata.image_refs),
        persona_count=len(personas),
        output_width=sku.creative_constraints.format_spec.width,
        output_height=sku.creative_constraints.format_spec.height,
        version_refs=versions,
        resolved_context_refs=tuple(
            f"{item.source_id}:{item.data_version}" for item in context.evidence
        ),
        components=components,
        evidence_refs=evidence_refs,
        captured_at=now,
        requested_image_count=request.output.image_output_count,
        requested_video_count=request.output.video_output_count,
        requested_video_duration_seconds=request.output.video_duration_seconds,
        requested_video_duration_min_seconds=request.output.video_duration_min_seconds,
        requested_video_duration_max_seconds=request.output.video_duration_max_seconds,
        requested_video_scene_duration_max_seconds=request.output.video_scene_duration_max_seconds,
        include_background_music=request.output.include_background_music,
        execution_mode=request.execution_mode.value,
        production_route=routing.route.value,
        routing_reasons=routing.reasons,
        routing_requires_override=routing.requires_override,
    )


def _unavailable_context_snapshot(
    request,
    width: int,
    height: int,
    request_ref: str,
    routing,
    detail: str,
) -> CreativeContextSnapshot:
    now = request.requested_at
    unknown_details = {
        ContextComponent.BRAND: "Brand context is unavailable.",
        ContextComponent.PRODUCT: detail,
        ContextComponent.PERSONA: "Persona context is unavailable.",
        ContextComponent.POLICY: "Brand policy is unavailable.",
        ContextComponent.HISTORY: "Creative history is unavailable.",
    }
    components = tuple(
        ContextEvidence(
            component=component,
            status=ComponentStatus.UNKNOWN,
            evidence_refs=(),
            observed_at=now,
            detail=component_detail,
        )
        for component, component_detail in unknown_details.items()
    ) + (
        ContextEvidence(
            component=ContextComponent.OUTPUT,
            status=ComponentStatus.KNOWN,
            evidence_refs=(request_ref,),
            observed_at=now,
        ),
        ContextEvidence(
            component=ContextComponent.VERSIONS,
            status=ComponentStatus.KNOWN,
            evidence_refs=(request_ref,),
            observed_at=now,
        ),
    )
    versions = (
        "prompt-static-creative-generation@1.0-draft",
        "rubric-static-creative-qa@1.0-draft",
        "policy-static-creative@1.0-draft",
        "rule-static-creative@1.0-draft",
        "workflow-static-creative-generation@1.0-draft",
    )
    return CreativeContextSnapshot(
        snapshot_id=f"marketing-context:{request.request_id}",
        version="marketing-automation-context@1",
        brand_id=request.brand,
        sku_id=request.sku_id,
        market=request.market,
        objective=request.objective,
        channel=request.platform,
        product_image_count=0,
        persona_count=0,
        output_width=width,
        output_height=height,
        version_refs=versions,
        resolved_context_refs=(),
        components=components,
        evidence_refs=(request_ref,),
        captured_at=now,
        requested_image_count=request.output.image_output_count,
        requested_video_count=request.output.video_output_count,
        requested_video_duration_seconds=request.output.video_duration_seconds,
        requested_video_duration_min_seconds=request.output.video_duration_min_seconds,
        requested_video_duration_max_seconds=request.output.video_duration_max_seconds,
        requested_video_scene_duration_max_seconds=request.output.video_scene_duration_max_seconds,
        include_background_music=request.output.include_background_music,
        execution_mode=request.execution_mode.value,
        production_route=routing.route.value,
        routing_reasons=routing.reasons,
        routing_requires_override=routing.requires_override,
    )


async def freeze_compilation_product_media(
    compilation: MarketingAutomationCompilation,
    resolver: IFrozenProductMediaResolver,
    *,
    existing_package: ProductionReadyCreativePackage | None = None,
) -> MarketingAutomationCompilation:
    """Freeze the selected Variant media set before model preparation."""
    package = compilation.package
    family = package.sku.product_family
    if package.request.product_family is None or family is None:
        return compilation
    candidates = _candidate_product_media(package.request, family.media)
    if not candidates:
        raise CreativeContextUnavailableError(
            "No product media is mapped to the selected Product Family scope"
        )
    existing_media = {
        item.media_id: item
        for item in (
            existing_package.sku.product_family.media
            if existing_package is not None and existing_package.sku.product_family is not None
            else ()
        )
        if item.artifact_ref is not None and item.checksum_sha256 is not None
    }
    source_refs = tuple(
        ProductMediaSourceRef(
            source_id=family.ref.source_id,
            product_id=family.ref.product_id,
            media_id=item.media_id,
            url=item.url,
            variant_ids=item.variant_ids,
            artifact_ref=(
                existing_media.get(item.media_id).artifact_ref
                if item.media_id in existing_media
                else None
            ),
            checksum_sha256=(
                existing_media.get(item.media_id).checksum_sha256
                if item.media_id in existing_media
                else None
            ),
        )
        for item in candidates
    )
    resolved = await resolver.resolve_product_sources(
        request_id=package.request.request_id,
        sku_id=package.request.sku_id,
        source_refs=source_refs,
    )
    resolved_by_id = {item.media_id: item for item in resolved if item.media_id is not None}
    if len(resolved_by_id) != len(candidates):
        raise CreativeContextUnavailableError(
            "Not every selected Product Family image could be frozen immutably"
        )
    frozen_media = tuple(
        replace(
            item,
            artifact_ref=resolved_by_id[item.media_id].asset_ref,
            checksum_sha256=resolved_by_id[item.media_id].checksum_sha256,
        )
        for item in candidates
    )
    frozen_ids = {item.media_id for item in frozen_media}
    frozen_family = replace(
        family,
        variants=tuple(
            replace(variant, media_ids=tuple(mid for mid in variant.media_ids if mid in frozen_ids))
            for variant in family.variants
        ),
        media=frozen_media,
    )
    frozen_sku = replace(
        package.sku,
        product_metadata=replace(
            package.sku.product_metadata,
            image_refs=tuple(item.artifact_ref for item in frozen_media if item.artifact_ref),
        ),
        product_family=frozen_family,
    )
    frozen_work_item = replace(package.work_item, target_sku_set=(frozen_sku,))
    frozen_package = replace(package, sku=frozen_sku, work_item=frozen_work_item)
    case = compilation.intake.cases[0]
    frozen_context_snapshot = replace(
        case.request.context,
        product_image_count=len(frozen_media),
    )
    frozen_preparation = replace(
        case.context_template,
        sku=frozen_sku,
        pack_hash=_checksum(
            {
                "previous_pack_hash": case.context_template.pack_hash,
                "product_media": [
                    (item.media_id, item.artifact_ref, item.checksum_sha256)
                    for item in frozen_media
                ],
            }
        ),
    )
    frozen_request = CreativeIntakeRequest(
        trigger=case.request.trigger,
        context=frozen_context_snapshot,
        source_checksum_sha256=intake_fingerprint(
            case.request.trigger,
            frozen_context_snapshot,
            frozen_work_item,
            frozen_preparation,
        ),
    )
    return MarketingAutomationCompilation(
        package=frozen_package,
        intake=CreativeIntakeFixture(
            (
                CreativeIntakeCase(
                    frozen_request,
                    frozen_work_item,
                    frozen_preparation,
                ),
            )
        ),
    )


def _candidate_product_media(request, media):
    if request.selection_scope.value != "variant":
        return tuple(sorted(media, key=lambda item: item.position))
    return tuple(
        sorted(
            (
                item
                for item in media
                if not item.variant_ids or request.selected_variant_id in item.variant_ids
            ),
            key=lambda item: item.position,
        )
    )


def _checksum(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = [
    "MarketingAutomationCompilation",
    "MarketingCreativeAutomationCompiler",
    "freeze_compilation_product_media",
]
