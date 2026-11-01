# Core API

**Folder:** `api/`. **Stack:** Express 5 on Node 24, TypeScript, MySQL through `mysql2`.
**Port:** 3001 inside the stack, `/system/` through Caddy.

The Core API owns the data and implements the pod's Core API contract (v1.0.0). It also adds:

- `LIST` methods the web app needs
- the cross-team testing endpoints
- private endpoints for the ingestion worker and notification service

| File | What's in it |
|---|---|
| `src/coreapi.ts` | Express app, validation, the pod contract endpoints, error handler |
| `src/db/api.ts` | The `Database` interface and domain types. Each method notes the errors it can throw |
| `src/db/mysql.ts` | `MySqlDb`, the MySQL implementation, with the audit chain and transactions |
| `src/services.ts` | `/ingest/*` and `/notif/*`, and the outbound calls to the worker and notifier |
| `src/testing.ts` | `/test/setup` and `/test/report` for the cross-team tester |

There is no OpenAPI file for the pod contract in this repo; the pod keeps it. The endpoints the
worker and notifier call are in their `core_api.openapi.yaml` files, shown on the
[ingestion worker](ingestion-worker.md#interfaces) and
[notification service](notification-service.md#interfaces) pages.

## Conventions

- **Requests:** every pod endpoint is a `POST`, with the operation in the body's `Method` field
  (`method` for `/dependencies`).
- **Timestamps:** `Timestamp` must be RFC 3339 and at most 5 seconds in the future. It is
  checked on every method except `LIST`.
- **Errors:** status 400 and `{"Error": "<type>", "Message": "..."}`. The types are
  `INVALID_DATA`, `UUID_EXISTS`, `UUID_DNE`, `DP_EXISTS` and `DP_DNE`.
    - Body that isn't valid JSON: `INVALID_DATA`.
    - Anything unexpected: 500 `INTERNAL_ERROR`, logged to stderr.
    - Under `/test/` errors use the tester's format instead: `{"message": "...", "source": "system"}`.
- **Validation:**
    - `Incident_ID`: non-empty, no `_`, at most 64 characters.
    - `Description`: at most 5000 characters.
    - Unknown team names: `INVALID_DATA`.
    - Any field too long for its column: `INVALID_DATA`.
- **Transactions:** each database method runs in one transaction and is retried up to 5 times
  on a deadlock.

## Pod contract endpoints

### `POST /incidents`

| Method | Needs | Does | `Status` |
|---|---|---|---|
| `NEW` | `Incident_ID`, `Timestamp`, `Description`; optional `Dependency` (or `Dependency_Name`), `Materiality`, `Severity`, `Urgency` | Creates an incident. Missing decision fields default to `UNDECIDED` | `Created` |
| `EDIT` | `Incident_ID`, `Timestamp`, `Description`; optional fields as for `NEW` | Updates the fields it's given. `Dependency: ""` clears the dependency | `Edited` |
| `GET` | `Incident_ID`, `Timestamp` | Returns the incident, and audits the read | `Data Fetched` |
| `LIST` | nothing | Every incident (extension for the web app) | `Listed` |

The response has `Incident_ID`, `Description`, `Dependency` (when set), `Materiality`,
`Severity`, `Urgency` and `Timestamp`. `LIST` returns `{"Incidents": [...]}`.

### `POST /tickets`

| Method | Needs | Does | `Status` |
|---|---|---|---|
| `NEW` | `Incident_ID`, `Timestamp`, `Description`; optional `Ticket_severity`, `Ticket_urgency`, `Team_list` | Creates the next ticket number, at version 1 | `Logged` |
| `EDIT` | `Incident_ID`, `Timestamp`, `Ticket_number`, `Description`; optional fields as for `NEW` | Adds a new version, keeping the fields it isn't sent | `Edited` |
| `GET` | `Incident_ID`, `Timestamp`, `Ticket_number` | A weak ID (`<id>_<n>`) or bare number gives the latest version; a strong ID (`<id>_<n>_<v>`) gives that version | `Displayed` |
| `LIST` | optional `Team`, `Ticket_Claim` (`CLAIMED` or `UNCLAIMED`) | The latest version of every ticket, filtered (extension for the web app) | `Listed` |

The response has:

- **IDs:** `Ticket_ID` (strong) and `Ticket_number` (weak).
- **Incident fields:** `UUID_Description`, `Materiality_type`, `uuid_severity`, `uuid_urgency`.
- **Ticket fields:** `Ticket_Description`, `ticket_severity`, `ticket_urgency`, `Team_List`.
- **Claim:** `Ticket_Claim`, plus `Claimed_By` when the ticket is claimed.
- `Timestamp`.

### `POST /notifier`

| Method | Needs | Does | `Status` |
|---|---|---|---|
| `NOTIFY` | `Ticket_Number` (weak), `Team_Names` (non-empty) | Records one notification per team, in the database only | `Notified team` |
| `CLAIM` | `Ticket_Number`, `Team_Names` with exactly one team | Claims the ticket. Fails with `INVALID_DATA` if another team holds it | `Claimed ticket` |

It returns `{"UUID", "Ticket_Number", "Status"}`. `UUID` is a number when the incident ID is
all digits (at most 15), so that it matches the contract's examples.

### `POST /logs`

It needs `Incident_ID` and `Timestamp`. It returns the incident's description, its decision
fields, and `Ticket_ID_List`: every ticket version's strong ID, in the order they were created.
This is the ticket history, **not** the audit log. The audit log has no endpoint yet.

### `POST /dependencies` (also `/dependancies`)

The contract spells the path both ways, so both work. It uses lowercase `method` and `dp_name`.

| `method` | Does | `status` |
|---|---|---|
| `NEW` | Adds the dependency (`DP_EXISTS` if it's already there) and tells the worker | `Added` |
| `MATCH` | Checks whether it exists | `Exists` or `Does not Exist` |
| `REMOVE` | Removes it (`DP_DNE` if it isn't there) and tells the worker | `Removed` |
| `LIST` | Every dependency name (extension) | `Listed` |

### `POST /reset`

Send `{"method": "RESET"}`. It truncates every table, restores the default teams and the audit
genesis, and tells the worker to delete every dependency. It returns `{"status": "DB Wiped"}`.
**It takes no authentication.**

### `GET /health`

Always `{"status": "ok"}`. It doesn't check the database.

## Cross-team testing endpoints

These follow the course's cross-team testing interface (`src/testing.ts`):

- **`POST /test/setup`:** send `{"session_id": "...", "setup": {...}?}`.
    - Wipes the database the way `/reset` does, and makes this session the active one.
    - Returns 201 `{"session_id"}`.
    - Setups run one at a time. Reusing the active session's ID gives 409.
- **`GET /test/report?session_id=...`:** 404 for anything but the active session. Otherwise it
  returns `{"session_id", "coverage": {"code": ...}}`, where code coverage is `null` because it
  isn't measured.

There's one session at a time. A new setup replaces the old one, and the `X-Session-ID` header
on project calls is ignored.

## Private endpoints for our services

| Endpoint | Token | Does |
|---|---|---|
| `GET /ingest/dependencies` | `INGEST_CORE_API_TOKEN` | Every dependency, as the worker's `Dependency` |
| `POST /ingest/incidents` | `INGEST_CORE_API_TOKEN` | See below |
| `POST /notif/notifications/{id}/results` | `NOTIF_CORE_API_TOKEN` | Stores the delivery results as a `NOTIFICATION_RESULTS` audit entry. 404 if `{id}` isn't an ingested incident |

`POST /ingest/incidents` works like this:

1. It checks that `source`, `external_id`, `title`, `summary`, `source_url` and `detected_at`
   are strings.
2. A repeat `(source, external_id)` returns 200 with the stored payload, and nothing else
   happens.
3. Otherwise it creates an incident with a random 12-digit ID. A collision is retried up to 5
   times.
    - **Description:** `title`, `summary` and the source URL, cut to 5000 characters.
    - **Dependency:** the first matched dependency.
4. It returns 201 with the payload plus `id` and `created_at`.
5. It then notifies the teams:
    - It sends the notification service one `Recipient` per team, with `channel: "log"` and
      the team name as the address.
    - `claim_url` is `${WEB_APP_URL}/app/#/incidents/<id>`.
    - It writes a `NOTIFICATION_SENT` audit entry.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `3001` | Listen port |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | `localhost`, `3306`, `seccheck` | MySQL |
| `WORKER_URL`, `NOTIFIER_URL` | unset | Where to send dependency events and notifications. Unset means skip |
| `WEB_APP_URL` | `http://localhost:8000` (Compose sets `http://localhost`) | Base of claim links |
| `INGEST_*_TOKEN`, `NOTIF_*_TOKEN` | none | See [Architecture](../architecture.md#service-to-service-authentication) |

## Tests

`api/test/` holds 36 vitest tests:

- **`db.test.ts`:** 16 tests of `MySqlDb` against a real MySQL. They skip unless `DB_USER` is set.
- **`api.test.ts`:** 20 HTTP tests against a running API. They skip unless `API_URL` is set.

Both wipe the database. `./test.sh` sets the variables and runs both. See [Testing](../testing.md).
