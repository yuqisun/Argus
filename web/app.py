"""FastAPI application entry point."""
from fastapi import FastAPI
from web.routes.health import router as health_router
from web.routes.hooks import router as hooks_router


def create_app(config: dict | None = None) -> FastAPI:
    env = (config or {}).get("environment", "dev")
    app = FastAPI(
        title="Argus — Log Anomaly Intelligent Remediation",
        version="0.1.0",
        docs_url="/docs" if env != "prod" else None,
    )
    app.include_router(health_router, tags=["health"])
    app.include_router(hooks_router, tags=["hooks"])

    @app.get("/")
    async def root():
        return {
            "service": "Argus — Log Anomaly Intelligent Remediation",
            "version": "0.1.0",
            "endpoints": {
                "health": "/health",
                "docs": "/docs",
                "sentry_webhook": "POST /hooks/sentry",
            }
        }

    return app


app = create_app()
