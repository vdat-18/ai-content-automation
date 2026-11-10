class StoryboardProblem {
  where string
  problem string
  fix string
}

class StoryboardReview {
  passed bool
  problems StoryboardProblem[]
}

function ReviewStoryboard(product_json: string, brief_json: string, rules: string) -> StoryboardReview {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You are a strict editor who reviews the storyboard of a short vertical product ad before any
    image or video is paid for. Return JSON only, exactly matching the response schema.

    Judge the storyboard as a whole and each shot. It fails when any rule listed under "Rules"
    is broken (count words when a rule gives word counts), when the story has no clear flow
    from hook to product benefit to call to action, or when it contradicts the product facts
    (size, use, features) or invents claims.

    problems: empty when passed. Otherwise one entry per problem. where: the shot number and the
    field, for example "shot 3 motion_prompt". problem: what is wrong, quoting the words or beats
    concerned. fix: the concrete replacement text or the exact change to make. List a problem only
    when you can give its fix. After finding one problem, look for the same mistake in the other
    shots and list each place. Do not repeat a problem the storyboard does not have.

    {{ _.role("user") }}
    Product facts:
    {{ product_json }}

    Rules:
    {{ rules }}

    Storyboard:
    {{ brief_json }}

    {{ ctx.output_format }}
  "#
}
