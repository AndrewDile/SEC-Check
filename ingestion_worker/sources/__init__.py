"""The third-party sources the worker polls."""

from ingestion_worker.sources.base import Source
from ingestion_worker.sources.cisa_kev import CisaKev
from ingestion_worker.sources.sec_edgar import SecEdgar8K

ALL_SOURCES: list[Source] = [CisaKev(), SecEdgar8K()]
