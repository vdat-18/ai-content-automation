from pathlib import Path

from ai_content.domains.marketing.creative.config.preparation import (
    load_preparation_config,
)


def test_creative_automation_worker_concurrency_is_bounded_by_configuration(
    project_root: Path,
) -> None:
    compose = (project_root / "deploy/compose.yaml").read_text(encoding="utf-8")
    environment = (project_root / "deploy/.env.example").read_text(encoding="utf-8")

    assert (
        "AIC_AI_CREATIVE_AUTOMATION_MAX_CONCURRENCY: "
        "${AIC_AI_CREATIVE_AUTOMATION_MAX_CONCURRENCY:-10}"
    ) in compose
    assert "--concurrency=${AIC_AI_CREATIVE_AUTOMATION_MAX_CONCURRENCY:-10}" in compose
    assert "AIC_AI_CREATIVE_AUTOMATION_MAX_CONCURRENCY=3" in environment


def test_creative_orchestration_runtime_configuration_is_available_to_api_and_worker(
    project_root: Path,
) -> None:
    compose = (project_root / "deploy/compose.yaml").read_text(encoding="utf-8")
    environment = (project_root / "deploy/.env.example").read_text(encoding="utf-8")

    assert (
        "AIC_AI_ORCHESTRATION_CONFIG: "
        "${AIC_AI_ORCHESTRATION_CONFIG:-/app/config/orchestration/nine-router.example.json}"
    ) in compose
    assert (
        "AIC_AI_ORCHESTRATION_CONFIG=/app/config/orchestration/nine-router.example.json"
        in environment
    )
    assert (
        "AIC_AI_PREPARATION_CONFIG: "
        "${AIC_AI_PREPARATION_CONFIG:-/app/config/preparation/nine-router.example.json}"
    ) in compose
    assert (
        "AIC_AI_PREPARATION_CONFIG=/app/config/preparation/nine-router.example.json"
        in environment
    )
    preparation = load_preparation_config(
        project_root / "config/preparation/nine-router.example.json"
    )
    assert preparation.backend == "baml"
    assert preparation.api_key_env == "ROUTER_API_KEY"
    assert preparation.fallback_model is None
    assert "ROUTER_API_KEY=" in environment


def test_research_navigation_and_analysis_are_available_to_api_and_worker(
    project_root: Path,
) -> None:
    compose = (project_root / "deploy/compose.yaml").read_text(encoding="utf-8")
    environment = (project_root / "deploy/.env.example").read_text(encoding="utf-8")

    assert "AIC_AI_JEV_API_URL: ${AIC_AI_JEV_API_URL:-}" in compose
    assert "JEV_API_KEY: ${JEV_API_KEY:-}" in compose
    assert (
        "AIC_AI_RESEARCH_SCREENING_CONFIG: "
        "${AIC_AI_RESEARCH_SCREENING_CONFIG:-/app/config/research_screening/nine-router.example.json}"
        in compose
    )
    assert (
        "AIC_AI_RESEARCH_SCREENING_CONFIG=/app/config/research_screening/nine-router.example.json"
        in environment
    )
    assert "AIC_AI_JEV_API_URL=https://api.typesafe.ai/v1/systemone" in environment
    assert "JEV_API_KEY=" in environment


def test_python_process_health_checks_allow_for_application_import_time(
    project_root: Path,
) -> None:
    compose = (project_root / "deploy/compose.yaml").read_text(encoding="utf-8")

    assert compose.count("timeout: 45s") == 2
