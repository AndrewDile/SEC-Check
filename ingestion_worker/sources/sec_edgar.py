"""SEC EDGAR: 8-K filings in which a public company reports a cybersecurity incident.

If one of a company's software vendors files one of these, the company may be affected too.

This uses EDGAR full-text search, the API behind https://efts.sec.gov/LATEST/search-index.
The SEC does not document it, so it could change without notice.
"""

from datetime import UTC, date, datetime

import httpx

from ingestion_worker import config
from ingestion_worker.sources.base import Source, SourceEvent

SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

# Material incidents are reported under Item 1.05. Since May 2024 the SEC has asked
# companies to report incidents they have not (yet) found material under Item 8.01,
# and those filings usually say "cybersecurity incident" rather than "Item 1.05".
QUERY = '"Item 1.05" OR "cybersecurity incident"'


class SecEdgar8K(Source):
    name = "sec_edgar_8k"
    poll_interval_s = config.EDGAR_POLL_INTERVAL_S

    def fetch(self, since: datetime) -> list[SourceEvent]:
        # A filing has one search hit per matching document, so key events by accession number.
        events: dict[str, SourceEvent] = {}
        for hit in _search(since):
            filing = hit["_source"]
            if filing["adsh"] not in events and _reports_incident(filing):
                events[filing["adsh"]] = _to_event(filing)
        return list(events.values())


def _search(since: datetime) -> list[dict]:
    """Every search hit among 8-Ks (including 8-K/As) filed since `since`, across all pages."""
    if not config.SEC_USER_AGENT:
        raise RuntimeError("SEC_USER_AGENT is not set; the SEC blocks requests without one")
    params = {
        "q": QUERY,
        "forms": "8-K",
        "dateRange": "custom",
        "startdt": since.date().isoformat(),
        "enddt": date.today().isoformat(),
    }
    hits: list[dict] = []
    # One request at a time keeps us far below the SEC's limit of 10 requests per second.
    while True:
        response = httpx.get(
            SEARCH_URL,
            params={**params, "from": len(hits)},
            headers={"User-Agent": config.SEC_USER_AGENT},
            timeout=30,
        )
        response.raise_for_status()
        page = response.json()["hits"]
        hits += page["hits"]
        if not page["hits"] or len(hits) >= page["total"]["value"]:
            return hits


def _reports_incident(filing: dict) -> bool:
    items = filing.get("items") or []
    if "1.05" in items:
        return True
    # For Item 8.01, only count matches in the 8-K itself. Exhibits such as merger
    # agreements often mention "cybersecurity incident" in their boilerplate.
    return "8.01" in items and filing["file_type"] == filing["form"]


def _to_event(filing: dict) -> SourceEvent:
    # A filing can list several filers (e.g. a parent and its subsidiaries). Use the first.
    company = _company_name(filing["display_names"][0])
    cik = filing["ciks"][0]
    accession = filing["adsh"]
    material = "1.05" in filing["items"]
    item = (
        "Item 1.05 (Material Cybersecurity Incidents)" if material else "Item 8.01 (Other Events)"
    )
    return SourceEvent(
        external_id=accession,
        title=f"{company} reported a cybersecurity incident to the SEC",
        summary=f"{company} filed a Form {filing['form']} on {filing['file_date']} under {item}.",
        source_url=(
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession.replace('-', '')}/{accession}-index.htm"
        ),
        published_at=datetime.fromisoformat(filing["file_date"]).replace(tzinfo=UTC),
        priority_hint="critical" if material else "high",
        vendor=company,
        vendor_cik=cik,
        details={
            "form": filing["form"],
            "items": filing["items"],
            "filers": filing["display_names"],
        },
    )


def _company_name(display_name: str) -> str:
    """'AMGEN INC  (AMGN)  (CIK 0000318154)' -> 'AMGEN INC'. Also drops state tags like ' /DE'."""
    return display_name.split("  (")[0].split(" /")[0].strip()
