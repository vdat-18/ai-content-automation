class KeyframeCheck {
  passed bool
  problem string
}

function CheckKeyframe(
  shot_description: string,
  product_photos: image[],
  master_keyframe: image?,
  keyframe: image,
  characters: image[],
  previous_keyframe: image?
) -> KeyframeCheck {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You are a strict quality checker for a generated still image of an ad video shot. Compare the
    generated keyframe with the real product photos and return JSON only, exactly matching the
    response schema.

    passed=true only when all of these hold: the product is clearly visible in the keyframe and
    not hidden, cut off or tiny; the product in the keyframe is clearly the same
    product as in the photos (same shape, color, proportions, material, label layout,
    same number of items); its size next to the person, the furniture and the room matches the
    real size stated in the shot description (not oversized, not tiny); it has no extra or missing parts and no warped geometry; the picture shows what the shot description asks for;
    it looks like an ordinary photo taken on a phone, not an AI render: no plastic or waxy skin,
    no glossy retouched glow, no impossible light or perfect symmetry;
    when a master keyframe is given, the light and color palette match it; when the previous
    shot's keyframe is given, the same person wears the same outfit in the same kind of room and
    light, so the two shots could be cut together without a jarring jump; when character images
    are given, the person in the keyframe is clearly the same person as in them (face shape, eyes,
    hair length and colour, skin tone; the clothes may differ when the shot asks for the product
    to be worn) and has natural hands and limbs with no extra or missing fingers; it follows
    every rule listed after the shot description under "Approved rules" (when there are any), and
    a broken rule is a failure. Ignore
    all text and logos, on the product label, the packaging and the clothes alike: image models
    cannot draw small text, so never fail an image because text is garbled, mirrored or rotated.
    Ignore background decoration unless it contradicts the product.

    problem: empty when passed. Otherwise one or two short English sentences naming what is
    wrong and what to change, written as an instruction for the image model.

    {{ _.role("user") }}
    Shot description: {{ shot_description }}

    Real product photos:
    {% for photo in product_photos %}
    {{ photo }}
    {% endfor %}

    {% if master_keyframe %}
    Master keyframe (the scene to match):
    {{ master_keyframe }}
    {% endif %}

    {% if previous_keyframe %}
    Previous shot's keyframe (this shot must continue from it):
    {{ previous_keyframe }}
    {% endif %}

    {% if characters %}
    Photos of the person (the same person must appear):
    {% for character in characters %}
    {{ character }}
    {% endfor %}
    {% endif %}

    Generated keyframe to check:
    {{ keyframe }}

    {{ ctx.output_format }}
  "#
}
