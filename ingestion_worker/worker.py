"""The ingestion pipeline: poll a source, match its events to dependencies, report incidents."""

import logging
import time
from datetime import UTC, datetime, timedelta

import httpx

from core_api_contract import IncidentCreate, MatchedDependency
from ingestion_worker import config, core_api
from ingestion_worker.matching import find_matches
from ingestion_worker.sources.base import Source, SourceEvent

log = logging.getLogger(__name__)


def run_forever(sources: list[Source]) -> None:
    """Poll each source on its own interval until the process is stopped."""
    next_poll = {source.name: 0.0 for source in sources}
    while True:
        for source in sources:
            if time.monotonic() >= next_poll[source.name]:
                poll(source)
                next_poll[source.name] = time.monotonic() + source.poll_interval_s
        time.sleep(max(0.0, min(next_poll.values()) - time.monotonic()))


def poll(source: Source) -> bool:
    """Poll `source` once and report every match. Returns False if anything failed.

    Nothing is remembered between polls. Each poll re-checks the last LOOKBACK_DAYS,
    and the Core API ignores incidents it already has, so anything that fails here
    is tried again on the next poll.
    """
    since = datetime.now(UTC) - timedelta(days=config.LOOKBACK_DAYS)
    try:
        events = source.fetch(since)
        dependencies = core_api.list_dependencies()
    except Exception:  # whatever goes wrong, keep polling the other sources
        log.exception("%s: poll failed", source.name)
        return False
    log.info("%s: %d events since %s", source.name, len(events), since.date())

    ok = True
    for event in events:
        for company_id, matches in find_matches(event, dependencies).items():
            try:
                report(source, event, company_id, matches)
            except httpx.HTTPError as error:
                log.error(
                    "%s: could not report %s for company %s: %s",
                    source.name,
                    event.external_id,
                    company_id,
                    error,
                )
                ok = False
    return ok


def report(
    source: Source, event: SourceEvent, company_id: str, matches: list[MatchedDependency]
) -> None:
    """Send one incident to the Core API, then request notifications if that hasn't happened yet."""
    incident = core_api.create_incident(
        IncidentCreate(
            company_id=company_id,
            source=source.name,
            external_id=event.external_id,
            title=event.title,
            summary=event.summary,
            source_url=event.source_url,
            published_at=event.published_at,
            detected_at=datetime.now(UTC),
            priority_hint=event.priority_hint,
            matched_dependencies=matches,
            details=event.details,
        )
    )
    if incident.notification_requested_at is None:
        core_api.request_notifications(incident.id)
        log.info(
            "%s: notifying company %s of incident %s (%s)",
            source.name,
            company_id,
            incident.id,
            event.title,
        )
