"""Webhook receiver endpoints."""
from fastapi import APIRouter, Request
import structlog
from argus.models.event import RawEvent

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post("/hooks/sentry", status_code=202)
async def sentry_webhook(request: Request):
    """Receive Sentry webhook alerts."""
    body = await request.json()

    stack_lines = []
    exception_data = body.get("exception", {})
    values = exception_data.get("values", [])
    if values:
        stacktrace = values[0].get("stacktrace", {})
        frames = stacktrace.get("frames", [])
        for frame in frames[-10:]:
            stack_lines.append(
                f'File "{frame.get("filename", "?")}", line {frame.get("lineno", 0)},'
                f' in {frame.get("function", "?")}'
            )

    raw = RawEvent(
        source="sentry",
        timestamp=body.get("timestamp", ""),
        raw_message=body.get("message", "")
        or (str(values[0].get("value", "")) if values else ""),
        service_name=body.get("tags", {}).get("server_name", "unknown"),
        host=body.get("tags", {}).get("host", "unknown"),
        environment=body.get("tags", {}).get("environment", "unknown"),
        stack_trace="\n".join(stack_lines) if stack_lines else None,
        metadata={
            "sentry_event_id": body.get("event_id", ""),
            "url": body.get("request", {}).get("url", ""),
            "level": body.get("tags", {}).get("level", "error"),
        },
    )

    logger.info("Sentry webhook received",
                event_id=raw.metadata.get("sentry_event_id"))

    return {"status": "accepted", "event_id": raw.metadata.get("sentry_event_id")}
