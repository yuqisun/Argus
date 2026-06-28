"""Orchestration: priority scoring, debounce, rate limiting, pipeline trigger."""
from __future__ import annotations
import structlog
from argus.models.event import RawEvent

logger = structlog.get_logger(__name__)


class PriorityScorer:
    """Score anomaly priority based on 5 signals → P0/P1/P2/P3."""

    WEIGHTS = {
        "severity": 0.35,
        "scope": 0.25,
        "trend": 0.20,
        "business": 0.10,
        "freshness": 0.10,
    }

    def evaluate(self, event: RawEvent) -> str:
        score = self.score(event)
        if score >= 80:
            return "P0"
        elif score >= 50:
            return "P1"
        elif score >= 25:
            return "P2"
        else:
            return "P3"

    def score(self, event: RawEvent) -> float:
        s = 0.0

        msg = event.raw_message.upper()
        if "FATAL" in msg or "CRITICAL" in msg:
            s += self.WEIGHTS["severity"] * 100
        elif "ERROR" in msg or "5XX" in msg:
            s += self.WEIGHTS["severity"] * 60
        elif "WARN" in msg:
            s += self.WEIGHTS["severity"] * 30

        host_count = event.metadata.get("host_count", 1)
        if isinstance(host_count, (int, float)) and host_count > 5:
            s += self.WEIGHTS["scope"] * 80
        elif isinstance(host_count, (int, float)) and host_count > 1:
            s += self.WEIGHTS["scope"] * 40
        else:
            s += self.WEIGHTS["scope"] * 10

        count = event.metadata.get("count", 1)
        if isinstance(count, (int, float)) and count > 100:
            s += self.WEIGHTS["trend"] * 90
        elif isinstance(count, (int, float)) and count > 10:
            s += self.WEIGHTS["trend"] * 50

        env = (event.environment or "").lower()
        if env == "prod" or env == "production":
            s += self.WEIGHTS["business"] * 80
        elif env == "staging":
            s += self.WEIGHTS["business"] * 40
        else:
            s += self.WEIGHTS["business"] * 10

        s += self.WEIGHTS["freshness"] * 50

        return s


class Orchestrator:
    """Orchestrate the end-to-end pipeline."""

    def __init__(self, scorer, ingest_service, rca_agent, owner_resolver, notifiers: list):
        self.scorer = scorer
        self.ingest = ingest_service
        self.rca = rca_agent
        self.owner = owner_resolver
        self.notifiers = notifiers

    async def handle_raw_event(self, event: RawEvent) -> dict:
        priority = self.scorer.evaluate(event)
        logger.info("Event scored", priority=priority, message=event.raw_message[:80])

        msg_id = await self.ingest.process(event)
        if not msg_id:
            return {"status": "deduped", "event": event.raw_message[:80]}

        return {
            "status": "published",
            "event": event.raw_message[:80],
            "priority": priority,
            "msg_id": msg_id,
        }
