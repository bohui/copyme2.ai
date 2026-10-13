from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.store import MemoryStore


def test_memoir_api_namespace_adapts_to_existing_domain_routes() -> None:
    client = TestClient(create_app(MemoryStore()))

    response = client.get("/api/v1/memoir/config")

    assert response.status_code == 200
    assert response.headers["X-API-Namespace"] == "memoir"
    assert response.headers["Connection"] == "close"
    assert "trial_primary_sessions" in response.json()


def test_legacy_api_namespace_remains_compatible() -> None:
    client = TestClient(create_app(MemoryStore()))

    response = client.get("/v1/config")

    assert response.status_code == 200
    assert "X-API-Namespace" not in response.headers
    assert "Connection" not in response.headers
    assert "trial_primary_sessions" in response.json()


def test_api_no_longer_serves_the_retired_browser_shell() -> None:
    client = TestClient(create_app(MemoryStore()))

    response = client.get("/app/memoir/client.js")

    assert response.status_code == 404


def test_browser_proxy_errors_also_close_the_upstream_connection() -> None:
    client = TestClient(create_app(MemoryStore()))
    response = client.get('/api/v1/memoir/health')
    assert response.status_code == 404
    assert response.headers['Connection'] == 'close'
