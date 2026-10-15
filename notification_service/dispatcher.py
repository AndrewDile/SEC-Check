"""Deliver a notification to every recipient, then report the results to the Core API."""

import logging
import time
from datetime import UTC, datetime

from notification_service import config, core_api
from notification_service.channels import CHANNELS
from notification_service.channels.base import Message, PermanentDeliveryError
from notification_service.models import (
    DeliveryResult,
    DeliveryStatus,
    NotificationRequest,
    Recipient,
)

log = logging.getLogger(__name__)

BODY = """\
{title}

{summary}

Dependencies that may be affected:
{dependencies}

Source: {source_url} (published {published})

No team has claimed this incident yet. To claim it, go to {claim_url}

This notice does not decide whether the incident is material. That is for your company to decide.
"""


def dispatch(request: NotificationRequest) -> None:
    message = render(request)
    results = [deliver(recipient, message) for recipient in request.recipients]
    delivered = sum(result.status == "delivered" for result in results)
    log.info(
        "Notification %s: delivered to %d of %d recipients",
        request.notification_id,
        delivered,
        len(results),
    )
    core_api.report_results(request.notification_id, results)


def render(request: NotificationRequest) -> Message:
    """Build the message that every channel sends."""
    incident = request.incident
    lines = []
    for d in incident.matched_dependencies:
        version = f" {d.version}" if d.version else ""
        lines.append(f"  - {d.vendor} {d.product}{version} ({d.confidence} confidence: {d.reason})")
    return Message(
        subject=f"[{incident.priority_hint.upper()}] Possible cybersecurity incident: {incident.title}",
        body=BODY.format(
            title=incident.title,
            summary=incident.summary,
            dependencies="\n".join(lines),
            source_url=incident.source_url,
            published=incident.published_at.date(),
            claim_url=request.claim_url,
        ),
        claim_url=str(request.claim_url),
    )


def deliver(recipient: Recipient, message: Message) -> DeliveryResult:
    """Send `message` to one recipient, retrying with exponential backoff (2s, 4s, ...)."""
    channel = CHANNELS.get(recipient.channel)
    if channel is None:
        return _result(recipient, "failed", 0, f"no channel named {recipient.channel!r}")

    error = ""
    for attempt in range(1, config.MAX_ATTEMPTS + 1):
        if attempt > 1:
            time.sleep(2 ** (attempt - 1))
        try:
            channel.send(recipient, message)
            return _result(recipient, "delivered", attempt)
        except PermanentDeliveryError as e:
            return _result(recipient, "failed", attempt, str(e))
        # Any other error may be temporary, so try again.
        except Exception as e:  # noqa: BLE001
            error = str(e)
            log.warning(
                "Attempt %d to reach %s via %s failed: %s",
                attempt,
                recipient.recipient_id,
                channel.name,
                e,
            )
    return _result(recipient, "failed", config.MAX_ATTEMPTS, error)


def _result(
    recipient: Recipient, status: DeliveryStatus, attempts: int, error: str | None = None
) -> DeliveryResult:
    return DeliveryResult(
        recipient_id=recipient.recipient_id,
        status=status,
        attempts=attempts,
        error=error,
        delivered_at=datetime.now(UTC) if status == "delivered" else None,
    )
