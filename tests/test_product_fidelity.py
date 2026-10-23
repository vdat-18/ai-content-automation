import asyncio
from decimal import Decimal
from types import SimpleNamespace

from ai_content.domains.marketing.creative.adapters.product_fidelity import _evaluation
from ai_content.domains.marketing.creative.application.paid_media_production import (
    PaidMediaProductionService,
)
from ai_content.domains.marketing.creative.ports.media_production import (
    PaidImageGenerationRequest,
    PaidMediaArtifact,
    PaidMediaGenerationLimits,
    PaidMediaQualityEvaluation,
    PaidMediaQualityIssue,
    PaidMediaSource,
)


def _request() -> PaidImageGenerationRequest:
    return PaidImageGenerationRequest(
        request_id="req-1",
        package_id="pkg-1",
        sku_id="sku-1",
        variation_key="v1",
        visual_direction="A bright bathroom shelf.",
        width=1024,
        height=1024,
        sources=(PaidMediaSource("artifact:product", "a" * 64, "product"),),
        limits=PaidMediaGenerationLimits(timeout_seconds=30, max_cost=Decimal("1")),
    )


class _Provider:
    def __init__(self) -> None:
        self.requests: list[PaidImageGenerationRequest] = []
        self.descriptor = SimpleNamespace(
            image_models=(),
            supported_aspect_ratios=("1:1",),
            max_reference_images=1,
            fidelity_mode="generative",
        )

    async def generate(self, request: PaidImageGenerationRequest) -> PaidMediaArtifact:
        self.requests.append(request)
        return PaidMediaArtifact(
            artifact_ref=f"artifact:{len(self.requests)}",
            checksum_sha256="b" * 64,
            content_type="image/png",
            provider_id="grok",
            provider_job_id=f"job-{len(self.requests)}",
            model="xai/grok-imagine-image",
            model_revision=None,
            elapsed_seconds=1.0,
            cost=Decimal("0.02"),
            width=1024,
            height=1024,
        )


class _Evaluator:
    def __init__(self, outcomes: list[str]) -> None:
        self._outcomes = outcomes

    async def evaluate_image(self, request, artifact) -> PaidMediaQualityEvaluation:
        if self._outcomes.pop(0) == "pass":
            return PaidMediaQualityEvaluation("pass", "Product matches.")
        issue = PaidMediaQualityIssue(
            "shape_changed", "Tube became a bottle.", "major", "Keep the tube."
        )
        return PaidMediaQualityEvaluation("revise", "Product changed.", (issue,))


def _service(provider: _Provider, evaluator: _Evaluator) -> PaidMediaProductionService:
    registry = SimpleNamespace(require_image=lambda provider_id=None: provider)
    return PaidMediaProductionService(registry, image_evaluator=evaluator, max_image_attempts=3)


def test_failed_fidelity_check_regenerates_with_the_repair() -> None:
    provider = _Provider()
    result = asyncio.run(
        _service(provider, _Evaluator(["revise", "pass"])).produce_image(_request())
    )

    assert [item.evaluation.outcome for item in result.attempts] == ["revise", "pass"]
    assert result.selected_artifact.artifact_ref == "artifact:2"
    assert result.total_cost == Decimal("0.04")
    assert "Keep the tube." in provider.requests[1].visual_direction
    assert provider.requests[1].request_id != provider.requests[0].request_id


def test_fidelity_attempts_are_bounded_and_end_in_human_review() -> None:
    provider = _Provider()
    evaluator = _Evaluator(["revise", "revise", "revise"])
    result = asyncio.run(_service(provider, evaluator).produce_image(_request()))

    assert len(provider.requests) == 3
    assert result.success and result.attempts[-1].evaluation.outcome == "human_review"
    assert result.total_cost == Decimal("0.06")


def test_verdict_parsing() -> None:
    passed = _evaluation('```json\n{"verdict": "pass", "summary": "Same tube.", "issues": []}\n```')
    assert passed.outcome == "pass"
    failed = _evaluation('{"verdict": "fail", "summary": "Frame is wood.", "issues": []}')
    assert failed.outcome == "revise" and failed.issues[0].repair_instruction


def test_outputs_that_still_fail_the_check_reach_human_review() -> None:
    from ai_content.domains.marketing.creative.application.final_review import (
        build_final_creative_review,
    )

    evaluator = _Evaluator(["revise", "revise", "revise"])
    result = asyncio.run(_service(_Provider(), evaluator).produce_image(_request()))
    review = build_final_creative_review(
        review_id="review-1",
        request_id="req-1",
        package_id="pkg-1",
        brand_id="AuraSleep",
        sku_id="sku-1",
        objective="conversion",
        platform="meta",
        direction_summary="Halloween night routine.",
        expected_image_count=1,
        expected_video_count=0,
        results=(("req-1:image:1:v1", "image", result),),
    )

    assert review.assets[0].qa_summary.startswith("Product fidelity still failing")
