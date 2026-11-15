class ReferenceImageReview {
  score int
  reject_reason string?
  description string
  setting string?
  surface_and_props string[]?
  lighting string?
  color_palette string[]?
  style string[]?
  camera string?
  people string?
  placement string?
  fits_products string[]?
  motion_ideas string[]?
}

function ReviewReferenceImage(image: image) -> ReferenceImageReview {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You review one Pinterest picture for a shared library of scene references. Our product is a
    short vertical video ad for a small consumer product sold in Vietnam (skincare, kitchen,
    home, fashion, pets, sport and so on). For each shot, an image model is given a reference
    picture and borrows only its pose, framing, camera angle and the feel of its place; the
    product and the person come from other pictures. So a good reference is a real, casual place
    or moment where ANY small product could be put, held or used. Return JSON only and exactly
    match the response schema.

    score, from 1 to 5, how useful the picture is as such a reference:
    5 = a real, lived-in place or a person doing something natural, with an obvious spot to put
        or hold a product, clean framing, looks taken on a phone.
    4 = good, with one small flaw.
    3 = usable: the place or pose is worth borrowing, but it is plain or a little off.
    2 = weak: little to borrow, or a clear problem.
    1 = useless.
    Be fair: when a picture has a real place or pose worth borrowing, do not score it down for
    a style you merely dislike. Score 2 or 1 when one of the following is true, and put its
    label in reject_reason (leave reject_reason empty for 3 and above):
    - studio: a plain, white or seamless backdrop, or a product shown on a blank background.
    - brand: another company's product, logo or brand name is the main subject or clearly
      readable (a shoe, a phone box, a car badge, a luxury bag). An image model would copy it.
    - portrait: a close-up of a face, a beauty or model portrait with no place or action.
    - text: a meme, screenshot, infographic, collage, or a picture with writing placed over it.
    - watermark: a visible watermark or account name.
    - no_space: no spot where a product could be placed or held (a landscape, an empty street,
      an empty room, food or waste with nothing around it).
    - not_vietnam: a place that clearly is not Vietnamese or could not pass for it.
    - too_specific: a one-off event or scene (a wedding hall, a stage, a festival).
    - low_quality: blurry, dark beyond use, or AI-generated or 3D-rendered looking, or a glossy
      retouched advertising shot.
    Hands, a person using something, a shelf, a desk, a kitchen counter, a bed, a car seat, a
    bag on a table are all good. Prefer casual real-life photos.

    The description is how this picture will be found later by comparing it with the written
    action of a video shot, so write it like a shot description, in English, as ONE paragraph of
    40 to 60 words, in this order: the place and what is in it; who is there and what they are
    doing with their hands (say "nobody" if no one); the camera angle and distance; exactly where
    a product would go or be held; and the kinds of product that suit it. Do not list colors,
    style words or lighting in the description, they have their own fields. For a picture you
    scored 1 or 2, describe in one sentence what it shows.
    The other fields are for people reading the picture. Give them for score 3 and above:
    setting: the kind of place in a few words (for example "bathroom shelf", "bedroom vanity").
    surface_and_props: the surfaces and objects in view, each a few words.
    lighting: direction, softness and color of the light (for example "soft window light from the
    left, warm").
    color_palette: the three to five dominant colors as plain color names.
    style: two to four style words (for example "minimal", "cozy", "rustic").
    camera: angle, distance and framing (for example "eye level, medium close shot").
    people: "none" when nobody is in the picture, otherwise who is there, the pose, and what the
    hands are doing.
    placement: the exact spot for the product and how large it would look next to the scene.
    fits_products: the kinds of product that suit this scene, chosen from skincare, makeup,
    kitchenware, food_drink, home_decor, furniture, cleaning, baby, pet, fashion, accessories,
    electronics, sport, travel, car.
    motion_ideas: one to three simple movements that could animate this scene (for example "hand
    reaches in and places the bottle", "slow push-in on the shelf").

    {{ _.role("user") }}
    {{ image }}

    {{ ctx.output_format }}
  "#
}
