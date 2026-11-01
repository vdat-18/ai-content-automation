// This helps use auto generate libraries you can use in the language of
// your choice. You can have multiple generators if you use multiple languages.
// Just ensure that the output_dir is different for each generator.
//
// One shared baml_src project backs four bounded-context BAML clients. Every
// generator below sees all functions/clients in this project, so each domain's
// generated baml_client includes types for the other domains too; only the
// functions used by that domain's adapters are actually called at runtime.
generator creative_target {
    output_type "python/pydantic"
    output_dir "../src/ai_content/domains/marketing/creative/adapters"
    version "0.226.2"
    default_client_mode async
}

generator creative_feedback_target {
    output_type "python/pydantic"
    output_dir "../src/ai_content/domains/marketing/creative_feedback/adapters"
    version "0.226.2"
    default_client_mode async
}

generator performance_decisions_target {
    output_type "python/pydantic"
    output_dir "../src/ai_content/domains/marketing/performance_decisions/adapters"
    version "0.226.2"
    default_client_mode async
}

generator research_screening_target {
    output_type "python/pydantic"
    output_dir "../src/ai_content/domains/marketing/research_crawler/adapters"
    version "0.226.2"
    default_client_mode async
}