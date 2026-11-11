class VoicePick {
  gender string
  voice string
  reason string
}

function PickVoice(brief_json: string, voices_json: string, person_photos: image[]) -> VoicePick {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You choose the voice-over voice for a short vertical Vietnamese TikTok product ad. Return
    JSON only, exactly matching the response schema.

    gender: the gender of the person who appears in the ad, "male" or "female", read from the
    photos of the person. When no photo is given, read it from the brief; when the brief gives
    no person, use "unknown".

    voice: the id of exactly one voice from the voice list. When gender is "male" or "female"
    the voice must have that gender. Choose the voice whose description best fits the product,
    the audience and the tone of the script.

    reason: one short English sentence saying why this voice fits.

    {{ _.role("user") }}
    Brief:
    {{ brief_json }}

    Voices:
    {{ voices_json }}

    {% if person_photos %}
    Photos of the person in the ad:
    {% for photo in person_photos %}
    {{ photo }}
    {% endfor %}
    {% endif %}

    {{ ctx.output_format }}
  "#
}
