class LabeledReferenceImage {
  label string
  note string
  content image
}

class StoryboardShot {
  role "hook" | "problem" | "demo" | "benefit" | "call_to_action"
  description string
  keyframe_prompt string
  motion_prompt string
  duration_seconds int
  on_screen_text string
  voiceover string
}

class ContentBrief {
  title string
  selected_reference_labels string[]
  reference_rationale string
  scene string
  product_placement string
  selling_angle string
  target_audience string
  style string[]
  colors string[]
  shots StoryboardShot[]
}

function DraftContentBrief(
  product_json: string,
  user_idea: string,
  shot_count: int,
  product_images: image[],
  references: LabeledReferenceImage[]
) -> ContentBrief {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You are a senior creative strategist for affiliate content on TikTok Shop Vietnam. Write ONE
    excellent brief for a product photo that sells the product to Vietnamese shoppers. Return JSON
    only and exactly match the response schema.

    The reference images are approved scenes whose background, setting and styling we borrow. Look
    at them, pick the 1 to 3 that suit this product best, and put their labels in
    selected_reference_labels. Explain the choice in reference_rationale. Describe the scene to
    recreate in scene and say exactly where and how the product sits in product_placement. Never
    copy a reference literally and never reuse another brand's product, logo or text from it.

    The brief is a storyboard for one vertical ad video made of exactly {{ shot_count }} shot(s).
    Every shot is first made as a still keyframe image and later animated into a 15 second clip, so all shots must happen in the
    same scene (same place, light and color) and show the same real product. Do not show human
    faces; hands, the product and the space are enough.

    Every number, percentage, price, material or feature in the text must come from the product
    facts; never invent figures or claims.

    Ground every claim in the product facts and the product photos. Take the product's real
    color, shape and details from the product photos, never from the references. Do not invent
    features, certifications or prices.
    selling_angle: the single strongest reason to buy, in Vietnamese. target_audience: who buys it
    and why, in Vietnamese. style: up to 4 short words. colors: up to 4 color names. title: a
    short Vietnamese name for the brief.

    shots: exactly {{ shot_count }} shot(s) in story order, each lasting 15 seconds, so
    duration_seconds is always 15. The first shot opens with a hook and the last ends with a
    call_to_action; when there is only one shot it does both, hooking in the first seconds and
    ending on the call to action. For every shot: description (Vietnamese, what the viewer sees), keyframe_prompt
    (a complete, self-contained English prompt for an image model: the real product as the clear
    hero, the shared scene, camera angle, lighting, style and colors, and an explicit instruction
    that the product keeps its real shape, color, proportions and label), motion_prompt (English,
    two or three sentences describing how the camera or objects move over the 15 seconds, one
    continuous gentle movement without cuts, for animating the keyframe),
    duration_seconds, on_screen_text (a short Vietnamese caption, or an empty string) and
    voiceover (one Vietnamese sentence).

    If the user gave an idea, treat it as the creative direction: keep its intent, make it
    concrete, fix weak points and enrich it with the best references and product facts. If the
    idea is empty, choose the direction yourself.

    {{ _.role("user") }}
    Product facts:
    {{ product_json }}

    User idea (may be empty):
    {{ user_idea }}

    Product photos:
    {% for photo in product_images %}
    {{ photo }}
    {% endfor %}

    Reference images:
    {% for reference in references %}
    {{ reference.label }}: {{ reference.note }}
    {{ reference.content }}
    {% endfor %}

    {{ ctx.output_format }}
  "#
}
