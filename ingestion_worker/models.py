# Generated from core_api.openapi.yaml by generate_models.sh. Don't edit it by hand.

from __future__ import annotations

from typing import Any, Literal

from pydantic import AnyUrl, AwareDatetime, BaseModel

type SourceName = Literal["cisa_kev", "sec_edgar_8k"]


type Priority = Literal["critical", "high", "medium", "low"]


type Confidence = Literal["high", "medium"]


class Dependency(BaseModel):
    """
    A piece of software a company has told us it uses.
    """

    id: str
    company_id: str
    vendor: str
    product: str
    version: str | None = None
    cpe: str | None = None
    """
    Not used for matching yet. For future sources like NVD.
    """
    purl: str | None = None
    """
    Not used for matching yet. For future sources like OSV.
    """
    vendor_cik: str | None = None
    """
    The vendor's SEC CIK, if it is a public company.
    """


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
    An incident as the Core API stores it. The notification service receives it too.
    """

    id: str
    created_at: AwareDatetime
    notification_requested_at: AwareDatetime | None = None
    """
    Set by the Core API once the notification service has accepted the notification.
    While it is null, the ingestion worker keeps asking for notifications.
    """
