class ResearchProductMatchDraft {
  product_id string
  match_kind "product_visible" | "scene_fit" | "style_only"
  confidence float
}

class ResearchReferenceProfileDraft {
  summary string
  relevance_to_project string
  primary_subject string
  content_goal string
  reference_types string[]
  product_categories string[]
  visual_style string[]
  composition string[]
  setting string[]
  colors string[]
  camera_motion string[]
  text_treatment string[]
  temporal_structure string[]
  audio_observations string[]
  hook string
  message string
  creative_takeaways string[]
  do_not_copy string[]
  observed_facts string[]
  inferences string[]
  media_notes string[]
  applicability_constraints string[]
  scene_type "lifestyle_scene" | "environment" | "flatlay" | "studio_plain" | "cutout" | "graphic" | "other"
  scene_description string
  background_usable bool
  background_reason string
  placement_note string
  camera_angle string
  lighting string
  swap_mode "insert" | "replace" | "style_only" | "reject"
  market_fit "us" | "neutral" | "non_us"
  product_matches ResearchProductMatchDraft[]
}

class ResearchScreeningDraft {
  usable bool
  materially_blurry bool
  reason_code string
  reason string
  confidence float
  profile ResearchReferenceProfileDraft?
}

function ScreenResearchReference(
  instructions: string,
  input_json: string,
  sources: LabeledReviewImage[]
) -> ResearchScreeningDraft {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    Decide whether this single public-media candidate is a useful Creative reference.
    Judge only the supplied typed project context and labeled media. Return usable=false
    with profile=null for navigation UI, login screens, placeholders, tiny thumbnails,
    irrelevant content, materially blurry media, or media without a concrete transferable
    Creative idea. Set materially_blurry=true only when blur prevents the main subject,
    composition, product presentation, text layout, or other transferable pattern from being
    understood reliably. Do not reject intentional background bokeh, localized motion blur,
    or another deliberate effect when the useful Creative pattern remains clear. A materially
    blurry candidate must return usable=false, reason_code="blurry_media", and profile=null. When
    usable=true, ground every profile field in visible evidence, keep observations and
    inferences separate, and never treat competitor claims as product truth. reason_code
    must be lowercase snake_case. confidence must be between 0 and 1.

    The reference is only valuable when its background can host one of the project's own
    products. Fill the scene fields from visible evidence first, then decide.
    scene_type: lifestyle_scene (real people or a lived-in setting), environment (an empty
    real room or place), flatlay, studio_plain (plain, white or seamless studio backdrop),
    cutout (product on a removed or flat colour background), graphic (illustration, collage,
    poster or text-led layout), other. The goal is to put one of the project's own products
    into this scene, so a competitor's product of the same kind in focus is an opportunity,
    not a problem. background_usable=true when the frame shows a real scene, surface or
    backdrop and either has free area where a product fits at a believable scale and
    perspective, or shows a similar product that could be replaced by ours (a person wearing
    a sleep mask, masks laid on a bed, a mask on a studio backdrop all qualify). Small
    captions or a logo do not disqualify an image whose scene is clear. background_usable=
    false only when there is no usable scene: text-led or graphic layouts, collages, app or
    web screenshots, extreme close-ups with no surroundings, or text, logos and overlays
    covering most of the frame. placement_note says where the product could go or what it
    replaces. swap_mode: insert (add the product into free space), replace (swap a similar
    existing object for the product), style_only (keep only mood, colour and composition),
    reject (no usable scene and no transferable style). When background_usable=false,
    swap_mode must be style_only or reject.
    market_fit: the project sells to shoppers in the United States. us when the setting,
    architecture, furnishings, people, retail context or visible language clearly read as
    American; neutral when nothing ties the image to a country; non_us when the setting,
    visible text or currency clearly belongs to another market (for example non-English
    text, yen or euro prices, or a distinctly foreign home style).
    product_matches: use ONLY product_id values from project_context.products and never
    invent ids. Add a match only when it is true: product_visible when that kind of product
    is actually shown in the image, scene_fit when the setting suits its usage_scenes and the
    product could be placed there, style_only when only the mood fits. Do not match a
    product whose avoid_scenes describe this setting, and respect each product's
    not_to_confuse_with list. Return an empty list when no product fits.
    </runtime_contract>

    {{ _.role("user") }}
    <input_json>
    {{ input_json }}
    </input_json>

    <labeled_media>
    {% for source in sources %}
    <image label="{{ source.label }}">
    {{ source.content }}
    </image>
    {% endfor %}
    </labeled_media>

    {{ ctx.output_format }}
  "#
}
