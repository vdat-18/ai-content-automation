class LabeledReference {
  label string
  note string
}

class StoryboardShot {
  role "hook" | "problem" | "demo" | "benefit" | "call_to_action"
  description string
  keyframe_prompt string
  motion_prompt string
  delivery "narrated" | "talking"
  duration_seconds int
  on_screen_text string
  voiceover string
}

class ContentBrief {
  title string
  format "problem_solution" | "step_by_step" | "before_after" | "unboxing" | "worth_it_text"
  script string
  product_photo_numbers int[]
  scene string
  product_placement string
  product_variant string
  product_size string
  selling_angle string
  target_audience string
  style string[]
  colors string[]
  shots StoryboardShot[]
}

function DraftContentBrief(
  product_json: string,
  user_idea: string,
  shot_count: int,
  product_images: image[],
  with_person: bool,
  person_images: image[],
  rules: string
) -> ContentBrief {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You are a senior creative strategist for affiliate content on TikTok Shop Vietnam. Write ONE
    excellent brief for a product photo that sells the product to Vietnamese shoppers. Return JSON
    only and exactly match the response schema.

    Describe in scene the one lived-in place where the whole video happens, suited to the target
    audience, and say exactly where and how the product sits in product_placement. Reference photos
    are matched to each shot later, so write every shot's keyframe_prompt on its own: the action,
    the framing, the distance and the camera angle.

    The product photos are numbered. Put in product_photo_numbers the numbers of all the photos
    that show the product, most useful first: the main photo, other angles and photos that show
    the size or real use. A photo that is a collage or carries text is fine when it shows the
    product or real facts such as a size chart. Read sizes and materials from all photos,
    including size charts, and use them in product_size and the prompts.

    The product may come in several versions (colors, scents, sizes). Pick exactly ONE version
    to show in the whole video: the one in the first photos or the best seller. Describe it in
    product_variant in English (the color, finish, shape and the name on the label as it looks in
    the photos). Every prompt then shows only that version and names its color; never show or
    mention the other versions.

    The brief is a storyboard for one vertical ad video made of exactly {{ shot_count }} shot(s).
    Every shot is first made as a still keyframe image and later animated into a 15 second clip.
    {% if with_person %}
    The video follows one recurring person, the one in the person photos below, who uses the real
    product, and every shot shows that same person doing something concrete with it (picking it
    up, using it, trying it, comparing before and after, reacting). Write actions, outfit and
    setting that suit the person you see in the photos. The product is the star: it is clearly
    visible and recognisable in every shot, from the first frame to the last, held, worn or placed
    in frame while the person acts (a close-up of skin or a face still has the product in the
    picture).
    {% else %}
    The video shows no person: no face and no body in any shot, only the real product, the place
    and, when the action needs it, hands. The product is the star: it is clearly visible and
    recognisable in every shot, from the first frame to the last, placed, held by hands or shown
    in use.
    {% endif %}
    The voice-over is a separate recording laid over the finished video, and the picture never has
    sound. Each shot has a delivery.
    {% if with_person %}
    narrated: the voice-over is heard while the person is busy
    with the product and nobody is seen speaking, so frame it with the mouth hidden or not the
    focus (seen from behind or the side, hands and product close-up, face turned down or away,
    or small in a wide frame). talking: the person is seen speaking in a relaxed conversation
    to the camera while the voice-over is heard, framed at chest or waist level so the face is
    clear. Use talking for the hook and the call to action and narrated for the middle shots.
    {% else %}
    Every shot is narrated: the voice-over is heard while the picture shows only the product, the
    place and hands, and nobody is seen speaking. Never use talking.
    {% endif %}

    Ground every claim in the product facts and the product photos. Take the product's real
    color, shape and details from the product photos, never from the references. Do not invent
    features, certifications or prices.
    product_size: the real size of the product in English, worked out from the title, the
    attributes and the photos (for example "about 40 x 40 x 60 cm, knee height on a standing adult,
    about as tall as a seated adult's chest"), written so the scale against a person and the room
    is clear. selling_angle: the single strongest reason to buy, in Vietnamese. target_audience: who buys it
    and why, in Vietnamese. style: up to 4 short words. colors: up to 4 color names. title: a
    short Vietnamese name for the brief.

    format: the video style, one of problem_solution, step_by_step, before_after, unboxing or
    worth_it_text.

    Write on_screen_text and voiceover in everyday Vietnamese shoppers use.

    script: the whole voice-over of the video as one continuous Vietnamese text, written first and
    then cut into consecutive parts, one per shot, so the voiceovers in order give the script again.

    shots: exactly {{ shot_count }} shot(s) in story order, each lasting 15 seconds, so
    duration_seconds is always 15. The first shot opens with a hook and the last ends with a
    call_to_action; when there is only one shot it does both, hooking in the first seconds and
    ending on the call to action. For every shot: description (Vietnamese, what the viewer sees), keyframe_prompt
    (a complete, self-contained English prompt for an image model: {% if with_person %}"the person from the character
    image" (never describe their age, face, hair, skin or clothes; the character image gives them) doing the action of this shot{% else %}the action of this shot with no person in the picture (hands are fine, no face, no body){% endif %} with the real product as the clear hero, the shared scene, camera angle, lighting, style and colors, and an explicit instruction
    that the product, in the version of product_variant, keeps its real shape, color, proportions and label, and that it keeps its
    real size from product_size next to the person and the room, never enlarged or shrunk; follow the rules for how a keyframe_prompt is written),
    motion_prompt (English, for animating the keyframe: describe only motion, because the keyframe
    already shows how everything looks; follow the rules for how it is written),
    delivery (narrated or talking),
    duration_seconds, on_screen_text (a short Vietnamese caption, or an empty string) and
    voiceover (one Vietnamese sentence).

    If the user gave an idea, treat it as the creative direction: keep its intent, make it
    concrete, fix weak points and enrich it with the product facts. If the
    idea is empty, choose the direction yourself.

    {{ _.role("user") }}
    Product facts:
    {{ product_json }}

    User idea (may be empty):
    {{ user_idea }}

    {% if rules %}
    Approved rules from the team's knowledge base (follow them in every shot):
    {{ rules }}
    {% endif %}

    {% if with_person %}
    Person photos (the same real person, shown in every shot):
    {% for photo in person_images %}
    {{ photo }}
    {% endfor %}
    {% endif %}

    Product photos:
    {% for photo in product_images %}
    Photo {{ loop.index }}:
    {{ photo }}
    {% endfor %}

    {{ ctx.output_format }}
  "#
}
