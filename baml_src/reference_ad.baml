class AdStructure {
  rules string[]
}

function AnalyzeAdStructure(frames: image[], frame_times: string, cut_times: string, voice_pace: string) -> AdStructure {
  client OrchestrationModel
  prompt #"
    {{ _.role("system") }}
    You study a short vertical TikTok ad that sells well and describe how it is built, so a
    scriptwriter can build a different ad the same way. Return JSON only, exactly matching the
    response schema.

    You get frames sampled evenly through the video in time order, the time of each frame in
    seconds, the times where the picture was measured to cut to a new shot, and measures of the
    voice: when it starts and ends, words per second, the longest pause between words, and the
    length of the video. The measures come from a speech recognizer, so singing in the music can
    count as voice. {"voice": "none"} means the video has no spoken words.

    rules: 3 to 6 rules, each one short English instruction written for a scriptwriter, about the
    structure only: what kind of hook opens the video and what the first 2 seconds show; how many
    shots there are and how fast they cut; where on-screen text sits, how big it is and how many
    words a line has; how the video ends (call to action, product close-up); when the voice starts, how fast it speaks
    and how long a pause may be, stated with the measured numbers. Each rule must work
    for any product. Never mention a brand, product name, person, logo or any words said or
    written in the ad, and never describe the product itself. You only see still frames, so state
    pace as what the measured cuts show and do not claim motion you cannot see.

    {{ _.role("user") }}
    Frame times in seconds: {{ frame_times }}
    Measured cut times in seconds: {{ cut_times }}
    Measured voice: {{ voice_pace }}

    Frames in time order:
    {% for frame in frames %}
    {{ frame }}
    {% endfor %}

    {{ ctx.output_format }}
  "#
}
