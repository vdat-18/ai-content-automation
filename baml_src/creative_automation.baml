enum CreativeAutomationReadiness {
  READY
  NEEDS_INPUT
}

enum AutomationHumanPresence {
  PRODUCT_ONLY
  HANDS_ONLY
  HUMAN_IN_USE
  HUMAN_LIFESTYLE
  ON_CAMERA_PRESENTER
}

enum AutomationVideoVoiceMode {
  NONE
  VOICE_OVER
  ON_CAMERA
}

enum AutomationVideoMusicMode {
  NONE
  SUBTLE_BACKGROUND
  MOOD_DRIVEN
}

enum AutomationVideoGenerationStrategy {
  ONE_SHOT
  MULTI_SOURCE
}

class AutomationImagePlan {
  variation_key string
  scenario string
  creative_hypothesis string
  human_presence AutomationHumanPresence
  visual_direction string
  product_id string?
  selected_variant_id string?
  selected_media_ids string[]?
  reference_ids string[]?
  reference_rationale string?
  evidence_refs string[]
}

class AutomationVideoAudioPlan {
  voice_mode AutomationVideoVoiceMode
  music_mode AutomationVideoMusicMode
  voice_direction string?
  music_direction string?
  continuity_direction string
}

class AutomationVideoScenePlan {
  scene_id string
  purpose string
  visual_direction string
  audio_direction string?
  transition_direction string
  generation_duration_seconds int
  usable_duration_seconds int
  selected_variant_id string?
  selected_media_ids string[]?
  evidence_refs string[]
}

class AutomationVideoPlan {
  variation_key string
  scenario string
  creative_hypothesis string
  human_presence AutomationHumanPresence
  generation_strategy AutomationVideoGenerationStrategy
  final_duration_seconds int
  continuity_plan string
  audio_plan AutomationVideoAudioPlan
  product_id string?
  reference_ids string[]?
  reference_rationale string?
  scenes AutomationVideoScenePlan[]
  evidence_refs string[]
}

class CreativeAutomationPlanDraft {
  readiness CreativeAutomationReadiness
  missing_context string[]
  strategy_summary string
  rationale string
  evidence_refs string[]
  image_plans AutomationImagePlan[]
  video_plans AutomationVideoPlan[]
  uncertainties string[]
}

function OrchestrateCreativeAutomation(
  instructions: string,
  input_json: string,
  product_images: LabeledReviewImage[],
  image_count: int,
  video_count: int,
  duration_min_seconds: int,
  duration_max_seconds: int,
  source_duration_max_seconds: int
) -> CreativeAutomationPlanDraft {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    Plan exactly one SKU. Never combine or infer another SKU.
    Return exactly {{ image_count }} image plans and exactly {{ video_count }} video plans
    when READY. Treat the requested outputs as one diverse Creative portfolio: choose
    distinct evidence-grounded scenarios, hypotheses, settings, hooks, human presence,
    visual language, and audio treatment instead of returning near-duplicates. The human
    does not select scenarios or human presence; choose them semantically from the product
    context and each brief. The human may explicitly pin video audio; only when audio is
    unpinned may you choose voice or music semantically. Do not use a fixed scenario rotation.
    request.notes is the Marketing human's trusted Additional requirements.
    Follow it directly as the highest-priority creative direction, preserve its meaning,
    and do not classify or independently revalidate its offer, claim, or copy wording.
    Shopify price and compare-at price are factual product context only. Do not place
    price, sale, or discount messaging in an output unless that human direction explicitly
    requests it.

    Treat request.creative_set_strategy as the binding relationship between outputs:
    SINGLE creates one focused execution; MULTI_ANGLE keeps the concept, layout and
    background coherent while showing materially different useful product views;
    LAYOUT_VARIATIONS keeps product identity, offer and setting intent while testing
    composition; BACKGROUND_VARIATIONS keeps product framing coherent while testing
    distinct evidence-grounded environments; COPY_VARIATIONS keeps the exact approved
    copy unchanged while varying only its placement, scale, and visual hierarchy; CAROUSEL
    creates an ordered, visually consistent sequence whose frames each communicate one
    role. Still return one independent plan for every requested output: every plan is one
    provider call and must produce exactly one image or one video, never a collage, contact
    sheet, multi-panel image, or bundle of alternatives.

    Every final video duration must be between {{ duration_min_seconds }} and
    {{ duration_max_seconds }} seconds inclusive. Choose ONE_SHOT only when one coherent
    source duration does not exceed {{ source_duration_max_seconds }} seconds; for any
    final duration at or below that limit, always return exactly one scene and ONE_SHOT.
    For any final duration above that limit, always choose MULTI_SOURCE and return at
    least two coherent scenes. Keep every scene at or below
    {{ source_duration_max_seconds }} seconds, and make scene durations add up exactly to
    final_duration_seconds. Provide a concrete continuity plan and intentional transitions
    so independently generated sources assemble naturally without morphing the product or
    people.

    Respect request.video_generate_audio exactly. When false, select NONE for both voice
    and music and return null audio directions. When true, enable at least one supported
    voice or music mode based on the brief. Legacy null requests may choose audio from the
    declared provider capabilities. Enabled modes require concise directions; disabled
    modes require null directions.
    When voice is enabled, direct natural US English appropriate to the concept. Keep one
    voice and music identity across a multi-source video, never split a sentence
    across sources, and keep music subordinate to speech. Scene audio_direction must be
    executable by the native-audio video model and consistent with the portfolio audio plan.

    The prepared_brief already incorporates the exact Research references selected by the
    human. Preserve that intent during output planning; Research may shape execution but must
    not replace the product, persona, angle, hook, message, offer, or human direction.
    Respect request.reference_selection_mode and provider_capabilities in input_json. New requests
    use only NONE or HUMAN; never select Research references on the human's behalf. Map the first
    image plan to image:1, the second to image:2, and likewise map video plans to video:1,
    video:2, and so on. NONE selects no Research reference. HUMAN preserves every exact reference
    in request.reference_assignments for that output without adding, removing, replacing, ranking,
    or redistributing it. Explain the concrete use in reference_rationale, and copy
    every selected ID into both reference_ids and evidence_refs. For each provider call, choose one
    or more Shopify Product media IDs so the combined count of selected Product media, selected
    Research references, and an enabled logo does not exceed the selected model's
    max_reference_images. Inspect the supplied Product images rather than choosing from metadata
    alone. For a video model and resolution that declares reference_to_video_resolutions, select
    2-3 useful Shopify Product images per scene when at least two are available, never exceeding
    max_product_images or the total input limit after preserving human Research references. If the
    exact Variant has only one available Product image, select that one image and no Research
    reference so production can use image-to-video. At resolutions outside
    reference_to_video_resolutions, select exactly one Product image and no Research reference.
    When
    request.image_generation_mode is single_image_edit, choose exactly one Shopify Product media
    ID for every image plan. When it is multi_image_edit and at least two eligible Shopify images
    fit after the Research and logo slots, select 2-3 complementary Product views for each image
    plan, never more than three. Use only declared generation durations, aspect ratios, output
    formats, native voice, and native music capabilities.

    Every image plan and video plan must preserve the exact product_id supplied in input_json.
    Select only variant IDs and media IDs present in the supplied Product Family context. Each
    output must use one variant identity; never combine media mapped to different variants.
    When a plan has no selected_variant_id, select only family-level media with no variant mapping.
    A request pinned to one variant must use that exact variant for every image and scene.

    For image plans, inspect the Research references selected for that output and translate only
    their applicable layout, framing, lighting, palette, and creative patterns into visual_direction.
    References are inspiration only: never copy their product, advertiser, logo, copy, claims,
    or distinctive brand assets. The supplied Shopify product and Variant remain the only
    product identity and truth. Design for the United States market with natural American
    commercial styling. Follow the request's explicit include_text and include_logo choices.
    When text is enabled with exact human copy, preserve it. When text is enabled without
    exact copy, use the Agent-written heading and subtext from the prepared brief. Incorporate
    enabled text and logo into the image-model direction so the provider returns one complete
    final image. When disabled, explicitly direct the provider to omit that element. Count an enabled uploaded logo against the image
    provider's max_reference_images and reserve one slot for it; at least one slot must remain
    for the Shopify product source. Never invent additional copy or brand marks.

    Write every image visual_direction as one photographer-style paragraph of flowing prose,
    in this order: subject and setting; the product's placement, scale and visible details;
    camera viewpoint and lens (for example eye level, 85mm); the light source with its
    direction and softness; physical material descriptions; color palette; composition and
    what stays sharp. Include human presence or absence and the exact text/logo treatment.
    Name concrete objects and materials, and state each texture once on the right object.
    Describe what should appear instead of listing exclusions, and never use stacked quality
    words such as ultra realistic, premium or award-winning. A Research reference described as
    an edit-ready scene is used as the real photograph: production edits it and puts the product
    in, so write visual_direction as the change to that photograph (where the product goes,
    its scale and any copy placement) instead of describing a new scene.

    For each video scene, apply the same Product-truth versus research-inspiration boundary.
    Use every Research reference selected for that video output for composition, setting,
    lighting, camera language, or pacing only, and preserve those exact IDs in every
    scene's evidence_refs. Never copy the
    reference product, advertiser, logo, text, claims, or distinctive brand assets.
    Every scene must specify camera framing and movement, product action, setting, lighting,
    subject continuity, transition intent, and the exact visual state at the beginning and end
    of the scene so independently generated sources can be assembled without another planning step.
    The opening frame of each scene is generated separately from the product image, so write the
    scene's visual_direction as motion, not as a still: one subject, one action and one camera
    move, using specific verbs. Prefer a steady product with a moving camera or environment over
    a moving product, and avoid fast or articulated motion, close text and rapid cuts.

    Videos must contain no generated text, captions, logos, or watermarks. Images may contain
    only human-supplied exact text or Agent-written brief text, plus a logo explicitly enabled
    by the request.
    Preserve supplied evidence identifiers exactly. If required product truth is absent,
    return NEEDS_INPUT and name it; never invent missing context.
    Keep the response compact and complete. Prefer one or two concise sentences for each
    summary, rationale, direction, and uncertainty field. Do not repeat the supplied input,
    runtime contract, evidence descriptions, or schema. Return only the requested JSON object.
    </runtime_contract>

    {{ _.role("user") }}
    <input_json>
    {{ input_json }}
    </input_json>

    <product_images>
    {% for source in product_images %}
    <image label="{{ source.label }}">
    {{ source.content }}
    </image>
    {% endfor %}
    </product_images>

    {{ ctx.output_format }}
  "#
}
