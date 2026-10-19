# Ingestion worker

**Folder:** `ingestion_worker/`. **Stack:** Python 3.13, FastAPI, httpx and Pydantic, through
uv with the root `pyproject.toml` and `uv.lock`. **Port:** 8002, inside the stack only.

The worker polls public feeds for vulnerabilities and incident reports, matches them to the
company's dependencies, and reports each match to the Core API as a possible incident. The Core
API then notifies the teams.

## How it runs

`python -m ingestion_worker` does two things at once:

- **Event API:** a thread runs the API that receives dependency events from the Core API.
- **Poll loop:** the main thread polls each source on its own interval, starting with an
  immediate poll.

`--once` polls each source one time and exits nonzero if anything failed. `--source NAME`
polls only that source.

Each poll goes like this (`worker.py`):

1. **Fetch:** get the source's events from the last `LOOKBACK_DAYS`.
2. **Load dependencies** from the in-memory cache. The first time, it loads them with
   `GET /ingest/dependencies`.
3. **Match** each event to the dependencies, grouped by company.
4. **Report:** `POST /ingest/incidents` for each company that has a match. A 201 means new;
   a 200 means the Core API already had it.

It remembers nothing between polls:

- Every poll re-reports its whole window, and the Core API ignores repeats.
- A failed report is simply tried again on the next poll.
- An error in one source is logged and doesn't stop the others.

## Sources

| Source | `name` | Interval | What counts as an event |
|---|---|---|---|
| CISA Known Exploited Vulnerabilities (`sources/cisa_kev.py`) | `cisa_kev` | `KEV_POLL_INTERVAL_S`, default 3600 s | Every catalog entry added since the lookback date |
| SEC EDGAR full-text search (`sources/sec_edgar.py`) | `sec_edgar_8k` | `EDGAR_POLL_INTERVAL_S`, default 900 s | 8-K and 8-K/A filings that match `"Item 1.05" OR "cybersecurity incident"`. A filing counts if it lists Item 1.05, or lists Item 8.01 with the match in the 8-K itself rather than an exhibit |

Each source builds its events like this:

- **KEV:**
    - **ID:** the CVE ID. **Link:** the NVD page.
    - **Priority:** `critical` if CISA has seen the vulnerability used by ransomware, otherwise
      `high`.
    - **Vendor and product:** from the catalog entry.
- **EDGAR:**
    - **ID:** the accession number. **Link:** the filing index.
    - **Priority:** `critical` for Item 1.05, `high` for Item 8.01.
    - **Vendor:** the filing company, with its CIK, and no product, so the event may affect any
      of that vendor's products.
    - **Requests:** it makes one request at a time, with `SEC_USER_AGENT`.
    - **API:** it uses EDGAR's search API, which the SEC doesn't document.

To add a source, subclass `Source` in `sources/base.py` and add it to `ALL_SOURCES`. Its name
must also be added to `SourceName` in **both** services' `core_api.openapi.yaml`; then run each
service's `generate_models.sh`.

## Matching (`matching.py`)

Matching uses names only, because the feeds give only names, and it never compares versions.
The rules are checked in this order:

| Rule | Confidence |
|---|---|
| The event's vendor CIK equals the dependency's `vendor_cik` (leading zeros ignored) | high |
| Vendor names differ (after lowercasing, keeping only letters and digits, and dropping suffixes like *Inc*, *Corp*, *Systems*) | no match |
| The event has no product (EDGAR) | medium |
| The product names are equal | high |
| The event's product is "Multiple Products" | medium |
| One product name contains the other as whole consecutive words | medium |
| Otherwise | no match |

Each match carries a human-readable `reason`, which ends up in the notification.

## Dependency cache (`dependency_cache.py`)

The cache is an in-memory dictionary, loaded on the first poll and updated by the Core API's
`PUT` and `DELETE` events.

- **Before the first load:** events are dropped, since the load already includes them.
- **On restart:** the worker reloads it from the Core API.
- **Locking:** a lock guards it, because the event API and the poll loop run on different
  threads.

## Interfaces

**Worker API**, which only the Core API calls, with `INGEST_INBOUND_TOKEN`. Both calls are
idempotent.

<swagger-ui src="../openapi/ingestion_worker/openapi.yaml"/>

**Core API endpoints the worker calls**, with `INGEST_CORE_API_TOKEN`, and the payloads they
share. `models.py` is generated from this file.

<swagger-ui src="../openapi/ingestion_worker/core_api.openapi.yaml"/>

These two services are internal, so **Try it out** won't reach them from a browser.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CORE_API_URL` | `http://localhost:8000` (Compose sets `http://api:3001`) | Core API base URL |
| `CORE_API_TOKEN` | required | Sent to the Core API |
| `INBOUND_TOKEN` | required | Expected from the Core API |
| `SEC_USER_AGENT` | empty | **Required for EDGAR.** Without it, EDGAR polls fail |
| `LOOKBACK_DAYS` | `30` | How far back each poll looks. Older events are never matched |
| `KEV_POLL_INTERVAL_S`, `EDGAR_POLL_INTERVAL_S` | `3600`, `900` | Poll intervals |
| `HOST`, `PORT` | `127.0.0.1`, `8002` (the image sets `0.0.0.0`) | Where the event API listens |
| `LOG_LEVEL` | `INFO` | Python logging level |
