"""Ingest pipeline: fingerprint → dedup → filter → publish."""
from __future__ import annotations
import time
import structlog
from argus.models.event import RawEvent, AnomalyEvent
from argus.interfaces.event_bus import EventBus
from argus.interfaces.fingerprinter import Fingerprinter

logger = structlog.get_logger(__name__)


class DedupState:
    """Tracks fingerprint state for dedup/cooldown in memory."""

    def __init__(self, dedup_window: float = 300, cooldown: float = 3600):
        self.dedup_window = dedup_window
        self.cooldown = cooldown
        self._seen: dict[str, float] = {}
        self._cooldowns: dict[str, float] = {}
        self._counts: dict[str, int] = {}

    def should_publish(self, fp_hash: str) -> bool:
        now = time.time()
        if fp_hash in self._cooldowns and now < self._cooldowns[fp_hash]:
            return False
        if fp_hash in self._seen and (now - self._seen[fp_hash]) < self.dedup_window:
            return False
        return True

    def record(self, fp_hash: str) -> None:
        now = time.time()
        if fp_hash not in self._seen:
            self._seen[fp_hash] = now
            self._counts[fp_hash] = 1
        else:
            self._counts.setdefault(fp_hash, 0)
            self._counts[fp_hash] += 1

    def set_cooldown(self, fp_hash: str) -> None:
        self._cooldowns[fp_hash] = time.time() + self.cooldown

    def get_count(self, fp_hash: str) -> int:
        return self._counts.get(fp_hash, 1)


class IngestService:
    """Collector → fingerprint → dedup → filter → publish."""

    def __init__(
        self,
        fingerprinter: Fingerprinter,
        event_bus: EventBus,
        dedup_window: float = 300,
        cooldown: float = 3600,
    ):
        self.fingerprinter = fingerprinter
        self.event_bus = event_bus
        self.state = DedupState(dedup_window=dedup_window, cooldown=cooldown)
        self._whitelist: set[str] = set()

    def add_whitelist(self, fp_hash: str) -> None:
        self._whitelist.add(fp_hash)

    async def process(self, event: RawEvent) -> str | None:
        fp = self.fingerprinter.fingerprint(event)

        if fp.hash in self._whitelist:
            logger.debug("Event whitelisted", fp_hash=fp.hash)
            return None

        if not self.state.should_publish(fp.hash):
            self.state.record(fp.hash)
            logger.debug("Event deduped", fp_hash=fp.hash)
            return None

        self.state.record(fp.hash)
        anomaly = AnomalyEvent.create(event, fp.hash)
        msg_id = await self.event_bus.publish(anomaly, anomaly.priority)
        logger.info("Anomaly published", event_id=anomaly.event_id, fp_hash=fp.hash)
        return msg_id
