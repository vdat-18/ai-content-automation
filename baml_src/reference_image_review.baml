class ReferenceImageReview {
  usable bool
  description string
  reject_reason string?
  setting string?
  surface_and_props string[]?
  lighting string?
  color_palette string[]?
  style string[]?
  camera string?
  people string?
  placement string?
  suits string[]?
  motion_ideas string[]?
  quality int?
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
    logos or watermarks over the picture, low quality images, AI-generated or 3D-rendered looking
    pictures, glossy retouched magazine or advertising shots, and scenes too simple to teach
    anything (one object on an empty surface, one flat color). Prefer casual, real-life photos
    that look taken on a phone in a real home or place.

    The review is read later by people and by models that choose which reference to give an image
    and video generator, and they cannot see the picture. So describe it completely, in English.
    description: four to six sentences that paint the whole picture: the place, what is in it, how
    it is lit, the style and mood, the colors, the camera, and exactly where and how a product of
    the given type could be placed. For an unusable image, say what makes it unusable.
    reject_reason: empty when usable, otherwise one short sentence (for example "plain studio
    backdrop" or "heavy text overlay").
    setting: the kind of place in a few words (for example "bathroom shelf", "bedroom vanity").
    surface_and_props: the surfaces and objects in view, each a few words.
    lighting: direction, softness and color of the light (for example "soft window light from the
    left, warm").
    color_palette: the three to five dominant colors as plain color names.
    style: two to four style words (for example "minimal", "cozy", "luxury", "rustic").
    camera: angle, distance and framing (for example "eye level, medium close shot, shallow depth").
    people: "none" when nobody is in the picture, otherwise who is there, the pose, and what the
    hands are doing, because a person shown with a product is valuable for an ad.
    placement: the exact spot for the product and how large it would look next to the scene.
    suits: which kinds of video shot this scene fits, chosen from hook, problem, demo, benefit,
    call_to_action, flat_lay, in_hand, unboxing, before_after.
    motion_ideas: one to three simple movements that could animate this scene (for example "hand
    reaches in and places the bottle", "slow push-in on the shelf").
    quality: 1 to 5 for sharpness, composition, how appealing it is and how much it looks like an
    everyday photo taken on a phone rather than an ad or a render.

    {{ _.role("user") }}
    Product type: {{ product_type }}
    {{ image }}

    {{ ctx.output_format }}
  "#
}
