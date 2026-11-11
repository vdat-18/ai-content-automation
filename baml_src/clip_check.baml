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
    the person in every frame is clearly the same person as in the photos and the keyframe
    (the clothes may differ when the shot shows the product worn). Be strict about the face:
    compare it with the photos feature by feature (eye shape and spacing, eyebrows, nose,
    lips, jaw and chin, hairline and hair parting, skin tone). A face that is only similar, a
    generic handsome face, or one that looks smoothed, idealised or like a different man or
    woman fails, and so does a face that drifts from the photos between frames; when the
    person's face is visible, it must also be alive: across the frames it shows real
    expression (a smile, raised eyebrows, eye movement, a change of look) and is never a
    frozen, blank, mask-like face that stays the same in every frame; hands and limbs look natural with no extra, missing,
    fused or bent-backwards fingers or arms, and the body stays well proportioned in every frame
    (a realistic head to body ratio and normal limb length, never stretched or distorted) and the
    face keeps clear skin with no acne or spots; the head and body always agree: in every
    frame compare where the face looks with where the chest faces; when the chest, or the back of
    the shirt, is turned away from the camera by more than about 60 degrees while the face still
    looks straight into the camera, the neck is twisted further than a real neck can go, so the
    clip fails; the person never turns the head all the way round;
    a mirror or other reflective surface that appears shows the same person in the same pose,
    never another person, a different pose or a body seen from the back while the front faces
    the camera, and no second person or figure appears that is not in the keyframe; the picture still shows what the shot description
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
