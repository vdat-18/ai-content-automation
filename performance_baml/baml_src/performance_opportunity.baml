enum OpportunityCategory {
  SCALE_WINNER
  REFRESH_FATIGUE
  TEST_NEW_ANGLE
  FILL_CREATIVE_GAP
  INVESTIGATE_ANOMALY
  DEFER_INSUFFICIENT_EVIDENCE
  STOP_OR_DEPRIORITIZE
  BLOCKED_CONFLICT
}

class CreativeOpportunityResult {
  category OpportunityCategory
  priority int
  rationale string
  evidence_refs string[]
  uncertainty string
  counterargument string
  hypothesis string
  experiment string
  success_signal string
}

function AnalyzeCreativeOpportunity(
  instructions: string,
  evidence_json: string
) -> CreativeOpportunityResult {
  client LocalMarketingLLM
  prompt #"
    {{ _.role("system") }}
    {{ instructions }}

    <runtime_contract>
    Analyze only the supplied typed evidence. Do not calculate new business
    metrics or invent missing facts. Every evidence reference in the output must
    occur verbatim in the input. Return uncertainty explicitly and choose a defer
    or blocked category when evidence is unavailable or conflicting.
    </runtime_contract>

    {{ _.role("user") }}
    <evidence_json>
    {{ evidence_json }}
    </evidence_json>

    {{ ctx.output_format }}
  "#
}
