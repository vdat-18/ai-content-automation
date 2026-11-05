class VideoReview {
  passed bool
  problems string[]
}

function ReviewFinalVideo(
  product_json: string,
  storyboard_json: string,
  product_photos: image[],
  frames: image[]
) -> VideoReview {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You are a strict editor who watches a finished vertical product ad before it is posted. You
    cannot play it; you see evenly spaced frames from it, in time order. Return JSON only, exactly
    matching the response schema.

    passed=true only when all of these hold: the product in every frame where it appears is clearly
    the real product from the photos, with the same shape, color, label and size next to the
    person and the room; the same person, outfit and room continue through the video; the frames
    follow the storyboard in order; the video does not look like a slideshow, so the frames differ
    in framing and action; and nothing is warped, covered by text, or shows invented text or logos.

    problems: empty when passed. Otherwise one short English line per problem, naming the
    approximate position (for example "around frame 5") and what is wrong.

    {{ _.role("user") }}
    Product facts:
    {{ product_json }}

    Storyboard:
    {{ storyboard_json }}

    Real product photos:
    {% for photo in product_photos %}
    {{ photo }}
    {% endfor %}

    Frames of the finished video, in time order:
    {% for frame in frames %}
    Frame {{ loop.index }}:
    {{ frame }}
    {% endfor %}

    {{ ctx.output_format }}
  "#
}
