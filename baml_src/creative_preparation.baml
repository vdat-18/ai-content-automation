class CreativePersonaHypothesis {
  name string
  description string
  rationale string
  evidence_refs string[]
  uncertainties string[]
}

class CreativeIdeaDraft {
  persona_id string
  angle string
  hook string
  concept string
  rationale string
  evidence_refs string[]
  claim_ids string[]
  reference_ids string[]
}

class CreativeIdeaCandidates {
  ideas CreativeIdeaDraft[]
}

class CreativeVariationDraft {
  variation_key string
  heading string
  visual_direction string
  evidence_refs string[]
  subtext string?
  awareness_stage string?
  angle string?
  offer string?
  production_level string?
  claim_ids string[]
  reference_ids string[]
}

class CreativeBriefDraft {
  heading string
  visual_direction string
  evidence_refs string[]
  subtext string?
  claim_ids string[]
  reference_ids string[]
  variations CreativeVariationDraft[]
}

enum IdeaRecommendation {
  SELECT
  KEEP
  REJECT
}

enum BriefReviewOutcome {
  PASS
  REVISE
  BLOCKED
}

class CompositionRegion {
  x int
  y int
  width int
  height int
}

enum TextAlignment {
  LEFT
  CENTER
  RIGHT
}

class CompositionTextPlacement {
  region CompositionRegion
  alignment TextAlignment
  text_color string
  background_color string?
}

class StaticCompositionDraft {
  visual_prompt string
  product_source_index int
  segmentation_prompt string
  product_region CompositionRegion
  heading CompositionTextPlacement
  subtext CompositionTextPlacement?
  logo_region CompositionRegion?
  rationale string
  evidence_refs string[]
}

enum SemanticCriterionStatus {
  PASS
  FAIL
  UNKNOWN
}

enum SemanticIssueSeverity {
  MINOR
  MAJOR
  CRITICAL
}

enum SemanticRepairAction {
  REGENERATE_FULL
  REGENERATE_WITH_CONSTRAINTS
  EDIT_REGION
  MANUAL_REVIEW
  REJECT_POLICY
}

class SemanticReviewEvidence {
  description string
  source_ref string
  region float[]?
}

class SemanticReviewIssue {
  code string
  severity SemanticIssueSeverity
  repair_action SemanticRepairAction
  description string
}

class SemanticCriterionReview {
  criterion_id string
  status SemanticCriterionStatus
  reason string
  score float?
  confidence float?
  evidence SemanticReviewEvidence[]
  issue SemanticReviewIssue?
}

class StaticCreativeReview {
  criteria SemanticCriterionReview[]
  summary string
  warnings string[]
}

class LabeledReviewImage {
  label string
  content image
}

function ResolveCreativePersona(
  instructions: string,
  input_json: string
) -> CreativePersonaHypothesis {
  client LocalMarketingLLM
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    Infer one useful audience hypothesis for Creative development from only the supplied
    exact Product/Variant truth, approved SecondBrain knowledge, and trusted human Additional
    requirements. This is a Creative hypothesis, not a researched customer fact or performance
    conclusion. Every evidence_refs value must be copied verbatim from allowed_evidence_refs.
    Do not use data-version text, a brand profile identifier, or concatenated identifiers.
    Do not invent product facts,
    claims, offers, prices, guarantees, demographics, or performance evidence. Preserve human
    direction as the highest-priority Creative instruction.
    </runtime_contract>

    {{ _.role("user") }}
    <input_json>
    {{ input_json }}
    </input_json>

    {{ ctx.output_format }}
  "#
}

function GenerateCreativeIdeas(
  instructions: string,
  input_json: string,
  max_ideas: int
) -> CreativeIdeaCandidates {
  client LocalMarketingLLM
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    Return at most {{ max_ideas }} evidence-grounded ideas. Every evidence_refs value must be
    copied verbatim from allowed_evidence_refs; never use data-version text, a brand profile
    identifier, or concatenated identifiers. Every claim_ids and reference_ids value must be an
    identifier present in the input.
    campaign_notes is the Marketing human's trusted Additional requirements.
    Follow it as the highest-priority creative direction, preserve its meaning, and do
    not require it to be split into persona, angle, hook, offer, or claim fields.
    Shopify price and compare-at price are factual product context only. Do not turn
    them into price, sale, or discount messaging unless the human direction explicitly
    requests that commercial treatment.
    Use requested_image_count and requested_video_count to keep every idea suitable for
    the actual requested media mix.
    Human-selected Research references are part of the starting context. Use their
    applicable layout, framing, lighting, palette, setting, and creative patterns when
    forming the idea, and preserve their IDs in reference_ids and evidence_refs. They are
    inspiration only: never copy their product, advertiser, logo, copy, claims, or
    distinctive brand assets, and never let them override Shopify product truth.
    </runtime_contract>

    {{ _.role("user") }}
    <input_json>
    {{ input_json }}
    </input_json>

    {{ ctx.output_format }}
  "#
}

function WriteCreativeBrief(
  instructions: string,
  input_json: string,
  variation_count: int
) -> CreativeBriefDraft {
  client LocalMarketingLLM
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    Write one production-ready Creative Set brief for the selected idea. It must be
    detailed enough to drive either image or video production.
    campaign_notes is the Marketing human's trusted Additional requirements.
    Follow it directly as the highest-priority creative direction without classifying
    it into separate fields. Exact copy, offer, or claim wording supplied there must be
    preserved rather than independently revalidated.
    Shopify price and compare-at price are factual product context only. Do not put
    them into copy or imply a promotion unless the human direction explicitly asks.
    Return exactly {{ variation_count }} explicit variations. Each variation must have
    a distinct visual direction and stable variation_key. Every evidence_refs value must be
    copied verbatim from allowed_evidence_refs; never use data-version text, a brand profile
    identifier, or concatenated identifiers. Do not invent evidence or claims. The top-level
    brief fields must
    mirror the first variation for compatibility with single-image consumers.

    Make every variation executable without another strategy-writing step. Its
    visual_direction must specify the composition and focal hierarchy, exact product
    placement and scale, camera/viewpoint, setting and background, lighting, palette,
    human presence or absence, and the intended use of approved text and logo. It must
    also state product-fidelity and negative constraints clearly enough for an image
    or video planner to act on them. Use heading and subtext as exact proposed copy,
    not as vague themes. heading and each variation heading must always be a non-empty
    internal creative title, even when the request disables rendered text; the application
    will not render it unless text is enabled. Use production_level to describe the concrete
    execution scope.
    Distinguish variations by a meaningful marketing hypothesis, not cosmetic wording.
    Use requested_image_count and requested_video_count to cover the actual media mix;
    video-capable directions must support purposeful scenes, continuity, motion, pacing,
    and transitions without imposing a fixed shot count.
    Incorporate every human-selected Research reference into the brief from the start,
    limited to applicable execution choices such as layout, framing, lighting, palette,
    setting, and creative pattern. Preserve its identifier in reference_ids and
    evidence_refs. Research must not replace Shopify product truth, approved claims,
    human direction, or brand assets.
    </runtime_contract>

    {{ _.role("user") }}
    <input_json>
    {{ input_json }}
    </input_json>

    {{ ctx.output_format }}
  "#
}

function PlanStaticComposition(
  instructions: string,
  input_json: string,
  product_images: LabeledReviewImage[]
) -> StaticCompositionDraft {
  client LocalMarketingLLM
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    Plan one static composition on a normalized 0-1000 canvas. Each CompositionRegion must use
    integer x and y values of at least 0, positive integer width and height values, and stay
    entirely inside the canvas: x + width <= 1000 and y + height <= 1000. Each text color must
    be a valid #RRGGBB or #RRGGBBAA hex string. Return a valid non-empty heading placement even
    when the request disables text. Every evidence_refs value must
    be copied verbatim from allowed_evidence_refs; never use data-version text, a brand profile
    identifier, or concatenated identifiers. Inspect every
    image labeled product_source_*, choose exactly one zero-based source index for exact
    pixel preservation, and write an English segmentation prompt for that product.
    Inspect every human-selected research reference image and use its applicable layout,
    framing, lighting, palette, or creative pattern. Do not drop or replace a selected
    reference. Never treat a research reference as
    product truth and never copy its product, logo, advertiser, copy, or claims.
    The image model produces the complete final image. Follow the request's explicit
    include_text and include_logo choices. When include_text is enabled with exact human
    copy, preserve it. When it is enabled without exact copy, use the Agent-written
    heading and subtext from the prepared brief. When disabled, omit text. Treat
    campaign_notes as trusted Marketing direction. Never invent logos or brand marks.
    </runtime_contract>

    {{ _.role("user") }}
    <input_json>
    {{ input_json }}
    </input_json>

    <planning_images>
    {% for source in product_images %}
    <image label="{{ source.label }}">
    {{ source.content }}
    </image>
    {% endfor %}
    </planning_images>

    {{ ctx.output_format }}
  "#
}

function ReviewStaticCreative(
  instructions: string,
  input_json: string,
  sources: LabeledReviewImage[]
) -> StaticCreativeReview {
  client LocalMarketingLLM
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    Review only the supplied images and typed context. Return exactly one
    assessment for every requested criterion and no additional criteria. Use
    UNKNOWN when the available evidence cannot support a conclusion. A FAIL
    must include one bounded repair instruction and other statuses must not.
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
