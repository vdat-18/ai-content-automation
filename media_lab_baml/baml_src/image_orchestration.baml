enum MediaLabImagePlanState {
  READY
  NEEDS_INPUT
}

enum MediaLabImageCapabilityId {
  CREATE_FROM_TEXT
  PRODUCT_SOURCE
  PRODUCT_AND_STYLE
  EDIT_EXISTING
}

enum MediaLabImageReferenceRole {
  PRODUCT_SOURCE
  STYLE_REFERENCE
  PREVIOUS_OUTPUT
}

enum MediaLabImageQualityDecision {
  PASS
  REGENERATE
  HUMAN_REVIEW
}

enum MediaLabImageQualityIssueSeverity {
  MINOR
  MAJOR
  CRITICAL
}

class MediaLabPlanningImage {
  source_index int
  content image
}

class MediaLabReviewImage {
  label string
  content image
}

class MediaLabImageReferencePlan {
  source_index int
  role MediaLabImageReferenceRole
  priority int
  must_preserve string[]
  allowed_changes string[]
  identity_group string?
}

class MediaLabImagePlan {
  state MediaLabImagePlanState
  summary string
  questions string[]
  uncertainties string[]
  capability_id MediaLabImageCapabilityId?
  production_prompt string?
  references MediaLabImageReferencePlan[]
}

class MediaLabImageQualityIssue {
  category string
  severity MediaLabImageQualityIssueSeverity
  description string
}

class MediaLabImageQualityReview {
  decision MediaLabImageQualityDecision
  summary string
  issues MediaLabImageQualityIssue[]
  repair_instructions string[]
  uncertainties string[]
}

class MediaLabImageRepairPrompt {
  production_prompt string
}

function PlanMediaLabImage(
  instructions: string,
  input_json: string,
  capabilities_json: string,
  sources: MediaLabPlanningImage[]
) -> MediaLabImagePlan {
  client MediaLabTerra
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    The executable capabilities, allowed role cardinalities, and maximum style
    reference count are supplied in capabilities_json. The source manifest
    supplies an index and origin for every image. Never invent a source or
    reuse a source index. For READY, resolve every supplied source exactly once
    and choose one capability from capabilities_json. Use NEEDS_INPUT when the
    request is ambiguous, conflicting, cannot be represented by a supplied
    capability, or lacks the original product source required for an edit.
    A product source must have concrete must_preserve details grounded in the
    supplied image or user instruction. Assign the same short English
    identity_group to every PRODUCT_SOURCE only when those images show the
    same product identity from different views. STYLE_REFERENCE and
    PREVIOUS_OUTPUT must use null. If supplied product images are different
    products, SKUs, or variants, return NEEDS_INPUT rather than merging them.
    Write a visual-only production prompt
    for FLUX.2 Dev. Do not invent product facts, claims, prices, CTA, exact
    copy, or a logo asset. Do not treat generated text or logos as final
    approved brand material. Every user-facing text field in the typed output
    must be English, even when the request or source content is another language.
    </runtime_contract>

    {{ _.role("user") }}
    <capabilities_json>
    {{ capabilities_json }}
    </capabilities_json>

    <input_json>
    {{ input_json }}
    </input_json>

    <source_images>
    {% for source in sources %}
    <image source_index="{{ source.source_index }}">
    {{ source.content }}
    </image>
    {% endfor %}
    </source_images>

    {{ ctx.output_format }}
  "#
}

function ReviewMediaLabImage(
  instructions: string,
  input_json: string,
  sources: MediaLabReviewImage[]
) -> MediaLabImageQualityReview {
  client MediaLabTerra
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    Review the candidate image against only the labeled source images and typed
    reference contract supplied in input_json. Use PASS only when the available
    visual evidence supports the requested result without a material conflict.
    Use REGENERATE only when a new FLUX.2 Dev prompt can safely address the
    observed issue while preserving the same product-source contract. Use
    HUMAN_REVIEW for ambiguity, insufficient visual evidence, or any concern
    that should not be auto-retried. REGENERATE must include one or more concise
    repair_instructions. PASS must not include issues, repair instructions, or
    uncertainties. Every user-facing typed field must be English.
    </runtime_contract>

    {{ _.role("user") }}
    <input_json>
    {{ input_json }}
    </input_json>

    <labeled_images>
    {% for source in sources %}
    <image label="{{ source.label }}">
    {{ source.content }}
    </image>
    {% endfor %}
    </labeled_images>

    {{ ctx.output_format }}
  "#
}

function RewriteMediaLabImagePrompt(
  instructions: string,
  input_json: string
) -> MediaLabImageRepairPrompt {
  client MediaLabTerra
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    Rewrite one visual-only FLUX.2 Dev production prompt from the original
    production prompt, typed reference contract, and structured Terra review
    supplied in input_json. Preserve all must_preserve constraints and include
    only the bounded repair instructions. Do not invent product facts, claims,
    prices, CTA, exact copy, or a logo asset. Return one complete production
    prompt in English only.
    </runtime_contract>

    {{ _.role("user") }}
    <input_json>
    {{ input_json }}
    </input_json>

    {{ ctx.output_format }}
  "#
}

enum MediaLabVideoPlanState {
  READY
  NEEDS_INPUT
}

enum MediaLabVideoCapabilityId {
  CREATE_FROM_TEXT
  CREATE_FROM_IMAGES
}

enum MediaLabVideoSourceRole {
  PRODUCT
  STYLE
  BACKGROUND
  CHARACTER
  KEYFRAME
  STORYBOARD
}

enum MediaLabVideoSourceUsage {
  GENERATION
  VERIFICATION
  BOTH
}

enum MediaLabVideoVerificationStage {
  TRACKING
  PRODUCT_FIDELITY
  TEMPORAL_QUALITY
}

enum MediaLabVideoQualityDecision {
  PASS
  REGENERATE
  HUMAN_REVIEW
}

enum MediaLabVideoQualityIssueSeverity {
  MINOR
  MAJOR
  CRITICAL
}

class MediaLabVideoPlanningImage {
  source_index int
  content image
}

class MediaLabVideoReviewImage {
  label string
  content image
}

class MediaLabVideoSourcePlan {
  source_index int
  role MediaLabVideoSourceRole
  usage MediaLabVideoSourceUsage
  priority int
  must_preserve string[]
  allowed_changes string[]
  identity_group string?
  is_primary_identity bool
}

class MediaLabVideoVerificationStagePlan {
  stage MediaLabVideoVerificationStage
  reason string
}

class MediaLabVideoPlan {
  state MediaLabVideoPlanState
  summary string
  questions string[]
  uncertainties string[]
  capability_id MediaLabVideoCapabilityId?
  production_prompt string?
  sources MediaLabVideoSourcePlan[]
  verification_plan MediaLabVideoVerificationStagePlan[]
}

class MediaLabVideoQualityIssue {
  category string
  severity MediaLabVideoQualityIssueSeverity
  description string
}

class MediaLabVideoQualityReview {
  decision MediaLabVideoQualityDecision
  summary string
  issues MediaLabVideoQualityIssue[]
  repair_instructions string[]
  uncertainties string[]
}

class MediaLabVideoRepairPrompt {
  production_prompt string
}

function PlanMediaLabVideo(
  instructions: string,
  input_json: string,
  capabilities_json: string,
  sources: MediaLabVideoPlanningImage[]
) -> MediaLabVideoPlan {
  client MediaLabTerra
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    All uploaded images are equal, unclassified sources. Infer each source's role and
    usage only from the user's request and visible evidence. The executable capabilities
    and generation-image cardinality are supplied in capabilities_json. Never invent,
    duplicate, or omit a source index. For READY, resolve every supplied source exactly
    once. A source can be used for generation, verification, or both. Use NEEDS_INPUT
    when roles are ambiguous, sources conflict, exact product identities or variants are
    mixed, or the request needs more generation images than the active pinned graph accepts.

    Select a typed verification plan. TEMPORAL_QUALITY is mandatory for every READY plan.
    Assign identity_group to every PRODUCT or CHARACTER source. Use the same short English
    group ID only for multiple views of the same visible identity; use different IDs for distinct
    identities. Other roles must use null. Set is_primary_identity only for the one identity group
    selected as the automatic verification target.

    Select TRACKING only when exactly one primary PRODUCT or CHARACTER identity group must remain
    consistent through time and at least one source in that group is used for verification. Every
    PRODUCT or CHARACTER source used for specialized verification must belong to that same primary
    group. Multiple views of the same product may represent that one group. PRODUCT_FIDELITY
    requires TRACKING and at least one primary original uploaded PRODUCT source used for
    verification. Do not treat a generated Media Lab output as product truth. If multiple distinct
    identities require automatic tracking or fidelity verification, use NEEDS_INPUT because the
    active verifier supports one primary identity group per shot. Do not select SAM/DINO stages
    merely because images were supplied.

    Write one visual-only MiniMax H3 production prompt using only generation sources. Do not
    invent product facts, claims, prices, CTA, exact copy, logo assets, audio, or a publish
    decision. Every user-facing typed field must be English, even when the request or source
    content is another language.
    </runtime_contract>

    {{ _.role("user") }}
    <capabilities_json>
    {{ capabilities_json }}
    </capabilities_json>

    <input_json>
    {{ input_json }}
    </input_json>

    <source_images>
    {% for source in sources %}
    <image source_index="{{ source.source_index }}">
    {{ source.content }}
    </image>
    {% endfor %}
    </source_images>

    {{ ctx.output_format }}
  "#
}


enum MediaLabVideoAdPlanState {
  READY
  NEEDS_INPUT
}

class MediaLabVideoAdShotPlan {
  shot_id string
  purpose string
  production_prompt string
  source_indexes int[]
  generation_duration_seconds int
  usable_duration_seconds float
  on_screen_text string?
}

class MediaLabVideoAdPlan {
  state MediaLabVideoAdPlanState
  summary string
  questions string[]
  uncertainties string[]
  target_duration_seconds float
  aspect_ratio string
  sources MediaLabVideoSourcePlan[]
  shots MediaLabVideoAdShotPlan[]
}

function PlanMediaLabVideoAd(
  instructions: string,
  input_json: string,
  sources: MediaLabVideoPlanningImage[]
) -> MediaLabVideoAdPlan {
  client MediaLabTerra
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    Build one executable final marketing Video Ad timeline for MiniMax H3. Split the
    final 20-25 second Ad into 3-6 independent source shots. Each shot must request
    4-8 generated seconds and select 3-8 usable seconds. The sum of usable durations
    must exactly equal target_duration_seconds. Exact on-screen copy is returned
    separately as on_screen_text and rendered later by deterministic FFmpeg code.
    Never ask H3 to draw exact text, logos, prices, claims, subtitles, or CTA. H3 can
    generate native voice, dialogue, narration, ambient sound, sound effects, and music;
    include grounded audio direction in production_prompt when the brief requests it.

    Resolve every supplied image exactly once in sources based on the human brief and
    visible pixels. Every source must use GENERATION. Assign PRODUCT or CHARACTER sources
    an identity_group; multiple views of the same identity must share one group. Other
    roles must use null. At most one identity group may be marked primary. source_indexes
    reference only supplied images used to condition that shot and each shot must stay
    within maximum_generation_images from input_json. Use an empty list for text-to-video.
    Use only visible/source-supported product facts. Keep
    product-detail, human-action, camera, payoff, and CTA roles distinct when the brief
    needs them. Prefer short coherent shots over one long multi-scene generation.
    Return NEEDS_INPUT when the brief lacks enough truth to choose a product, claim,
    offer, or required scene safely. Every user-facing field and production prompt must
    be English. shot_id must be unique ASCII letters, digits, underscores, or hyphens.
    </runtime_contract>

    {{ _.role("user") }}
    <input_json>
    {{ input_json }}
    </input_json>

    <source_images>
    {% for source in sources %}
    <image source_index="{{ source.source_index }}">
    {{ source.content }}
    </image>
    {% endfor %}
    </source_images>

    {{ ctx.output_format }}
  "#
}

function ReviewMediaLabVideo(
  instructions: string,
  input_json: string,
  sources: MediaLabVideoReviewImage[]
) -> MediaLabVideoQualityReview {
  client MediaLabTerra
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    Review only the labeled temporal candidate evidence, resolved source contract, and
    selected verifier evidence supplied in input_json. A missing unselected verifier is
    irrelevant. Never turn an unavailable selected stage into PASS. Compare consecutive
    candidate frames across the timestamped timeline. Use HUMAN_REVIEW for ambiguity,
    insufficient evidence, possible detail drift or flicker between samples, audio concerns,
    or a repair that cannot be safely automated. Use PASS only when the available evidence
    supports the requested short shot without a material concern. Use REGENERATE only when
    one new MiniMax H3 generation from the original source contract can safely address the
    observed issue. REGENERATE requires concise repair_instructions. PASS cannot contain
    issues, repair instructions, or uncertainties. Every user-facing typed field must be English.
    </runtime_contract>

    {{ _.role("user") }}
    <input_json>
    {{ input_json }}
    </input_json>

    <labeled_images>
    {% for source in sources %}
    <image label="{{ source.label }}">
    {{ source.content }}
    </image>
    {% endfor %}
    </labeled_images>

    {{ ctx.output_format }}
  "#
}

function RewriteMediaLabVideoPrompt(
  instructions: string,
  input_json: string
) -> MediaLabVideoRepairPrompt {
  client MediaLabTerra
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    Rewrite one visual-only MiniMax H3 production prompt from the original prompt, resolved
    multi-source contract, selected verification evidence, and structured Terra review in
    input_json. Preserve every must_preserve constraint and apply only the bounded repair
    instructions. Do not invent product facts, claims, prices, CTA, exact copy, logo assets,
    audio, or a publish decision. Return one complete production prompt in English only.
    </runtime_contract>

    {{ _.role("user") }}
    <input_json>
    {{ input_json }}
    </input_json>

    {{ ctx.output_format }}
  "#
}
