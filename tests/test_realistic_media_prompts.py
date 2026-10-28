from decimal import Decimal
from types import SimpleNamespace

from ai_content.domains.marketing.creative.adapters.managed_media import (
    _image_prompt,
    _video_prompt,
)
from ai_content.domains.marketing.creative.application.paid_media_production import (
    _repair_request,
)
from ai_content.domains.marketing.creative.ports.media_production import (
    PaidImageGenerationRequest,
    PaidMediaArtifact,
    PaidMediaGenerationLimits,
    PaidMediaSource,
    PaidVideoGenerationRequest,
)

_SHA = "a" * 64


def _image_request(*sources: PaidMediaSource, **overrides) -> PaidImageGenerationRequest:
    return PaidImageGenerationRequest(
        request_id="r",
        package_id="p",
        sku_id="s",
        variation_key="v",
        visual_direction="A woman asleep on white linen in soft morning light",
        width=1024,
        height=1024,
        sources=sources,
        limits=PaidMediaGenerationLimits(timeout_seconds=30, max_cost=Decimal("1")),
        **overrides,
    )


def test_plain_prompt_describes_a_photograph_without_advertising_boilerplate() -> None:
    prompt = _image_prompt(_image_request(PaidMediaSource("a", _SHA, "product")))
    assert prompt.startswith("A woman asleep on white linen")
    assert "product image 1" in prompt
    assert "advertising image" not in prompt and "ultra realistic" not in prompt
    assert "The image contains no text" in prompt and "The image contains no logo" in prompt


def test_swap_reference_becomes_the_scene_that_is_edited() -> None:
    scene = PaidMediaSource(
        "scene", _SHA, "style", swap_mode="replace", note="the mask on her face"
    )
    prompt = _image_prompt(
        _image_request(
            scene, PaidMediaSource("a", _SHA, "product"), generation_mode="multi_image_edit"
        )
    )
    assert prompt.startswith("Edit the photograph in image 1. Replace the matching product")
    assert "from image 2" in prompt and "Placement: the mask on her face." in prompt
    assert "contact shadows" in prompt


def test_repair_edits_the_generated_image_when_the_model_can_edit() -> None:
    model = SimpleNamespace(
        model_id="m",
        supported_modes=("single_image_edit", "multi_image_edit"),
        max_reference_images=3,
    )
    descriptor = SimpleNamespace(image_models=(model,), max_reference_images=3)
    request = _image_request(
        PaidMediaSource("p1", _SHA, "product"),
        PaidMediaSource("p2", _SHA, "product"),
        PaidMediaSource("p3", _SHA, "product"),
        model_id="m",
    )
    artifact = PaidMediaArtifact(
        artifact_ref="out",
        checksum_sha256="b" * 64,
        content_type="image/png",
        provider_id="x",
        provider_job_id="j",
        model="m",
        model_revision=None,
        elapsed_seconds=1.0,
        cost=Decimal("0.04"),
        width=1,
        height=1,
    )
    repaired = _repair_request(descriptor, request, artifact, 2, "Add a contact shadow.")
    assert [item.role for item in repaired.sources] == ["draft", "product", "product"]
    assert repaired.generation_mode == "multi_image_edit"
    prompt = _image_prompt(repaired)
    assert prompt.startswith("Edit image 1: Add a contact shadow.")

    single = SimpleNamespace(image_models=(), max_reference_images=1)
    fallback = _repair_request(single, request, artifact, 2, "Fix the cap.")
    assert fallback.sources == request.sources and "Fix the cap." in fallback.visual_direction


def test_video_prompt_asks_for_motion_and_keeps_the_product_stable() -> None:
    request = PaidVideoGenerationRequest(
        request_id="r",
        package_id="p",
        sku_id="s",
        visual_direction="Slow push-in on the mask resting on the pillow",
        aspect_ratio="9:16",
        sources=(PaidMediaSource("k", _SHA, "keyframe"),),
        limits=PaidMediaGenerationLimits(timeout_seconds=30, max_cost=Decimal("1")),
        duration_seconds=6,
        continuity_direction="one shot",
    )
    prompt = _video_prompt(request)
    assert prompt.startswith("Slow push-in")
    assert "exact shape, label, color and material" in prompt
    assert "Do not generate" not in prompt


def test_edit_mode_sends_xai_typed_reference_entries() -> None:
    from ai_content.domains.marketing.creative.adapters.managed_media import _reference_payload
    from ai_content.domains.marketing.creative.config.managed_media import (
        ManagedImageModelConfig,
    )

    edit = ManagedImageModelConfig(model="m", reference_field="images", request_mode="json_edit")
    generation = ManagedImageModelConfig(model="m", reference_field="images")
    assert _reference_payload(edit, ["data:a"]) == [{"type": "image_url", "url": "data:a"}]
    assert _reference_payload(generation, ["data:a"]) == [{"image_url": "data:a"}]
