class ReferenceImageReview {
  usable bool
  description string
}

function ReviewReferenceImage(product_type: string, image: image) -> ReferenceImageReview {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You review one Pinterest image as a reference for marketing photos of a product type.
    The goal is to borrow the scene: its background, setting, composition and styling, so our
    own product of that type can be placed into a similar scene. Return JSON only and exactly
    match the response schema.

    Set usable=true only when the image shows a real scene (a lived-in setting, a real room or
    place, or items arranged on a textured surface), the background has real, visible content
    worth borrowing, and a product of the given type could be placed into or swapped within that
    scene. Set usable=false for plain, white or seamless studio backdrops, products on blank
    backgrounds, infographics, collages, illustrations, screenshots, images with heavy text,
    logos or watermarks over the picture, low quality images, and scenes where nothing can be
    borrowed.

    description: two or three sentences, written so someone who cannot see the image can
    understand it and compare it with a product photo: the setting and surroundings, lighting,
    style, dominant colors, props, camera angle, and exactly where and how a product of the given
    type could be placed in the scene. For an unusable image, say what makes it unusable.

    {{ _.role("user") }}
    Product type: {{ product_type }}
    {{ image }}

    {{ ctx.output_format }}
  "#
}
