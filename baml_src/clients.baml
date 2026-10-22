// Local-first client for Marketing LLM tasks.
client<llm> LocalMarketingLLM {
  provider "openai-generic"
  options {
    base_url env.LOCAL_LLM_BASE_URL
    model env.LOCAL_LLM_MODEL
    api_key env.LOCAL_LLM_API_KEY
    temperature 0
    max_tokens 2000
  }
}

client<llm> LocalMarketingFallbackLLM {
  provider "openai-generic"
  options {
    base_url env.LOCAL_LLM_BASE_URL
    model env.LOCAL_LLM_FALLBACK_MODEL
    api_key env.LOCAL_LLM_API_KEY
    temperature 0
    max_tokens 2000
  }
}

client<llm> LocalMarketingLLMWithFallback {
  provider fallback
  options {
    strategy [
      LocalMarketingLLM
      LocalMarketingFallbackLLM
    ]
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
