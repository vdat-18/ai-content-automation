class ClipCheck {
  passed bool
  problem string
  category "face" | "product" | "skin" | "body" | "scene" | "other"
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
    frames from the clip in time order (the first near the start, the last near the end), the
    keyframe it was animated from, and the real product photos. Return JSON only, exactly matching
    the response schema.

    passed=true only when all of these hold:
    - Product: clearly visible in every frame, with the same shape, color, proportions, material
      and number of items as in the product photos and the keyframe; no melting, warping, splitting
      or growing; no object appears from nowhere or vanishes between frames.
    - Face (when photos of the person are given): the person in every frame is clearly the same
      person as in the photos and the keyframe (clothes may differ when the shot shows the product
      worn). Compare feature by feature: eye shape and spacing, eyebrows, nose, lips, jaw and chin,
      hairline and parting, skin tone. A merely similar or generic face, one whose features look
      changed, or one that drifts between frames fails. The only allowed difference is clearer skin:
      acne, spots and scars seen in the photos must NOT appear in the clip.
    - Life: a visible face shows real expression across the frames (a smile, raised eyebrows, eye
      movement), never a frozen, blank, mask-like face.
    - Body: hands and limbs look natural (no extra, missing, fused or bent-backwards fingers or
      arms) and well proportioned in every frame (realistic head to body ratio, normal limb length).
    - Head and body agree: in every frame compare where the face looks with where the chest faces.
      When the chest or the back of the shirt is turned more than about 60 degrees away from the
      camera while the face still looks straight into it, the neck is twisted beyond what is real
      and the clip fails; the head never turns all the way round.
    - Mirrors: a mirror or reflective surface shows the same person in the same pose, never another
      person, another pose or a back view while the front faces the camera; no second person or
      figure appears that is not in the keyframe.
    - Scene: the picture shows what the shot description asks for; the room and light stay as in
      the keyframe; the frames look like real phone-camera footage, not a glitching render.
    Ignore all text and logos on the product, packaging and clothes: video models cannot draw small
    text, so never fail a clip because text changes or is garbled. Judge only what the frames show;
    they are samples, so do not fail the clip for motion you cannot see.

    When the shot description says to keep the skin as in the photos, ignore every rule about
    clearer skin: the skin must match the photos, marks included.

    problem: empty when passed. Otherwise one or two short English sentences naming what is wrong
    and in which frame number (counting from 1).

    category: the kind of the main problem when passed is false, otherwise "other": "face" when the
    person does not look like the one in the photos, "product" for its shape, color, label, size or
    number, "skin" for skin marks or a waxy look, "body" for hands, limbs, proportions or a twisted
    neck, "scene" for the room, the light or a jump between shots, else "other".

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
