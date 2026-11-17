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
    short vertical video ad for a small consumer product sold in Vietnam (skincare, kitchen, home,
    fashion, pets, sport and so on). For each shot an image model borrows from a reference only its
    pose, framing, camera angle and the feel of its place; the product and the person come from
    other pictures. So a good reference is a real, casual place or moment where ANY small product
    could be put, held or used. Return JSON only, exactly matching the response schema.

    score, from 1 to 5, how useful the picture is as such a reference:
    5 = a real, lived-in place or a person doing something natural, with an obvious spot to put or
        hold a product, clean framing, looks taken on a phone.
    4 = good, with one small flaw.
    3 = usable: the place or pose is worth borrowing, but plain or a little off.
    2 = weak: little to borrow, or a clear problem.
    1 = useless.
    Be fair: do not score down a picture with a real place or pose worth borrowing for a style you
    merely dislike. Score 2 or 1 when one of these is true and put its label in reject_reason
    (empty for 3 and above):
    - studio: plain, white or seamless backdrop, or a product on a blank background.
    - brand: another company's product, logo or brand name is the main subject or clearly readable
      (a shoe, a phone box, a car badge, a luxury bag); an image model would copy it.
    - portrait: a close-up of a face, a beauty or model portrait with no place or action.
    - text: a meme, screenshot, infographic, collage, or a picture with writing over it.
    - watermark: a visible watermark or account name.
    - no_space: no spot to place or hold a product (a landscape, an empty street or room, food or
      waste with nothing around it).
    - not_vietnam: a place that clearly is not Vietnamese or could not pass for it.
    - too_specific: a one-off event or scene (a wedding hall, a stage, a festival).
    - low_quality: blurry, too dark, AI-generated or 3D-rendered looking, or a glossy retouched
      advertising shot.
    Hands, a person using something, a shelf, a desk, a kitchen counter, a bed, a car seat, a bag on
    a table are all good. Prefer casual real-life photos.

    description: how this picture will be found later, by comparing it with the written action of a
    video shot, so write it like a shot description, in English, as ONE paragraph of 40 to 60 words
    in this order: the place and what is in it; who is there and what they do with their hands
    ("nobody" if no one); the camera angle and distance; exactly where a product would go or be
    held; the kinds of product that suit it. No colors, style words or lighting here, they have
    their own fields. For a picture scored 1 or 2, one sentence on what it shows.

    The other fields are for people reading the picture; give them for score 3 and above:
    - setting: the kind of place in a few words ("bathroom shelf", "bedroom vanity").
    - surface_and_props: the surfaces and objects in view, each a few words.
    - lighting: direction, softness and color ("soft window light from the left, warm").
    - color_palette: three to five dominant colors as plain names.
    - style: two to four style words ("minimal", "cozy", "rustic").
    - camera: angle, distance and framing ("eye level, medium close shot").
    - people: "none" when nobody is in the picture, otherwise who, the pose and what the hands do.
    - placement: the exact spot for the product and how large it would look next to the scene.
    - fits_products: kinds of product that suit the scene, from skincare, makeup, kitchenware,
      food_drink, home_decor, furniture, cleaning, baby, pet, fashion, accessories, electronics,
      sport, travel, car.
    - motion_ideas: one to three simple movements that could animate the scene ("hand reaches in
      and places the bottle", "slow push-in on the shelf").

    {{ _.role("user") }}
    {{ image }}

    {{ ctx.output_format }}
  "#
}
