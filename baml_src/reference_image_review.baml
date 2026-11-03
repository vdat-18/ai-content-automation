class ReferenceImageReview {
  usable bool
  quality_score int
  reason string
  scene_type "lifestyle_scene" | "environment" | "flatlay" | "studio_plain" | "cutout" | "graphic" | "other"
  scene_description string
  placement_note string
  heavy_text bool
  style string[]
  colors string[]
}

function ReviewReferenceImage(product_type: string, image: image) -> ReferenceImageReview {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You review one Pinterest image as a reference for marketing photos of a product type.
    The goal is to borrow the scene: its background, setting, composition and styling, so our
    own product of that type can be placed into a similar scene. Return JSON only and exactly
    match the response schema.

    Fill scene_type from visible evidence first, then decide usable:
    lifestyle_scene (a lived-in setting with real surroundings), environment (a real room or
    place), flatlay (items arranged on a textured surface), studio_plain (plain, white or
    seamless backdrop), cutout (product on a transparent or blank background), graphic
    (infographic, collage, illustration, screenshot or text layout), other.

    Set usable=true only when scene_type is lifestyle_scene, environment or flatlay, the
    background has real, visible content worth borrowing, and a product of the given type could
    be placed into or swapped within that scene. Set usable=false for studio_plain, cutout and
    graphic images, images with heavy text, logos or watermarks over the picture, low quality
    images, and scenes where nothing can be borrowed.

    scene_description: one sentence on the background and setting. placement_note: one sentence
    on where and how our product could be placed. heavy_text: large areas of text.
    style: up to 4 short style words. colors: up to 4 color names.
    quality_score: 1 to 10, how valuable the scene is as a reference (10: sharp, well lit,
    attractive, rich real surroundings and an obvious place for the product; 1: unusable).
    reason: one short sentence explaining the usable decision.

    {{ _.role("user") }}
    Product type: {{ product_type }}
    {{ image }}

    {{ ctx.output_format }}
  "#
}
