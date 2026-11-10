class CuratedRule {
  title string
  content string
  replaces string[]
}

function CurateKnowledge(new_rule: string, existing_rules: string) -> CuratedRule {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You keep the rulebook that guides an AI which makes vertical product ad images and videos.
    A reviewer just approved a new rule that came from feedback on a generated image or video.
    Rewrite it so the rulebook stays short, clear and free of repeats. Return JSON only, exactly
    matching the response schema.

    title: a short English name of the rule.
    content: English, in the form "WHEN: <situation>. DO: <what to do>. DO NOT: <what to avoid>.",
    concrete and checkable by looking at a picture, with nothing specific to one product or one
    person. Keep every fact from the new rule; drop chatter.
    replaces: the ids of existing rules that say the same thing as the new rule or are
    contradicted by it. Fold whatever is still useful in them into content. Never list a rule
    that covers something different. Use an empty list when nothing is replaced.

    {{ _.role("user") }}
    New rule:
    {{ new_rule }}

    Existing rules (id: title: content):
    {{ existing_rules }}

    {{ ctx.output_format }}
  "#
}
