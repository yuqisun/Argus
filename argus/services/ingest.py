"""Ingest pipeline: fingerprint → dedup → filter → publish."""
from __future__ import annotations
import time
import structlog
from argus.models.event import RawEvent, AnomalyEvent
from argus.interfaces.event_bus import EventBus
from argus.interfaces.fingerprinter import Fingerprinter

logger = structlog.get_logger(__name__)


class DedupState:
    """Tracks fingerprint state for dedup/cooldown.

    Uses Redis when available (multi-worker safe), falls back to in-memory.
    """

    DEDUP_KEY = "argus:dedup:seen"
    COOLDOWN_KEY = "argus:dedup:cooldown"
    COUNT_KEY = "argus:dedup:count"

    def __init__(
        self,
        dedup_window: float = 300,
        cooldown: float = 3600,
        redis_client=None,
    ):
        self.dedup_window = dedup_window
        self.cooldown = cooldown
        self._redis = redis_client
        # In-memory fallback
        self._seen: dict[str, float] = {}
        self._cooldowns: dict[str, float] = {}
        self._counts: dict[str, int] = {}

    async def should_publish(self, fp_hash: str) -> bool:
        now = time.time()
        if self._redis:
            # Check cooldown
            cd_remaining = await self._redis.ttl(f"{self.COOLDOWN_KEY}:{fp_hash}")
            if cd_remaining and cd_remaining > 0:
                return False
            # Check dedup window — use SETNX with TTL
            seen_key = f"{self.DEDUP_KEY}:{fp_hash}"
            set_result = await self._redis.set(seen_key, str(now), nx=True, ex=int(self.dedup_window))
            if not set_result:
                return False
            return True
        else:
            if fp_hash in self._cooldowns and now < self._cooldowns[fp_hash]:
                return False
            if fp_hash in self._seen and (now - self._seen[fp_hash]) < self.dedup_window:
                return False
            return True

    async def record(self, fp_hash: str) -> None:
        if self._redis:
            await self._redis.incr(f"{self.COUNT_KEY}:{fp_hash}")
        else:
            now = time.time()
            if fp_hash not in self._seen:
                self._seen[fp_hash] = now
                self._counts[fp_hash] = 1
            else:
                self._counts.setdefault(fp_hash, 0)
                self._counts[fp_hash] += 1

    async def set_cooldown(self, fp_hash: str) -> None:
        if self._redis:
            await self._redis.set(
                f"{self.COOLDOWN_KEY}:{fp_hash}", "1", ex=int(self.cooldown),
            )
        else:
            self._cooldowns[fp_hash] = time.time() + self.cooldown

    async def get_count(self, fp_hash: str) -> int:
        if self._redis:
            val = await self._redis.get(f"{self.COUNT_KEY}:{fp_hash}")
            return int(val) if val else 1
        else:
            return self._counts.get(fp_hash, 1)


class IngestService:
    """Collector → fingerprint → dedup → filter → publish."""

    def __init__(
        self,
        fingerprinter: Fingerprinter,
        event_bus: EventBus,
        dedup_window: float = 300,
        cooldown: float = 3600,
        redis_client=None,
    ):
        self.fingerprinter = fingerprinter
        self.event_bus = event_bus
        self.state = DedupState(
            dedup_window=dedup_window, cooldown=cooldown, redis_client=redis_client,
        )
        self._whitelist: set[str] = set()

    def add_whitelist(self, fp_hash: str) -> None:
        self._whitelist.add(fp_hash)

    async def process(self, event: RawEvent, priority: str = "P2") -> str | None:
        fp = self.fingerprinter.fingerprint(event)

        if fp.hash in self._whitelist:
            logger.debug("Event whitelisted", fp_hash=fp.hash)
            return None

        if not await self.state.should_publish(fp.hash):
            await self.state.record(fp.hash)
            logger.debug("Event deduped", fp_hash=fp.hash)
            return None

        await self.state.record(fp.hash)
        anomaly = AnomalyEvent.create(event, fp.hash, priority=priority)
        msg_id = await self.event_bus.publish(anomaly, anomaly.priority)
        logger.info("Anomaly published", event_id=anomaly.event_id, fp_hash=fp.hash, priority=priority)
        return msg_id
