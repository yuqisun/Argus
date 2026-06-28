"""Integration tests for the web layer."""
import pytest
from httpx import AsyncClient, ASGITransport
from web.app import create_app


@pytest.fixture
def app():
    return create_app({"environment": "test"})


@pytest.mark.asyncio
async def test_health_check(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "argus"


@pytest.mark.asyncio
async def test_sentry_webhook_accepted(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/hooks/sentry", json={
            "event_id": "abc123",
            "message": "ValueError: something broke",
            "timestamp": "2026-06-28T10:30:00Z",
            "exception": {
                "values": [{
                    "type": "ValueError",
                    "value": "something broke",
                    "stacktrace": {
                        "frames": [
                            {"filename": "app.py", "lineno": 42, "function": "handle"}
                        ]
                    }
                }]
            },
            "tags": {"level": "error", "environment": "prod", "server_name": "api"},
            "request": {"url": "https://api.example.com/users"},
        })
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
