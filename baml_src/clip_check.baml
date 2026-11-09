class ClipCheck {
  passed bool
  problem string
}

function CheckClip(
  shot_description: string,
  product_photos: image[],
  keyframe: image,
  characters: image[],
  clip_frames: image[]
) -> ClipCheck {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You are a strict quality checker for a short AI-generated video clip of an ad shot. You get
    a few frames taken in time order from the clip (the first one is near the start, the last one
    near the end), the keyframe the clip was animated from, and the real product photos. Return
    JSON only, exactly matching the response schema.

    passed=true only when all of these hold: the product stays clearly visible in every frame and
    keeps the same shape, color, proportions, material and number of items as in the product
    photos and the keyframe, with no melting, warping, splitting or growing between frames; no
    object appears from nowhere or vanishes between frames; when photos of the person are given,
    the person in every frame is clearly the same person (face shape, hair, skin tone; the clothes
    may differ when the shot shows the product worn) as in the photos and the keyframe; hands and limbs look natural with no extra, missing,
    fused or bent-backwards fingers or arms, and the body stays well proportioned in every frame
    (a realistic head to body ratio and normal limb length, never stretched or distorted) and the
    face keeps clear skin with no acne or spots; the picture still shows what the shot description
    asks for and the room and light stay the same as in the keyframe; the frames look like
    footage of a real phone camera, not a glitching render. Ignore all text and logos on the
    product, the packaging and the clothes: video models cannot draw small text, so never fail a
    clip because text changes or is garbled. Judge only what the frames show; frames are samples,
    so do not fail the clip for motion you cannot see.

    problem: empty when passed. Otherwise one or two short English sentences naming what is
    wrong and in which frame number (counting from 1), so a person can look at it.

    {{ _.role("user") }}
    Shot description: {{ shot_description }}

    Real product photos:
    {% for photo in product_photos %}
    {{ photo }}
    {% endfor %}

    Keyframe the clip starts from:
    {{ keyframe }}

    {% if characters %}
    Photos of the person (the same person must appear):
    {% for character in characters %}
    {{ character }}
    {% endfor %}
    {% endif %}

    Frames of the generated clip, in time order:
    {% for frame in clip_frames %}
    Frame {{ loop.index }}:
    {{ frame }}
    {% endfor %}

    {{ ctx.output_format }}
  "#
}
