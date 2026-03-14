"""Smoke tests for health endpoints and app bootstrap."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    app = create_app()
    return TestClient(app)


def test_healthz_returns_200(client: TestClient) -> None:
    """Test that /healthz returns HTTP 200 with expected body."""
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["service"] == "api-change-radar"


def test_readyz_returns_200(client: TestClient) -> None:
    """Test that /readyz returns HTTP 200 with expected body."""
    response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["service"] == "api-change-radar"


def test_request_id_middleware_injects_header(client: TestClient) -> None:
    """Test that RequestIdMiddleware adds X-Request-ID to response."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert isinstance(response.headers["X-Request-ID"], str)
    assert len(response.headers["X-Request-ID"]) > 0


def test_request_id_middleware_respects_incoming_header(client: TestClient) -> None:
    """Test that RequestIdMiddleware respects incoming X-Request-ID header."""
    request_id = "test-request-123"
    response = client.get("/healthz", headers={"X-Request-ID": request_id})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id


def test_app_docs_available_by_default(client: TestClient) -> None:
    """Test that OpenAPI docs are enabled by default for local bootstrap."""
    response = client.get("/docs")
    assert response.status_code == 200


def test_root_endpoint_returns_bootstrap_info(client: TestClient) -> None:
    """Test that GET / provides a simple bootstrap response."""
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "api-change-radar"
    assert body["docs"] == "/docs"


def test_app_docs_can_be_disabled_via_settings() -> None:
    """Test that docs can be disabled explicitly with typed settings."""
    from app.core.config import Settings

    app = create_app(Settings(docs_enabled=False))
    client = TestClient(app)
    response = client.get("/docs")
    assert response.status_code == 404


def test_api_v1_router_registered(client: TestClient) -> None:
    """Test that the API v1 router is mounted and responding."""
    from app.core.config import Settings

    settings = Settings()
    api_prefix = settings.api_prefix  # default: "/api/v1"

    # The v1 root route should be available under the prefix
    response = client.get(f"{api_prefix}/")
    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "API v1 is available"
