// Default client for Marketing LLM tasks; the Python adapters always override
// this via a runtime ClientRegistry pointed at the configured third-party API.
client<llm> MarketingLLM {
  provider "openai-generic"
  options {
    base_url env.MARKETING_LLM_BASE_URL
    model env.MARKETING_LLM_MODEL
    api_key env.MARKETING_LLM_API_KEY
    temperature 0
    max_tokens 2000
  }
}

// Dedicated client for creative_feedback tasks, which need a larger token budget.
client<llm> CreativeFeedbackLLM {
  provider "openai-generic"
  options {
    base_url env.MARKETING_LLM_BASE_URL
    model env.MARKETING_LLM_MODEL
    api_key env.MARKETING_LLM_API_KEY
    temperature 0
    max_tokens 2400
  }
}

// Provider-neutral semantic orchestration client. Provider and model are runtime values.
client<llm> OrchestrationModel {
  provider "openai-generic"
  options {
    base_url env.ORCHESTRATION_MODEL_BASE_URL
    model env.ORCHESTRATION_MODEL_NAME
    api_key env.ORCHESTRATION_MODEL_API_KEY
    temperature 0
    max_tokens 3000
  }
}
