class ReferenceCandidate {
  label string
  note string
  photo image
}

class ShotReferenceChoice {
  choice string
}

function ChooseShotReference(
  product_json: string,
  shot_json: string,
  candidates: ReferenceCandidate[]
) -> ShotReferenceChoice {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You pick the reference photo that best helps an image model create ONE shot of a short
    vertical ad. The reference lends only its pose, framing, camera angle and the feel of its
    place; the product and the person come from other pictures. Return JSON only, exactly
    matching the response schema.

    Look at each candidate photo, not only its note. Choose the label of the one that fits what
    this shot shows: the same kind of action, framing and distance, a place that suits the
    product, and a casual real-life look. Return "none" when no candidate really fits the shot
    (a wrong reference is worse than none).

    {{ _.role("user") }}
    Product facts:
    {{ product_json }}

    Shot:
    {{ shot_json }}

    Candidates:
    {% for candidate in candidates %}
    {{ candidate.label }}: {{ candidate.note }}
    {{ candidate.photo }}
    {% endfor %}

    {{ ctx.output_format }}
  "#
}
