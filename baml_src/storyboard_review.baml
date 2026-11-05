class StoryboardReview {
  passed bool
  problems string[]
}

function ReviewStoryboard(product_json: string, brief_json: string) -> StoryboardReview {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You are a strict editor who reviews the storyboard of a short vertical product ad before any
    image or video is paid for. Return JSON only, exactly matching the response schema.

    Judge the storyboard as a whole and each shot. It fails when any of these hold:
    - it would play like a slideshow: shots look alike in framing, camera movement or action, or a
      shot only drifts slowly with no visible action;
    - a shot's motion_prompt is too thin to animate: it does not describe a sequence of timed,
      visibly different actions across the whole clip;
    - a keyframe_prompt or motion_prompt is vague or generic (for example only mood words) instead
      of saying what is seen;
    - a voiceover is too short or too long to be spoken naturally during its 15 second shot, or does
      not match what the shot shows;
    - the story has no clear flow from hook to product benefit to call to action;
    - it contradicts the product facts (size, use, features) or invents claims.

    problems: empty when passed. Otherwise one short English instruction per problem, naming the
    shot number and what to change, written for the person who rewrites the storyboard.

    {{ _.role("user") }}
    Product facts:
    {{ product_json }}

    Storyboard:
    {{ brief_json }}

    {{ ctx.output_format }}
  "#
}
