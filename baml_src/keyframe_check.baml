class KeyframeCheck {
  passed bool
  problem string
}

function CheckKeyframe(
  shot_description: string,
  product_photos: image[],
  master_keyframe: image?,
  keyframe: image,
  character: image?,
  previous_keyframe: image?
) -> KeyframeCheck {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You are a strict quality checker for a generated still image of an ad video shot. Compare the
    generated keyframe with the real product photos and return JSON only, exactly matching the
    response schema.

    passed=true only when all of these hold: the product in the keyframe is clearly the same
    product as in the photos (same shape, color, proportions, material, label layout,
    same number of items); its size next to the person, the furniture and the room matches the
    real size stated in the shot description (not oversized, not tiny); it has no extra or missing parts and no warped geometry; the picture shows what the shot description asks for;
    when a master keyframe is given, the light and color palette match it; when the previous
    shot's keyframe is given, the same person wears the same outfit in the same kind of room and
    light, so the two shots could be cut together without a jarring jump; when a character image
    is given, the person in the keyframe is clearly the same person (face, hair, skin tone,
    clothes) and has natural hands and limbs with no extra or missing fingers. Ignore
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

    {% if character %}
    Character (the same person must appear):
    {{ character }}
    {% endif %}

    Generated keyframe to check:
    {{ keyframe }}

    {{ ctx.output_format }}
  "#
}
