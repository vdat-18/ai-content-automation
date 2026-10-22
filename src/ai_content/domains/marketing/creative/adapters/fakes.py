"""Deterministic fake adapters for the walking skeleton.

No network, no model, no API: FakeContextCollector -> FakeIdeaGenerator ->
FakeImageGenerator -> DeterministicQAChecker -> FakeApprovalQueue.

Failure injection flags let scenario tests simulate source timeouts,
generator errors, empty idea sets and scripted QA outcomes.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from decimal import Decimal

from PIL import Image

from ..domain.entities import (
    AssetVersion,
    Cost,
    QACheckResult,
    QASession,
    VersionId,
)
from ..domain.reviews import (
    CriterionReview,
    CriterionStatus,
    ReviewOutcome,
    SemanticReviewResult,
)
from ..ports.contracts import (
    ContextPackage,
    CreativeWorkItemInput,
    EvidenceRef,
    FidelityCheck,
    IdeaPackage,
    RevisionRequest,
    SkuInput,
    StaticCreativeInput,
)
from ..ports.images import ProductCutout
from .image_files import read_local_image


class SyntheticProductSegmenter:
    """Explicit synthetic adapter used only by fake/offline runtimes."""

    async def extract(self, source_ref: str, prompt: str) -> ProductCutout:
        source = read_local_image(source_ref)
        with Image.open(io.BytesIO(source)) as opened:
            image = opened.convert("RGBA")
        mask = Image.new("L", image.size, 255)
        image.putalpha(mask)
        mask_stream = io.BytesIO()
        mask.save(mask_stream, format="PNG")
        cutout_stream = io.BytesIO()
        image.save(cutout_stream, format="PNG")
        return ProductCutout(
            rgba_png=cutout_stream.getvalue(),
            mask_png=mask_stream.getvalue(),
            source_checksum=hashlib.sha256(source).hexdigest(),
            model="synthetic-segmenter",
            model_version="1",
            prompt=prompt,
            bounding_box=(0, 0, image.width, image.height),
            source_width=image.width,
            source_height=image.height,
        )


class FakeContextCollector:
    """Returns a deterministic context package echoing SKU input."""

    def __init__(self, raise_on_collect: bool = False) -> None:
        self._raise_on_collect = raise_on_collect

    async def collect(
        self,
        work_item: CreativeWorkItemInput,
        sku: SkuInput,
    ) -> ContextPackage:
        if self._raise_on_collect:
            raise RuntimeError("fake source timeout while collecting context")
        return ContextPackage(
            context_id=f"{work_item.source_run_id}:{sku.sku_id}",
            source_run_id=work_item.source_run_id,
            sku_id=sku.sku_id,
            brand=work_item.marketing_scope.brand,
            evidence=(
                EvidenceRef(
                    source_id="synthetic-product-catalog",
                    data_version="synthetic-v1",
                ),
                EvidenceRef(
                    source_id="synthetic-creative-history",
                    data_version="synthetic-v1",
                ),
            ),
            historical=sku.historical_creative_context,
            brand_guideline_ref=sku.creative_constraints.brand_guideline_ref,
        )


class FakeIdeaGenerator:
    """Returns two deterministic ideas; honors persona_override on idea 1."""

    def __init__(
        self,
        raise_on_generate: bool = False,
        return_empty: bool = False,
    ) -> None:
        self._raise_on_generate = raise_on_generate
        self._return_empty = return_empty

    async def generate_ideas(
        self,
        context: ContextPackage,
        work_item: CreativeWorkItemInput,
    ) -> tuple[IdeaPackage, ...]:
        if self._raise_on_generate:
            raise RuntimeError("fake idea generator failure")
        if self._return_empty:
            return ()

        evidence_refs = tuple(e.source_id for e in context.evidence)
        checks = (FidelityCheck(check_id="product-truth", passed=True),)
        return (
            IdeaPackage(
                idea_id=f"{context.context_id}:idea-1",
                brand=context.brand,
                sku_id=context.sku_id,
                objective=work_item.objective,
                market=work_item.marketing_scope.market,
                persona=work_item.persona_override or "practical-optimizer",
                angle="one-statement-upgrade",
                hook="Upgrade your room with one statement piece",
                concept="product on a styled wall, warm daylight, minimal props",
                evidence_refs=evidence_refs,
                fidelity_checks=checks,
                confidence=Decimal("78"),
            ),
            IdeaPackage(
                idea_id=f"{context.context_id}:idea-2",
                brand=context.brand,
                sku_id=context.sku_id,
                objective=work_item.objective,
                market=work_item.marketing_scope.market,
                persona="style-seeker",
                angle="timeless-materials",
                hook="Style that outlasts trends",
                concept="close-up material texture, neutral background",
                evidence_refs=evidence_refs,
                fidelity_checks=checks,
                confidence=Decimal("64"),
            ),
        )


@dataclass(frozen=True)
class GenerationCall:
    """Record of one generator invocation for test assertions."""

    version_ref: str
    revision: RevisionRequest | None
    variation_id: str | None = None


class FakeImageGenerator:
    """Deterministic generator that records every call including revisions.

    v1 receives revision=None; regenerated versions receive the RevisionRequest
    derived from the previous QA failure and produce a "-revised" artifact.
    """

    def __init__(
        self,
        cost_per_version: Decimal = Decimal("0.10"),
        raise_on_generate: bool = False,
    ) -> None:
        self.calls: list[GenerationCall] = []
        self._cost_per_version = cost_per_version
        self._raise_on_generate = raise_on_generate

    async def generate(
        self,
        input_data: StaticCreativeInput,
        version_id: VersionId,
        revision: RevisionRequest | None = None,
    ) -> AssetVersion:
        self.calls.append(
            GenerationCall(
                version_ref=version_id.value,
                revision=revision,
                variation_id=input_data.variation_id,
            )
        )
        if self._raise_on_generate:
            raise RuntimeError("fake image generation failure")

        suffix = "-revised" if revision is not None else ""
        seed_material = f"{input_data.idea_id}:{version_id.value}"
        seed = int.from_bytes(
            hashlib.sha256(seed_material.encode("utf-8")).digest()[:4],
            byteorder="big",
        ) % (2**31)
        return AssetVersion(
            version_id=version_id,
            attempt_number=version_id.version_number,
            input_ref=f"idea:{input_data.idea_id}",
            artifact_url=f"fake://artifacts/{version_id.value}{suffix}.png",
            cost=Cost(self._cost_per_version, "USD"),
            generator_version="fake-image-generator@1",
            seed=seed,
            creative_set_id=input_data.creative_set_id,
            variation_id=input_data.variation_id,
            variation_attempt_number=1,
        )


class DeterministicQAChecker:
    """Scripted QA: fails the first `fail_times` checks, then passes.

    Failing results carry the configured issues plus feedback text; pass
    results carry the configured warnings. Non-empty policy_violations on a
    failing check route the job to the Policy Queue.
    """

    def __init__(
        self,
        fail_times: int = 1,
        issues: tuple[str, ...] = ("brand_logo_missing", "product_not_visible"),
        policy_violations: tuple[str, ...] = (),
        fail_score: Decimal = Decimal("40"),
        pass_score: Decimal = Decimal("85"),
        pass_warnings: tuple[str, ...] = ("minor: text contrast near threshold",),
    ) -> None:
        self.call_count = 0
        self.last_version_ref: str | None = None
        self._fail_times = fail_times
        self._issues = issues
        self._policy_violations = policy_violations
        self._fail_score = fail_score
        self._pass_score = pass_score
        self._pass_warnings = pass_warnings

    async def check(self, session: QASession) -> QACheckResult:
        self.call_count += 1
        self.last_version_ref = session.asset.version_id.value
        if self.call_count <= self._fail_times:
            feedback = f"Fix attempt {self.call_count}: " + "; ".join(self._issues)
            return QACheckResult(
                passed=False,
                score=self._fail_score,
                issues=self._issues,
                warnings=(),
                feedback=feedback,
                policy_violations=self._policy_violations,
            )
        return QACheckResult(
            passed=True,
            score=self._pass_score,
            warnings=self._pass_warnings,
        )


class ScriptedSemanticReviewer:
    """Return semantic results by variation and attempt without call-order coupling."""

    def __init__(
        self,
        results: dict[tuple[str, int], SemanticReviewResult] | None = None,
        attempt_results: dict[int, SemanticReviewResult] | None = None,
        default: SemanticReviewResult | None = None,
    ) -> None:
        self._results = results or {}
        self._attempt_results = attempt_results or {}
        self._default = default or SemanticReviewResult(
            outcome=ReviewOutcome.PASS,
            score=Decimal("85"),
            criteria=(
                CriterionReview(
                    criterion_id="brief_alignment",
                    status=CriterionStatus.PASS,
                    reason="Synthetic semantic review pass",
                    score=Decimal("4"),
                    confidence=Decimal("1"),
                ),
            ),
            reviewer_version="scripted-semantic-reviewer@1",
            summary="Synthetic semantic review pass",
        )
        self.calls: list[tuple[str, int]] = []

    async def review(self, session: QASession) -> SemanticReviewResult:
        variation_id = session.asset.variation_id or "default"
        attempt = session.asset.variation_attempt_number
        key = (variation_id, attempt)
        self.calls.append(key)
        return self._results.get(key, self._attempt_results.get(attempt, self._default))
