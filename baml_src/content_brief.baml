class LabeledReferenceImage {
  label string
  note string
  content image
}

class ContentBrief {
  title string
  selected_reference_labels string[]
  reference_rationale string
  scene string
  product_placement string
  selling_angle string
  target_audience string
  composition string
  style string[]
  colors string[]
  on_image_text string
  image_prompt string
}

function DraftContentBrief(
  product_json: string,
  user_idea: string,
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

    Ground every claim in the product facts and the product photos. Take the product's real
    color, shape and details from the product photos, never from the references. Do not invent
    features, certifications or prices.
    selling_angle: the single strongest reason to buy, in Vietnamese. target_audience: who buys it
    and why, in Vietnamese. composition: framing, camera angle, lighting. style: up to 4 short
    words. colors: up to 4 color names. on_image_text: a short Vietnamese headline for the image,
    or an empty string when the image should have no text. title: a short Vietnamese name for the
    brief. image_prompt: a complete English prompt for an image model that includes the product as
    the clear hero, the scene, placement, composition, lighting, style and colors, and states that
    the product must keep its real shape, color and details.

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
