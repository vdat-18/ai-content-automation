client<llm> LocalMarketingLLM {
  provider "openai-generic"
  options {
    base_url env.LOCAL_LLM_BASE_URL
    model env.LOCAL_LLM_MODEL
    api_key env.LOCAL_LLM_API_KEY
    temperature 0
    max_tokens 2400
  }
}
