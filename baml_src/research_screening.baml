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
