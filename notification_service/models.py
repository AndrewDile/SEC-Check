# Generated from core_api.openapi.yaml by generate_models.sh. Don't edit it by hand.

from __future__ import annotations

from typing import Any, Literal

from pydantic import AnyUrl, AwareDatetime, BaseModel, Field

type SourceName = Literal["cisa_kev", "sec_edgar_8k"]


type Priority = Literal["critical", "high", "medium", "low"]


type Confidence = Literal["high", "medium"]


class MatchedDependency(BaseModel):
    """
    One of the company's dependencies that an incident may affect, and why we think so.
    """

    dependency_id: str
    vendor: str
    product: str
    version: str | None = None
    confidence: Confidence
    reason: str


class IncidentCreate(BaseModel):
    """
    A possible incident for one company, found by the ingestion worker.
    """

    company_id: str
    source: SourceName
    external_id: str
    """
    The source's own ID: a CVE ID, an SEC accession number, ...
    """
    title: str
    summary: str
    source_url: AnyUrl
    published_at: AwareDatetime
    """
    When the source published it.
    """
    detected_at: AwareDatetime
    """
    When we matched it, for the audit trail.
    """
    priority_hint: Priority
    """
    A hint for sorting only. Whether an incident is material is for the company to decide.
    """
    matched_dependencies: list[MatchedDependency]
    details: dict[str, Any] | None = {}
    """
    Source-specific extras.
    """


class Incident(IncidentCreate):
    """
    An incident as the Core API stores it.
    """

    id: str
    created_at: AwareDatetime


class Recipient(BaseModel):
    """
    One way to reach one team. The Core API sends one per contact method of every team.
    """

    recipient_id: str
    team_name: str
    channel: str = Field(..., examples=["email", "sms", "ms_teams"])
    address: str
    """
    What the channel needs: an email address, a phone number, a webhook URL, ...
    """


class NotificationRequest(BaseModel):
    """
    What the Core API sends the notification service when it creates an incident.
    """

    notification_id: str
    """
    Repeating an ID is a no-op, so the Core API can safely retry.
    """
    incident: Incident
    claim_url: AnyUrl
    """
    The web app page where a team claims the incident.
    """
    recipients: list[Recipient]


type DeliveryStatus = Literal["delivered", "failed"]


class DeliveryResult(BaseModel):
    recipient_id: str
    status: DeliveryStatus
    attempts: int = Field(..., ge=0)
    """
    0 when the notification service has no channel by that name.
    """
    error: str | None = None
    delivered_at: AwareDatetime | None = None


class NotificationResults(BaseModel):
    results: list[DeliveryResult]
