from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.store import MemoryStore


def test_memoir_api_namespace_adapts_to_existing_domain_routes() -> None:
    client = TestClient(create_app(MemoryStore()))

    response = client.get("/api/v1/memoir/config")

    assert response.status_code == 200
    assert response.headers["X-API-Namespace"] == "memoir"
    assert "trial_primary_sessions" in response.json()


def test_legacy_api_namespace_remains_compatible() -> None:
    client = TestClient(create_app(MemoryStore()))

    response = client.get("/v1/config")

    assert response.status_code == 200
    assert "X-API-Namespace" not in response.headers
    assert "trial_primary_sessions" in response.json()


def test_product_routes_serve_the_web_shell() -> None:
    client = TestClient(create_app(MemoryStore()))

    response = client.get("/memoir/start")

    assert response.status_code == 200
    assert "CopyMe2" in response.text
    assert "/app/memoir/client.js" in response.text
