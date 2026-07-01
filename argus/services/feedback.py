"""Feedback collection and recording."""
from __future__ import annotations
from dataclasses import dataclass
import structlog
from asyncpg import Pool

logger = structlog.get_logger(__name__)

FEEDBACK_TYPES = {
    "accurate", "inaccurate", "wrong_owner",
    "known_issue", "fix_adopted", "fix_modified",
}


@dataclass
class Feedback:
    event_id: str
    feedback_type: str
    comment: str = ""
    submitted_by: str = ""

    def __post_init__(self):
        if self.feedback_type not in FEEDBACK_TYPES:
            raise ValueError(
                f"Invalid feedback_type: {self.feedback_type}. Must be one of {FEEDBACK_TYPES}"
            )
        # Validate event_id — allow alphanumeric + hyphens (UUID, Sentry ID, etc.)
        import re
        if not re.match(r'^[a-zA-Z0-9\-]{1,64}$', self.event_id):
            raise ValueError(
                f"Invalid event_id format: {self.event_id}. Expected alphanumeric/UUID string."
            )


class FeedbackService:
    """Record and query user feedback on analysis results."""

    def __init__(self, db_pool: Pool):
        self.db = db_pool

    async def record(self, feedback: Feedback) -> None:
        await self.db.execute(
            """
            INSERT INTO feedbacks (event_id, feedback_type, comment, submitted_by, created_at)
            VALUES ($1, $2, $3, $4, NOW())
            """,
            feedback.event_id,
            feedback.feedback_type,
            feedback.comment,
            feedback.submitted_by,
        )
        logger.info("Feedback recorded", event_id=feedback.event_id,
                     type=feedback.feedback_type)

    async def get_for_event(self, event_id: str) -> list[Feedback]:
        rows = await self.db.fetch(
            "SELECT * FROM feedbacks WHERE event_id = $1 ORDER BY created_at DESC",
            event_id,
        )
        return [
            Feedback(
                event_id=row["event_id"],
                feedback_type=row["feedback_type"],
                comment=row["comment"] or "",
                submitted_by=row["submitted_by"] or "",
            )
            for row in rows
        ]
