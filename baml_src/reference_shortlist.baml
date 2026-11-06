class ReferenceShortlist {
  labels string[]
}

function ShortlistReferences(
  product_json: string,
  user_idea: string,
  references: LabeledReference[],
  keep: int
) -> ReferenceShortlist {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You choose which reference scenes are worth considering for a short vertical ad of one
    product. Each reference is a real photo that someone has already described in words. Return
    JSON only, exactly matching the response schema.

    Choose at most {{ keep }} references and return their labels, best first. Prefer scenes where
    this product, at its real size, would look natural and where its use could be shown; prefer
    casual real-life scenes; and make the choice varied (different places, light and camera) so
    the writer has real alternatives. Skip scenes that do not suit the product. Return only
    labels that appear in the list.

    {{ _.role("user") }}
    Product facts:
    {{ product_json }}

    Idea from the user (may be empty):
    {{ user_idea }}

    References:
    {% for reference in references %}
    {{ reference.label }}: {{ reference.note }}
    {% endfor %}

    {{ ctx.output_format }}
  "#
}
