"""Proposed Core API contract for the ingestion worker and the notification service.

These models are the request and response bodies of every Core API call the two
services make or receive, so the team can review the whole interface in one place.

    Ingestion worker -> Core API
        GET  /v1/dependencies                       -> list[Dependency]
        POST /v1/incidents         IncidentCreate   -> Incident (201 new, 200 already reported)
        POST /v1/incidents/{id}/notifications       -> 202

    Core API -> notification service
        POST /v1/notifications     NotificationRequest -> 202

    Notification service -> Core API
        POST /v1/notifications/{id}/results  NotificationResults -> 200

Every call sends "Authorization: Bearer <token>".
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

SourceName = Literal["cisa_kev", "sec_edgar_8k"]
Priority = Literal["critical", "high", "medium", "low"]
Confidence = Literal["high", "medium"]
DeliveryStatus = Literal["delivered", "failed"]


# Dependencies -------------------------------------------------------------


class Dependency(BaseModel):
    """A piece of software a company has told us it uses."""

    id: str
    company_id: str
    vendor: str
    product: str
    version: str | None = None
    cpe: str | None = None  # not used for matching yet; for future sources like NVD
    purl: str | None = None  # not used for matching yet; for future sources like OSV
    vendor_cik: str | None = None  # the vendor's SEC CIK, if it is a public company


# Incidents ----------------------------------------------------------------


class MatchedDependency(BaseModel):
    """One of the company's dependencies that an incident may affect, and why we think so."""

    dependency_id: str
    vendor: str
    product: str
    version: str | None = None
    confidence: Confidence
    reason: str


class IncidentCreate(BaseModel):
    """A possible incident for one company, found by the ingestion worker.

    (company_id, source, external_id) is unique. Reporting the same incident again
    returns the existing one with 200 instead of creating a duplicate.
    """

    company_id: str
    source: SourceName
    external_id: str  # the source's own ID: a CVE ID, an SEC accession number, ...
    title: str
    summary: str
    source_url: str
    published_at: datetime  # when the source published it
    detected_at: datetime  # when we matched it, for the audit trail
    # A hint for sorting only. Whether an incident is material is for the company to decide.
    priority_hint: Priority
    matched_dependencies: list[MatchedDependency]
    details: dict = {}  # source-specific extras


class Incident(IncidentCreate):
    id: str
    created_at: datetime
    # Set by the Core API once the notification service has accepted the notification.
    # While it is None, the ingestion worker keeps asking for notifications.
    notification_requested_at: datetime | None = None


# Notifications ------------------------------------------------------------


class Recipient(BaseModel):
    """One way to reach one team. The Core API sends one per contact method of every team."""

    recipient_id: str
    team_name: str
    channel: str  # e.g. "email", "sms", "ms_teams"
    address: str  # what the channel needs: an email address, a phone number, a webhook URL, ...


class NotificationRequest(BaseModel):
    notification_id: str  # repeating an ID is a no-op, so the Core API can safely retry
    incident: Incident
    claim_url: str  # the web app page where a team claims the incident
    recipients: list[Recipient]


class DeliveryResult(BaseModel):
    recipient_id: str
    status: DeliveryStatus
    attempts: int
    error: str | None = None
    delivered_at: datetime | None = None


class NotificationResults(BaseModel):
    results: list[DeliveryResult]
