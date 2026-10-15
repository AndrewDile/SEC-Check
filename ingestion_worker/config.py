"""Ingestion worker settings, read from environment variables."""

import os

CORE_API_URL = os.environ.get("CORE_API_URL", "http://localhost:8000")
CORE_API_TOKEN = os.environ["CORE_API_TOKEN"]

# The SEC blocks requests that don't identify the sender, e.g. "Team Name admin@example.com".
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "")

# Each poll re-checks events from this many days back. Older events are never matched.
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "30"))

KEV_POLL_INTERVAL_S = int(os.environ.get("KEV_POLL_INTERVAL_S", "3600"))
EDGAR_POLL_INTERVAL_S = int(os.environ.get("EDGAR_POLL_INTERVAL_S", "900"))
