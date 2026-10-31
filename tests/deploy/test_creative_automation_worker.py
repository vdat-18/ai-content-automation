from pathlib import Path

from ai_content.domains.marketing.creative.config.preparation import (
    PreparationConfig,
)
from ai_content.settings import ApplicationSettings


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

    assert "AIC_ORCH_BASE_URL: ${AIC_ORCH_BASE_URL:-https://api.x.ai/v1}" in compose
    assert "AIC_ORCH_BASE_URL=https://api.x.ai/v1" in environment
    assert "AIC_ORCH_API_KEY=" in environment
    assert "AIC_PREP_BASE_URL: ${AIC_PREP_BASE_URL:-https://api.x.ai/v1}" in compose
    assert "AIC_PREP_BASE_URL=https://api.x.ai/v1" in environment
    assert "AIC_PREP_API_KEY=" in environment

    settings = ApplicationSettings()
    preparation = PreparationConfig.from_settings(settings, config_dir=project_root / "config")
    assert preparation.backend == "baml"
    assert preparation.fallback_model is None


def test_research_navigation_and_analysis_are_available_to_api_and_worker(
    project_root: Path,
) -> None:
    compose = (project_root / "deploy/compose.yaml").read_text(encoding="utf-8")
    environment = (project_root / "deploy/.env.example").read_text(encoding="utf-8")

    assert "AIC_AI_JEV_API_URL: ${AIC_AI_JEV_API_URL:-}" in compose
    assert "JEV_API_KEY: ${JEV_API_KEY:-}" in compose
    assert (
        "AIC_SCREENING_BASE_URL: "
        "${AIC_SCREENING_BASE_URL:-https://generativelanguage.googleapis.com/v1beta}"
    ) in compose
    assert (
        "AIC_SCREENING_BASE_URL=https://generativelanguage.googleapis.com/v1beta"
        in environment
    )
    assert "AIC_SCREENING_API_KEY=" in environment
    assert "AIC_AI_JEV_API_URL=https://api.typesafe.ai/v1/systemone" in environment
    assert "JEV_API_KEY=" in environment


def test_python_process_health_checks_allow_for_application_import_time(
    project_root: Path,
) -> None:
    compose = (project_root / "deploy/compose.yaml").read_text(encoding="utf-8")

    assert compose.count("timeout: 45s") == 2
