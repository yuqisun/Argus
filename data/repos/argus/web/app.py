"""FastAPI application entry point with pipeline wiring."""
import os
from pathlib import Path

# Load .env before anything else
_dotenv_path = Path(__file__).resolve().parent.parent / ".env"
if _dotenv_path.exists():
    # Read .env manually (avoid python-dotenv import overhead when not needed)
    for _line in _dotenv_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip().strip('"').strip("'"))

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

    # Bootstrap pipeline services into app state
    pipeline = _build_pipeline(config or {})
    app.state.pipeline = pipeline

    app.include_router(health_router, tags=["health"])
    app.include_router(hooks_router, tags=["hooks"])

    @app.get("/")
    async def root():
        return {
            "service": "Argus — Log Anomaly Intelligent Remediation",
            "version": "0.1.0",
            "pipeline": "ready" if pipeline else "unconfigured",
            "endpoints": {
                "health": "/health",
                "docs": "/docs",
                "sentry_webhook": "POST /hooks/sentry",
            },
        }

    return app


def _build_pipeline(config: dict):
    """Build pipeline services from config. Returns dict of services or None."""
    try:
        from argus.implementations.fingerprint.stack_message_fp import StackMessageFingerprinter
        from argus.services.ingest import IngestService
        from argus.services.orchestration import PriorityScorer
        from argus.implementations.event_bus.redis_bus import RedisEventBus

        # Fingerprinter (always works, no deps)
        fp_cfg = config.get("fingerprinter", {})
        fingerprinter = StackMessageFingerprinter(
            stack_top_n=fp_cfg.get("stack_top_n", 5),
        )

        # Priority scorer (always works)
        scorer = PriorityScorer()

        # EventBus (try Redis, fallback to in-memory stub)
        event_bus = _build_event_bus(config)

        # Ingest pipeline
        ingest = IngestService(
            fingerprinter=fingerprinter,
            event_bus=event_bus,
        )

        # Try LLM
        llm_client = _build_llm(config)

        # Try code searcher
        code_searcher = _build_code_searcher(config)

        # RCA agent
        from argus.services.rca_agent import RCAAgent
        rca = RCAAgent(
            llm=llm_client,
            searcher=code_searcher,
        ) if llm_client and code_searcher else None

        # Owner resolver
        owner = _build_owner(config)

        # Notifiers
        notifiers = _build_notifiers(config)

        return {
            "fingerprinter": fingerprinter,
            "scorer": scorer,
            "event_bus": event_bus,
            "ingest": ingest,
            "rca": rca,
            "owner": owner,
            "notifiers": notifiers,
        }
    except Exception:
        import structlog
        logger = structlog.get_logger("web")
        logger.exception("Pipeline build failed")
        return None


def _build_event_bus(config: dict):
    """Try Redis, fallback to in-memory stub."""
    try:
        import redis.asyncio as redis
        redis_cfg = config.get("redis", {})
        url = redis_cfg.get("url", "redis://localhost:6379/0")
        client = redis.Redis.from_url(url)
        from argus.implementations.event_bus.redis_bus import RedisEventBus
        return RedisEventBus(redis_client=client)
    except Exception:
        # In-memory fallback
        import structlog
        structlog.get_logger("web").warning("Redis unavailable, using in-memory event bus")

        class InMemoryBus:
            def __init__(self):
                self.published: list = []
            async def publish(self, event, priority):
                self.published.append((event, priority))
                return event.event_id
            async def consume(self, priority):
                if False: yield
            async def dead_letter(self, event, reason):
                pass

        return InMemoryBus()


def _build_llm(config: dict):
    """Try to build LLM client. Returns None if no API key."""
    import os
    import structlog
    logger = structlog.get_logger("web")
    llm_cfg = config.get("llm", {})
    api_key = llm_cfg.get("api_key", "") or os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        logger.warning("No LLM API key — RCA analysis disabled")
        return None
    from argus.implementations.llm.openai_client import OpenAILLMClient
    return OpenAILLMClient(
        base_url=llm_cfg.get("base_url", "https://api.deepseek.com"),
        api_key=api_key,
        default_model=llm_cfg.get("models", {}).get("strong", "deepseek-chat"),
    )


def _build_code_searcher(config: dict):
    """Try to build code searcher. Returns None if no repos."""
    import structlog
    logger = structlog.get_logger("web")
    cs_cfg = config.get("code_search", {})
    repos_root = cs_cfg.get("local", {}).get("repos_root", "./data/repos")
    from pathlib import Path
    if not Path(repos_root).exists():
        logger.warning("No repos root — code search disabled")
        return None
    from argus.implementations.code_search.local_searcher import LocalRepoCodeSearcher
    return LocalRepoCodeSearcher(repos_root=repos_root)


def _build_owner(config: dict):
    """Build owner resolver (always works without deps)."""
    cs_cfg = config.get("code_search", {})
    repos_root = cs_cfg.get("local", {}).get("repos_root", "./data/repos")
    from argus.implementations.owner.github_resolver import GitHubOwnerResolver
    return GitHubOwnerResolver(repos_root=repos_root)


def _build_notifiers(config: dict):
    """Build notifiers from config."""
    import structlog
    logger = structlog.get_logger("web")
    notifiers = []
    for n_cfg in config.get("notifiers", []):
        if n_cfg.get("type") == "smtp":
            from argus.implementations.notifiers.smtp_notifier import SMTPNotifier
            notifiers.append(SMTPNotifier(
                host=n_cfg.get("host", "localhost"),
                port=n_cfg.get("port", 1025),
                from_addr=n_cfg.get("from_addr", "argus@company.com"),
            ))
        else:
            logger.info("Unknown notifier type", type=n_cfg.get("type"))
    return notifiers


app = create_app()
