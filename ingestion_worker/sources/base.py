"""What every source provides."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from ingestion_worker.models import Priority, SourceName


@dataclass
class SourceEvent:
    """One item from a source (a KEV entry, an 8-K filing, ...) in a common shape."""

    external_id: str  # the source's own ID
    title: str
    summary: str
    source_url: str
    published_at: datetime
    priority_hint: Priority
    vendor: str  # the company the event is about
    product: str | None = None  # None means it may affect any product from `vendor`
    vendor_cik: str | None = None  # the vendor's SEC CIK, when the source gives it
    details: dict = field(default_factory=dict)  # source-specific extras, passed through as-is


class Source(ABC):
    """A third-party feed the worker polls.

    To add a source, subclass this and add an instance to ALL_SOURCES in
    sources/__init__.py. Its `name` must also be added to SourceName in the
    core_api.openapi.yaml of every service that defines it, followed by running that
    service's generate_models.sh.
    """

    name: SourceName
    poll_interval_s: int

    @abstractmethod
    def fetch(self, since: datetime) -> list[SourceEvent]:
        """Return every event published on or after `since`."""
