// Dedicated Terra boundary for Media Lab intent routing and visual prompt enrichment.
client<llm> MediaLabTerra {
  provider "openai-generic"
  options {
    base_url env.MEDIA_LAB_TERRA_BASE_URL
    model env.MEDIA_LAB_TERRA_MODEL
    api_key env.MEDIA_LAB_TERRA_API_KEY
    temperature 0
    max_tokens 2000
  }
}
