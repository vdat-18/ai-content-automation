from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.pgstore import runtime_container

from ai_content.entrypoints.api.app import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AIC_AI_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("AIC_AI_CONFIG_DIR", str(Path(__file__).parent.parent / "config"))
    monkeypatch.setattr(app.state, "postgres_runtime", runtime_container(), raising=False)
    return TestClient(app)


def test_health_endpoints(client: TestClient) -> None:
    assert client.get("/health/live").json()["checks"] == {"process": "ok"}
    ready = client.get("/health/ready").json()
    assert ready["status"] == "ok" and ready["checks"] == {"storage": "ok", "database": "ok"}
    assert client.get("/api/v1/health").json()["status"] == "ok"


def test_dashboard_routes_are_mounted(client: TestClient) -> None:
    assert client.get("/api/v1/products").json() == []
    assert client.get("/api/v1/products/reference-images").json() == []
    assert client.get("/api/v1/notifications").json()["total"] == 0
    assert client.get("/api/v1/marketing/creative-knowledge").json() == {"items": [], "total": 0}
    assert client.get("/api/v1/ai-usage/summary").status_code == 200


def test_removed_workflows_are_gone(client: TestClient) -> None:
    for path in (
        "/api/v1/marketing/research-crawls",
        "/api/v1/marketing/creative-automation/batches",
        "/api/v1/data-sources/brands",
        "/api/v1/execution/commands",
    ):
        assert client.get(path).status_code == 404


def test_creative_knowledge_bootstrap_reads_the_config_directory(client: TestClient) -> None:
    response = client.post(
        "/api/v1/marketing/creative-knowledge/bootstrap",
        json={"contributor": "tester", "manifest_id": "product_ad"},
    )
    assert response.status_code == 200, response.text
    assert client.get("/api/v1/marketing/creative-knowledge").json()["total"] > 0
