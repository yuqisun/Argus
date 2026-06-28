"""End-to-end pipeline test."""
import pytest
from httpx import AsyncClient, ASGITransport
from web.app import create_app


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_sentry_to_health_flow(self):
        """Verify webhook acceptance and health check in sequence."""
        app = create_app({"environment": "test"})

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Send Sentry webhook
            resp = await client.post("/hooks/sentry", json={
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
            assert resp.status_code == 202

            # 2. Check health still works
            resp = await client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_app_imports_and_runs(self):
        """Verify the app module is importable and creates a FastAPI app."""
        from web.app import app
        assert app.title == "Argus — Log Anomaly Intelligent Remediation"
