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

## Catch-up for new dependencies

When the Core API sends a `PUT` for a dependency, the worker wakes its poll loop and checks that
dependency right away, rather than at the next poll. The check runs on the poll loop's thread, so
it never overlaps a poll.

- **Window:** KEV is checked over its whole catalog (`full_history` on the source); EDGAR only over
  `LOOKBACK_DAYS`.
- **Events inside the window:** reported as usual, so teams are notified.
- **Older events:** reported with `backfill: true`, so they appear as incidents without a
  notification each. Low-confidence matches are skipped, because a name like `Microsoft` would
  otherwise add hundreds of old incidents.
- **Failures:** the dependency stays waiting and is tried again after the next poll of any source.
- **Restarts:** waiting checks are lost. Regular polls still cover the lookback window, but
  older KEV entries aren't checked again.
- **Removed dependencies:** a dependency removed before its check runs is skipped.

A repeat report can name a dependency the Core API hasn't seen on that incident. The Core API
adds it and notifies the teams again, so a dependency added later isn't missed
([Core API](core-api.md)).

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
service's `generate_models.sh` (`./verify.sh --fix generated` runs both).

## Matching (`matching.py`)

Matching uses names only, because the feeds give only names, and it never compares versions.

A dependency is one free-text name. The Core API splits it at `:`, or else at the first space,
which is often wrong: `Palo Alto Networks PAN-OS` gets the vendor `Palo`. So the rules also compare
the whole name. Vendor names are lowercased, reduced to letters and digits, stripped of suffixes
like *Inc*, *Corp* and *Systems*, and mapped through a short alias table (`_VENDOR_ALIASES`, for
example *International Business Machines* to *IBM*).

The rules are checked in this order:

| Rule | Example dependency and event | Confidence |
|---|---|---|
| The event's vendor CIK equals the dependency's `vendor_cik` (leading zeros ignored) | | high |
| Same vendor, and the event has no product (EDGAR) | `Microsoft Windows`, MICROSOFT CORP | medium |
| Same vendor, and the event's product is "Multiple Products" | `Microsoft`, Microsoft / Multiple Products | medium |
| Same vendor, and the dependency names no product | `Microsoft`, Microsoft / Windows | low |
| Same vendor and equal product names | `Microsoft Windows`, Microsoft / Windows | high |
| Same vendor, and one product name contains the other as whole consecutive words | `Cisco IOS`, Cisco / IOS and IOS XE | medium |
| Same vendor, otherwise | `Microsoft Office`, Microsoft / Windows | no match |
| Different vendor, and the whole name is the event's product, is within it, or starts with it | `Windows`, `MOVEit`, `Windows 11` | low |
| Otherwise | `Oracle:Java`, Sun / Java | no match |

The product-only rule never applies to generic names like `Server` (`_GENERIC_WORDS`). Because it
compares the whole name, a dependency that names another vendor doesn't match it.

Matches are sent strongest first, because the Core API shows the first as the incident's dependency.

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
| `LOOKBACK_DAYS` | `30` | How far back each poll looks. Older events are matched only by a new dependency's KEV catch-up |
| `KEV_POLL_INTERVAL_S`, `EDGAR_POLL_INTERVAL_S` | `3600`, `900` | Poll intervals |
| `KEV_URL`, `EDGAR_SEARCH_URL` | The real feeds | Only the end-to-end tests change these |
| `HOST`, `PORT` | `127.0.0.1`, `8002` (the image sets `0.0.0.0`) | Where the event API listens |
| `LOG_LEVEL` | `INFO` | Python logging level |
