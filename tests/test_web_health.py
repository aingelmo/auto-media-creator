"""Health endpoint contract for the container prober (homelab GET /health)."""

from fastapi.testclient import TestClient

from edl_agent.web.app import app


def test_health_returns_200_ok() -> None:
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_not_shadowed_by_spa_fallback() -> None:
    """The /{full_path:path} SPA route must not swallow /health."""
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.headers["content-type"].startswith("application/json")
