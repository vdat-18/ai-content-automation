class KeyframeCheck {
  passed bool
  problem string
}

function CheckKeyframe(
  shot_description: string,
  product_photos: image[],
  master_keyframe: image?,
  keyframe: image
) -> KeyframeCheck {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You are a strict quality checker for a generated still image of an ad video shot. Compare the
    generated keyframe with the real product photos and return JSON only, exactly matching the
    response schema.

    passed=true only when all of these hold: the product in the keyframe is clearly the same
    product as in the photos (same shape, color, proportions, material, label and printed text,
    same number of items); it has no extra or missing parts, no warped geometry and no
    unreadable or invented text or logos; the picture shows what the shot description asks for;
    and, when a master keyframe is given, the place, light and color palette match it. Ignore
    background text and small decoration unless it contradicts the product.

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

    Generated keyframe to check:
    {{ keyframe }}

    {{ ctx.output_format }}
  "#
}
