"""LLM orchestration service for the bounded Media Lab Create Image flow."""

from __future__ import annotations

import hashlib
import json

from ..domain.models import (
    ImageCapability,
    ImageOrchestrationPlan,
    ImageOrchestrationTrace,
    ImagePlanningSource,
    ImagePlanningState,
    ImageReferencePlan,
    ImageReferenceRole,
    ImageSourceOrigin,
)
from ..ports.interfaces import IImageOrchestrator, MediaLabImageOrchestrationError


class MediaLabImageOrchestrationService:
    def __init__(
        self,
        orchestrator: IImageOrchestrator,
        capabilities: tuple[ImageCapability, ...],
    ) -> None:
        self._orchestrator = orchestrator
        self._capabilities = capabilities

    def model(self) -> str:
        return self._orchestrator.model

    def maximum_source_count(self) -> int:
        return min(
            self._orchestrator.max_images,
            max(capability.maximum_reference_count for capability in self._capabilities),
        )

    async def plan(
        self,
        user_request: str,
        sources: tuple[ImagePlanningSource, ...],
    ) -> ImageOrchestrationPlan:
        if not user_request.strip():
            raise MediaLabImageOrchestrationError(
                "Creative request cannot be blank",
                status_code=400,
                code="invalid_request",
            )
        if len(sources) > self.maximum_source_count():
            raise MediaLabImageOrchestrationError(
                "Planning sources exceed the configured pinned image capability",
                status_code=400,
                code="too_many_sources",
            )
        if tuple(source.source_index for source in sources) != tuple(range(len(sources))):
            raise MediaLabImageOrchestrationError(
                "Planning sources must have consecutive indexes",
                status_code=400,
                code="invalid_sources",
            )
        plan = await self._orchestrator.plan(user_request.strip(), sources, self._capabilities)
        self._validate_plan(plan, sources)
        return plan

    def draft(
        self,
        user_request: str,
        sources: tuple[ImagePlanningSource, ...],
        *,
        questions: tuple[str, ...],
        uncertainties: tuple[str, ...],
    ) -> ImageOrchestrationPlan:
        """Build an explicit human-requested draft from an unresolved plan."""
        upload_indexes = tuple(
            source.source_index
            for source in sources
            if source.source_origin == ImageSourceOrigin.UPLOAD
        )
        previous_indexes = tuple(
            source.source_index
            for source in sources
            if source.source_origin == ImageSourceOrigin.MEDIA_LAB_OUTPUT
        )
        if len(previous_indexes) > 1 or (previous_indexes and not upload_indexes):
            raise MediaLabImageOrchestrationError(
                "Draft generation needs one uploaded product source when revising a previous result",
                status_code=409,
                code="draft_sources_unsupported",
            )

        if previous_indexes:
            capability_id = "edit_existing"
            references = tuple(
                ImageReferencePlan(
                    source_index=index,
                    role=ImageReferenceRole.PRODUCT_SOURCE,
                    priority=100 - offset,
                    must_preserve=(
                        "product identity, geometry, proportions, materials, colors, labels, and visible details",
                    ),
                    allowed_changes=("only changes explicitly requested by the user",),
                    identity_group="draft-product",
                )
                for offset, index in enumerate(upload_indexes)
            ) + (
                ImageReferencePlan(
                    source_index=previous_indexes[0],
                    role=ImageReferenceRole.PREVIOUS_OUTPUT,
                    priority=90,
                    must_preserve=("base composition unless the user requests a change",),
                    allowed_changes=("changes explicitly requested by the user",),
                ),
            )
        elif not upload_indexes:
            capability_id = "create_from_text"
            references = ()
        elif len(upload_indexes) == 1:
            capability_id = "product_source"
            references = (
                ImageReferencePlan(
                    source_index=upload_indexes[0],
                    role=ImageReferenceRole.PRODUCT_SOURCE,
                    priority=100,
                    must_preserve=(
                        "product identity, geometry, proportions, materials, colors, labels, and visible details",
                    ),
                    allowed_changes=("only changes explicitly requested by the user",),
                    identity_group="draft-product",
                ),
            )
        else:
            capability_id = "product_and_style"
            references = (
                ImageReferencePlan(
                    source_index=upload_indexes[0],
                    role=ImageReferenceRole.PRODUCT_SOURCE,
                    priority=100,
                    must_preserve=(
                        "product identity, geometry, proportions, materials, colors, labels, and visible details",
                    ),
                    allowed_changes=("only changes explicitly requested by the user",),
                    identity_group="draft-product",
                ),
                *(
                    ImageReferencePlan(
                        source_index=index,
                        role=ImageReferenceRole.STYLE_REFERENCE,
                        priority=max(1, 90 - offset),
                        must_preserve=(),
                        allowed_changes=("adapt visual style as requested",),
                    )
                    for offset, index in enumerate(upload_indexes[1:])
                ),
            )

        if not any(item.capability_id == capability_id for item in self._capabilities):
            raise MediaLabImageOrchestrationError(
                "The selected sources cannot be generated as a draft with the current image setup",
                status_code=409,
                code="draft_capability_unavailable",
            )
        summary = (
            "Draft generation will use the request as written. Visible text and unresolved "
            "details require careful human review."
        )
        plan_payload = {
            "capability_id": capability_id,
            "production_prompt": user_request.strip(),
            "references": [
                {
                    "source_index": item.source_index,
                    "role": item.role.value,
                    "priority": item.priority,
                    "must_preserve": item.must_preserve,
                    "allowed_changes": item.allowed_changes,
                    "identity_group": item.identity_group,
                }
                for item in references
            ],
        }
        trace = ImageOrchestrationTrace(
            user_request=user_request.strip(),
            capability_id=capability_id,
            summary=summary,
            planner_model="deterministic-draft-override",
            planner_prompt_version="draft-override-v1",
            planner_prompt_hash=_stable_hash("media-lab-image-draft-override-v1"),
            planner_config_hash=_stable_hash(
                json.dumps({"mapping": "first-upload-product-rest-style"}, sort_keys=True)
            ),
            plan_hash=_stable_hash(json.dumps(plan_payload, sort_keys=True)),
        )
        plan = ImageOrchestrationPlan(
            state=ImagePlanningState.READY,
            summary=summary,
            questions=questions,
            uncertainties=uncertainties,
            capability_id=capability_id,
            production_prompt=user_request.strip(),
            references=references,
            trace=trace,
        )
        self._validate_plan(plan, sources)
        return plan

    def _validate_plan(
        self,
        plan: ImageOrchestrationPlan,
        sources: tuple[ImagePlanningSource, ...],
    ) -> None:
        if plan.state == ImagePlanningState.NEEDS_INPUT:
            if (
                plan.capability_id is not None
                or plan.production_prompt is not None
                or plan.references
            ):
                raise MediaLabImageOrchestrationError(
                    "Terra returned an invalid needs-input plan",
                    code="invalid_provider_output",
                )
            return
        if plan.state != ImagePlanningState.READY:
            raise MediaLabImageOrchestrationError(
                "Terra returned an unknown plan state",
                code="invalid_provider_output",
            )
        if plan.capability_id is None or plan.production_prompt is None:
            raise MediaLabImageOrchestrationError(
                "Terra returned an incomplete ready plan",
                code="invalid_provider_output",
            )
        capability = next(
            (item for item in self._capabilities if item.capability_id == plan.capability_id),
            None,
        )
        if capability is None:
            raise MediaLabImageOrchestrationError(
                "Terra selected an unsupported Media Lab capability",
                code="invalid_provider_output",
            )
        source_indexes = tuple(item.source_index for item in plan.references)
        if (
            len(plan.references) != len(sources)
            or len(set(source_indexes)) != len(source_indexes)
            or set(source_indexes) != set(range(len(sources)))
        ):
            raise MediaLabImageOrchestrationError(
                "Terra did not resolve every planning source exactly once",
                code="invalid_provider_output",
            )
        roles = tuple(item.role for item in plan.references)
        if not _matches_capability_roles(roles, capability):
            raise MediaLabImageOrchestrationError(
                "Terra returned an invalid reference role combination",
                code="invalid_provider_output",
            )
        if any(item.priority < 1 or item.priority > 100 for item in plan.references):
            raise MediaLabImageOrchestrationError(
                "Terra returned an invalid reference priority",
                code="invalid_provider_output",
            )
        product_references = tuple(
            item for item in plan.references if item.role == ImageReferenceRole.PRODUCT_SOURCE
        )
        if any(
            not item.identity_group or not item.identity_group.strip()
            for item in product_references
        ):
            raise MediaLabImageOrchestrationError(
                "Terra omitted a product identity group",
                code="invalid_provider_output",
            )
        if len({item.identity_group for item in product_references}) > 1:
            raise MediaLabImageOrchestrationError(
                "Terra mixed multiple product identities in one image plan",
                code="invalid_provider_output",
            )
        if any(
            item.role != ImageReferenceRole.PRODUCT_SOURCE and item.identity_group is not None
            for item in plan.references
        ):
            raise MediaLabImageOrchestrationError(
                "Terra assigned an identity group to a non-product source",
                code="invalid_provider_output",
            )
        source_by_index = {source.source_index: source for source in sources}
        for reference in plan.references:
            source = source_by_index[reference.source_index]
            if reference.role == ImageReferenceRole.PRODUCT_SOURCE:
                if not reference.must_preserve:
                    raise MediaLabImageOrchestrationError(
                        "Terra omitted product preservation constraints",
                        code="invalid_provider_output",
                    )
                if source.source_origin != ImageSourceOrigin.UPLOAD:
                    raise MediaLabImageOrchestrationError(
                        "Terra selected a generated output as product source truth",
                        code="invalid_provider_output",
                    )
            if (
                reference.role == ImageReferenceRole.PREVIOUS_OUTPUT
                and source.source_origin != ImageSourceOrigin.MEDIA_LAB_OUTPUT
            ):
                raise MediaLabImageOrchestrationError(
                    "Terra selected an untracked image as a previous Media Lab output",
                    code="invalid_provider_output",
                )
            if (
                reference.role != ImageReferenceRole.PREVIOUS_OUTPUT
                and source.source_origin == ImageSourceOrigin.MEDIA_LAB_OUTPUT
            ):
                raise MediaLabImageOrchestrationError(
                    "Terra assigned a previous Media Lab output to an invalid reference role",
                    code="invalid_provider_output",
                )


def _matches_capability_roles(
    roles: tuple[ImageReferenceRole, ...],
    capability: ImageCapability,
) -> bool:
    product_count = roles.count(ImageReferenceRole.PRODUCT_SOURCE)
    style_count = roles.count(ImageReferenceRole.STYLE_REFERENCE)
    previous_count = roles.count(ImageReferenceRole.PREVIOUS_OUTPUT)
    allowed_roles = set(capability.required_roles)
    if any(role not in allowed_roles for role in roles):
        return False
    if not (
        capability.minimum_product_source_count
        <= product_count
        <= capability.maximum_product_source_count
    ):
        return False
    if not (
        capability.minimum_style_reference_count
        <= style_count
        <= capability.maximum_style_reference_count
    ):
        return False
    expected_previous_count = int(ImageReferenceRole.PREVIOUS_OUTPUT in allowed_roles)
    if previous_count != expected_previous_count:
        return False
    return capability.minimum_reference_count <= len(roles) <= capability.maximum_reference_count


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = ["MediaLabImageOrchestrationService"]
