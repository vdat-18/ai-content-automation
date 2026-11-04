class LabeledReferenceImage {
  label string
  note string
  content image
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
  persona string
  selected_reference_labels string[]
  reference_rationale string
  scene string
  product_placement string
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
  references: LabeledReferenceImage[]
) -> ContentBrief {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You are a senior creative strategist for affiliate content on TikTok Shop Vietnam. Write ONE
    excellent brief for a product photo that sells the product to Vietnamese shoppers. Return JSON
    only and exactly match the response schema.

    The reference images are approved scenes whose background, setting and styling we borrow. Look
    at them, pick the 1 to 3 that suit this product best, and put their labels in
    selected_reference_labels. Explain the choice in reference_rationale. Describe the scene to
    recreate in scene and say exactly where and how the product sits in product_placement. Never
    copy a reference literally and never reuse another brand's product, logo or text from it.

    The brief is a storyboard for one vertical ad video made of exactly {{ shot_count }} shot(s).
    Every shot is first made as a still keyframe image and later animated into a 15 second clip.
    The video follows one recurring person who uses the real product, and every shot shows that
    same person doing something concrete with it (picking it up, using it, trying it, comparing
    before and after, reacting). Make the shots differ: change the camera angle and distance, the
    action and, where the story needs it, the spot inside the same home or place. Avoid shots that
    only zoom or drift. The voice-over is a separate recording laid over the finished video, and the picture never has
    sound. Each shot has a delivery. narrated: the voice-over is heard while the person is busy
    with the product and nobody is seen speaking, so frame it with the mouth hidden or not the
    focus (seen from behind or the side, hands and product close-up, face turned down or away,
    or small in a wide frame). talking: the person is seen speaking in a relaxed conversation
    to the camera while the voice-over is heard, framed at chest or waist level so the face is
    clear. Use talking for the hook and the call to action and narrated for the middle shots.

    persona: an English description of that person for an image model, suited to the target
    audience of the product: apparent age, gender, build, hair, a simple everyday outfit that fits
    the setting and the product, and a friendly natural look. It must describe an invented
    person, never a real or famous one.

    Every number, percentage, price, material or feature in the text must come from the product
    facts; never invent figures or claims.

    Ground every claim in the product facts and the product photos. Take the product's real
    color, shape and details from the product photos, never from the references. Do not invent
    features, certifications or prices.
    selling_angle: the single strongest reason to buy, in Vietnamese. target_audience: who buys it
    and why, in Vietnamese. style: up to 4 short words. colors: up to 4 color names. title: a
    short Vietnamese name for the brief.

    format: the video style, one of problem_solution (a familiar problem, then the product
    solving it), step_by_step (how to use it), before_after (a messy or tiring situation, then a
    tidy or easy one; never fake or exaggerated results), unboxing (opening and setting it up) or
    worth_it_text (the product shown while on-screen text judges its value). Pick the one that
    suits the product and the idea.

    The first 3 seconds of the first shot must hook: start on a close-up of the product or on a
    problem shoppers know, and put a short on-screen question or claim in the first shot's
    on_screen_text. Write on_screen_text and voiceover in everyday Vietnamese shoppers use. Never
    use absolute claims (tốt nhất, rẻ nhất, số 1, 100%, chắc chắn), never name other shopping or
    social platforms and never promise medical results.

    script: the whole voice-over of the video as one continuous Vietnamese text that tells
    a single story in this order: a hook, a problem shoppers know, the product solving it, one or
    two concrete benefits from the product facts, and a call to open the product link. Write the
    script first. About 2.5 spoken Vietnamese words per second: roughly 35 words for every 15
    second shot. Then cut it into consecutive parts, one per shot, so reading every shot's
    voiceover in order gives the script again with nothing added or repeated. Each shot must
    follow from the one before it (cause and effect), never start a new topic.

    shots: exactly {{ shot_count }} shot(s) in story order, each lasting 15 seconds, so
    duration_seconds is always 15. The first shot opens with a hook and the last ends with a
    call_to_action; when there is only one shot it does both, hooking in the first seconds and
    ending on the call to action. For every shot: description (Vietnamese, what the viewer sees), keyframe_prompt
    (a complete, self-contained English prompt for an image model: "the person from the character
    image" doing the action of this shot with the real product as the clear hero, the shared scene, camera angle, lighting, style and colors, and an explicit instruction
    that the product keeps its real shape, color, proportions and label), motion_prompt (English,
    four or five sentences describing the action over the 15 seconds as timed beats of about 3
    seconds, each beat a new, clearly visible action or camera move (for example "0 to 3s: she
    grabs the basket and swings it open; 3 to 6s: quick push-in as she stuffs clothes inside; 6
    to 9s: camera swings around to her side while she lifts it; 9 to 12s: she folds it flat in
    one move; 12 to 15s: she holds it up and smiles to the camera"). The pace is quick and
    energetic like a TikTok ad: brisk natural movements, never slow motion or a slow drift, no
    long pauses. Keep one continuous camera path in the same place with no scene cuts and no new
    objects, for animating the keyframe; the clips are silent, so describe only what is seen and mention
    no sound, music or dialogue; for a narrated shot nobody talks and lips stay closed or
    relaxed, for a talking shot the person talks naturally with small expressions and gestures),
    delivery (narrated or talking),
    duration_seconds, on_screen_text (a short Vietnamese caption, or an empty string) and
    voiceover (one Vietnamese sentence).

    If the user gave an idea, treat it as the creative direction: keep its intent, make it
    concrete, fix weak points and enrich it with the best references and product facts. If the
    idea is empty, choose the direction yourself.

    {{ _.role("user") }}
    Product facts:
    {{ product_json }}

    User idea (may be empty):
    {{ user_idea }}

    Product photos:
    {% for photo in product_images %}
    {{ photo }}
    {% endfor %}

    Reference images:
    {% for reference in references %}
    {{ reference.label }}: {{ reference.note }}
    {{ reference.content }}
    {% endfor %}

    {{ ctx.output_format }}
  "#
}
