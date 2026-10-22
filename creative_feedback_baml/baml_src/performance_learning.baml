class AdsDiagnosisResult {
  observations string[]
  hypotheses string[]
  confounders string[]
  uncertainty string
  evidence_refs string[]
}

enum LearningRecommendationAction {
  REQUEST_NEW_CREATIVE
  RETEST_CREATIVE
  WAIT_FOR_MORE_DATA
  NO_ACTION
  MANUAL_REVIEW
}

class LearningProposalResult {
  priority int
  recommended_action LearningRecommendationAction
  hypothesis string
  experiment string
  success_signal string
  evidence_refs string[]
  uncertainty string
}

class CreativeLessonResult {
  proposal LearningProposalResult?
}

function DiagnoseAdsOutcome(
  instructions: string,
  evidence_json: string
) -> AdsDiagnosisResult {
  client LocalMarketingLLM
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    Use only the supplied typed evidence. Keep observations, hypotheses and
    confounders separate. Do not calculate metrics or claim causality. Every
    evidence reference must occur verbatim in the input.
    </runtime_contract>

    {{ _.role("user") }}
    <evidence_json>
    {{ evidence_json }}
    </evidence_json>

    {{ ctx.output_format }}
  "#
}

function SynthesizeCreativeLesson(
  instructions: string,
  evidence_json: string,
  diagnosis_json: string
) -> CreativeLessonResult {
  client LocalMarketingLLM
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    Use only the supplied evidence and diagnosis. Preserve the deterministic
    recommendation exactly. Return no proposal when that recommendation is not
    actionable. Every evidence reference must occur verbatim in the input.
    </runtime_contract>

    {{ _.role("user") }}
    <evidence_json>
    {{ evidence_json }}
    </evidence_json>

    <diagnosis_json>
    {{ diagnosis_json }}
    </diagnosis_json>

    {{ ctx.output_format }}
  "#
}
