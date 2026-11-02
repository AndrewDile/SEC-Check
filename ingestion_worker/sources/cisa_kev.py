"""CISA's Known Exploited Vulnerabilities (KEV) catalog: vulnerabilities attackers are actively using."""

from datetime import UTC, date, datetime

import httpx

from ingestion_worker import config
from ingestion_worker.sources.base import Source, SourceEvent


class CisaKev(Source):
    name = "cisa_kev"
    poll_interval_s = config.KEV_POLL_INTERVAL_S
    full_history = True

    def fetch(self, since: datetime) -> list[SourceEvent]:
        # The feed is always the whole catalog, so keep only the recent entries.
        response = httpx.get(config.KEV_URL, timeout=60)
        response.raise_for_status()
        return [
            _to_event(entry)
            for entry in response.json()["vulnerabilities"]
            if date.fromisoformat(entry["dateAdded"]) >= since.date()
        ]


def _to_event(entry: dict) -> SourceEvent:
    cve = entry["cveID"]
    return SourceEvent(
        external_id=cve,
        title=f"{cve}: {entry['vulnerabilityName']}",
        summary=entry["shortDescription"],
        source_url=f"https://nvd.nist.gov/vuln/detail/{cve}",
        published_at=datetime.fromisoformat(entry["dateAdded"]).replace(tzinfo=UTC),
        # "Known" means CISA has seen the vulnerability used in ransomware campaigns.
        priority_hint="critical" if entry["knownRansomwareCampaignUse"] == "Known" else "high",
        vendor=entry["vendorProject"],
        product=entry["product"],
        details={
            key: entry.get(key)
            for key in ("requiredAction", "dueDate", "knownRansomwareCampaignUse", "cwes", "notes")
        },
    )
