class ReferenceImageReview {
  usable bool
  reason string
  matches_product_type bool
  heavy_text bool
  style string[]
  composition string
  colors string[]
  focal_point string
}

function ReviewReferenceImage(product_type: string, image: image) -> ReferenceImageReview {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You review one Pinterest image as a style reference for marketing photos of a product type.
    Return JSON only and exactly match the response schema.

    Set usable=true only when the image shows the product type clearly and works as a visual
    reference for composition, lighting, setting or styling. Set usable=false for infographics
    or collages with heavy text, logos or watermarks covering the image, screenshots, drawings
    or illustrations, low quality images, and images that do not show the product type.
    matches_product_type: the product type is the main subject. heavy_text: large areas of text.
    style: up to 4 short style words. composition: one short sentence. colors: up to 4 color names.
    focal_point: what draws the eye. reason: one short sentence explaining the usable decision.

    {{ _.role("user") }}
    Product type: {{ product_type }}
    {{ image }}

    {{ ctx.output_format }}
  "#
}
