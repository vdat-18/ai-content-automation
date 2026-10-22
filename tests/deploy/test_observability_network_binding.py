from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).parents[2]


def test_grafana_bind_address_is_explicit_and_safe_by_default() -> None:
    compose = (_REPOSITORY_ROOT / "deploy/compose.observability.yaml").read_text(
        encoding="utf-8"
    )
    environment = (_REPOSITORY_ROOT / "deploy/.env.example").read_text(
        encoding="utf-8"
    )

    assert "${AIC_GRAFANA_BIND_ADDRESS:-127.0.0.1}" in compose
    assert "AIC_GRAFANA_BIND_ADDRESS=127.0.0.1" in environment


def test_langfuse_public_url_and_bind_address_are_configurable() -> None:
    compose = (_REPOSITORY_ROOT / "deploy/compose.langfuse.yaml").read_text(
        encoding="utf-8"
    )
    environment = (_REPOSITORY_ROOT / "deploy/.env.example").read_text(
        encoding="utf-8"
    )

    assert "NEXTAUTH_URL: ${AIC_LANGFUSE_PUBLIC_URL:-http://localhost:3001}" in compose
    assert "${AIC_LANGFUSE_BIND_ADDRESS:-127.0.0.1}" in compose
    assert "AIC_LANGFUSE_BIND_ADDRESS=127.0.0.1" in environment
    assert "AIC_LANGFUSE_PUBLIC_URL=http://localhost:3001" in environment


def test_database_and_debug_ports_have_configurable_safe_bind_defaults() -> None:
    base_compose = (_REPOSITORY_ROOT / "deploy/compose.yaml").read_text(
        encoding="utf-8"
    )
    debug_compose = (_REPOSITORY_ROOT / "deploy/compose.debug.yaml").read_text(
        encoding="utf-8"
    )
    environment = (_REPOSITORY_ROOT / "deploy/.env.example").read_text(
        encoding="utf-8"
    )

    assert "${AIC_POSTGRES_BIND_ADDRESS:-127.0.0.1}:5432:5432" in base_compose
    assert debug_compose.count("${AIC_DEBUG_BIND_ADDRESS:-127.0.0.1}") == 19
    assert "${AIC_DEBUG_SEAWEED_S3_PORT:-8333}:8333" in debug_compose
    assert "AIC_POSTGRES_BIND_ADDRESS=127.0.0.1" in environment
    assert "AIC_DEBUG_BIND_ADDRESS=127.0.0.1" in environment
    assert "AIC_DEBUG_SEAWEED_S3_PORT=8333" in environment
