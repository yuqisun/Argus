"""Webhook receiver with full pipeline integration."""
from fastapi import APIRouter, Request
import structlog
from argus.models.event import RawEvent

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.post("/hooks/sentry", status_code=202)
async def sentry_webhook(request: Request):
    """Receive Sentry webhook → full pipeline."""
    body = await request.json()

    # Parse Sentry payload into RawEvent
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

    # Run pipeline
    pipeline = request.app.state.pipeline

    result = {
        "status": "accepted",
        "event_id": raw.metadata.get("sentry_event_id"),
    }

    if pipeline:
        # 1. Fingerprint
        fp = pipeline["fingerprinter"].fingerprint(raw)
        result["fingerprint"] = fp.hash
        result["exception_type"] = fp.exception_type

        # 2. Score priority
        priority = pipeline["scorer"].evaluate(raw)
        result["priority"] = priority

        # 3. Ingest (dedup + publish)
        msg_id = await pipeline["ingest"].process(raw)
        if msg_id is None:
            result["status"] = "deduped"
            result["note"] = "duplicate within window"
            logger.info("Sentry event deduped", **result)
            return result

        result["msg_id"] = msg_id

        # 4. RCA (if LLM configured)
        rca = pipeline.get("rca")
        if rca:
            try:
                rca_result = await rca.analyze(raw, repo="unknown", commit="unknown")
                result["root_cause"] = rca_result.root_cause_summary[:500]
                result["confidence"] = rca_result.confidence
                result["root_cause_type"] = rca_result.root_cause_type
                if rca_result.diff_suggestion:
                    result["diff"] = rca_result.diff_suggestion[:500]
            except Exception:
                logger.exception("RCA analysis failed")
                result["root_cause"] = "analysis failed"
        else:
            result["root_cause"] = "LLM not configured (set DEEPSEEK_API_KEY)"

        # 5. Owner resolution
        owner = pipeline.get("owner")
        if owner and fp.top_frames:
            # Extract first frame info
            first_frame = fp.top_frames[0] if fp.top_frames else None
            if first_frame:
                file_path = first_frame.split(":")[0] if ":" in first_frame else "unknown"
                try:
                    owners = await owner.resolve(
                        "unknown", file_path, 0, commit="unknown"
                    )
                    result["owners"] = [
                        {"name": o.name, "email": o.email, "source": o.source}
                        for o in owners
                    ]
                except Exception:
                    result["owners"] = []

        # 6. Notification (if configured)
        notifiers = pipeline.get("notifiers", [])
        if notifiers:
            from argus.interfaces.notifier import Notification
            notif = Notification(
                subject=f"[Argus][{priority}] {raw.raw_message[:80]}",
                body_html=f"<pre>{result.get('root_cause', '')}</pre>",
                body_text=result.get("root_cause", ""),
                recipients=[],
                priority=priority,
            )
            for n in notifiers:
                try:
                    await n.send(notif)
                except Exception:
                    pass

    logger.info("Pipeline complete", **result)
    return result
