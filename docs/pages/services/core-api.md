# Core API

**Folder:** `api/`. **Stack:** Express 5 on Node 24, TypeScript, MySQL through `mysql2`.
**Port:** 3001 inside the stack, `/system/` through Caddy.

The Core API owns the data and implements the pod's Core API contract (v1.0.2, which added `/teams` and
`/users`). It also adds:

- `LIST` methods the web app needs
- the cross-team testing endpoints, with a separate copy of the data per test session
- private endpoints for the ingestion worker and notification service

| File | What's in it |
|---|---|
| `src/coreapi.ts` | Express app, scope and actor middleware, validation, the pod contract endpoints, error handler |
| `src/context.ts` | The request's scope and actor (`AsyncLocalStorage`), which every database method reads |
| `src/db/api.ts` | The `Database` interface and domain types. Each method notes the errors it can throw |
| `src/db/mysql.ts` | `MySqlDb`, the MySQL implementation, with the audit chain and transactions |
| `src/db/migrate.ts` | Applies `db/migrations/*.sql` at startup, each once |
| `src/calendar.ts` | Business days for the Form 8-K filing deadline |
| `src/services.ts` | `/ingest/*` and `/notif/*`, and the outbound calls to the worker and notifier |
| `src/testing.ts` | `/test/setup` and `/test/report` for the cross-team tester, and test session limits |
| `src/coverage.ts` | Per-session code coverage from V8 |
| `src/metrics.ts` | Request log lines and per-session request timings |

There is no OpenAPI file for the pod contract in this repo; the pod keeps it. The endpoints the
worker and notifier call are in their `core_api.openapi.yaml` files, shown on the
[ingestion worker](ingestion-worker.md#interfaces) and
[notification service](notification-service.md#interfaces) pages.

## Conventions

- **Requests:** every pod endpoint is a `POST`, with the operation in the body's `Method` field
  (`method` for `/dependencies`).
- **Headers:**
    - `X-Session-ID` runs the request in that test session's data. A session that isn't active
      gives `INVALID_DATA`. Without it, the request uses the real data.
    - `X-User` names who is acting, for the audit log. It must be a user of that data
      (`INVALID_DATA` otherwise). Without it the actor is `Unknown`. It isn't authenticated.
- **Timestamps:** `Timestamp` must be RFC 3339 and at most 5 seconds in the future. It is
  checked on every method except `LIST`.
- **Errors:** status 400 and `{"Error": "<type>", "Message": "..."}`. The types are
  `INVALID_DATA`, `UUID_EXISTS`, `UUID_DNE`, `DP_EXISTS`, `DP_DNE`, `TEAM_EXISTS`, `TEAM_DNE`,
  `USER_EXISTS` and `USER_DNE`.
    - Body that isn't valid JSON: `INVALID_DATA`.
    - Anything unexpected: 500 `INTERNAL_ERROR`, logged to stderr.
    - Under `/test/` errors use the tester's format instead: `{"message": "...", "source": "system"}`.
- **Validation:**
    - `Incident_ID`: non-empty, no `_`, at most 64 characters.
    - `Description`: at most 5000 characters.
    - Team names on `/tickets` (`Team_list`) and `/notifier` (`Team_Names`) must be teams that
      exist, i.e. were created through `/teams` or restored by a reset. Others: `INVALID_DATA`.
    - Any field too long for its column: `INVALID_DATA`.
- **Transactions:** each database method runs in one transaction, audit entry included, and is
  retried up to 5 times on a deadlock. A response is built from what that one transaction read.

## Pod contract endpoints

### `POST /incidents`

| Method | Needs | Does | `Status` |
|---|---|---|---|
| `NEW` | `Incident_ID`, `Timestamp`, `Description`; optional `Dependency` (or `Dependency_Name`), `Materiality`, `Severity`, `Urgency` | Creates an incident. Missing decision fields default to `UNDECIDED` | `Created` |
| `EDIT` | `Incident_ID`, `Timestamp`, `Description`; optional fields as for `NEW`, and `Note` | Updates the fields it's given. `Dependency: ""` clears the dependency. Changing `Materiality` away from `MATERIAL` needs a `Note` (`INVALID_DATA` without one) | `Edited` |
| `GET` | `Incident_ID`, `Timestamp` | Returns the incident, and audits the read | `Data Fetched` |
| `LIST` | nothing | Every incident (extension for the web app), audited as one `INCIDENTS_LISTED` | `Listed` |

The response has `Incident_ID`, `Description`, `Dependency` (when set), `Materiality`,
`Severity`, `Urgency` and `Timestamp`. While the incident is `MATERIAL` it also has
`Filing_Deadline` (`YYYY-MM-DD`, extension): 4 business days after the first `MATERIAL`
determination, which later changes never restart (see [Data model](../data-model.md)). `LIST`
returns `{"Incidents": [...]}`.

`Note` is an extension: the reason for the edit, stored in the audit entry.

### `POST /tickets`

| Method | Needs | Does | `Status` |
|---|---|---|---|
| `NEW` | `Incident_ID`, `Timestamp`, `Description`; optional `Ticket_severity`, `Ticket_urgency`, `Team_list` | Creates the next ticket number, at version 1 | `Logged` |
| `EDIT` | `Incident_ID`, `Timestamp`, `Ticket_number`, `Description`; optional fields as for `NEW` | Adds a new version, keeping the fields it isn't sent | `Edited` |
| `GET` | `Incident_ID`, `Timestamp`, `Ticket_number` | A weak ID (`<id>_<n>`) or bare number gives the latest version; a strong ID (`<id>_<n>_<v>`), as `/logs` lists them, gives that version | `Displayed` |
| `LIST` | optional `Team`, `Ticket_Claim` (`CLAIMED` or `UNCLAIMED`) | The latest version of every ticket, filtered (extension for the web app), audited as one `TICKETS_LISTED` | `Listed` |

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
| `CLAIM` | `Ticket_Number`, `Team_Names` with exactly one team | Claims the ticket. Fails with `INVALID_DATA` if another team holds it. Of two teams claiming at once, one wins | `Claimed ticket` |

It returns `{"UUID", "Ticket_Number", "Status"}`. `UUID` is a number when the incident ID is
all digits (at most 15), so that it matches the contract's examples.

### `POST /logs`

It needs `Incident_ID` and `Timestamp`. It returns the incident's description, its decision
fields, and:

- `Ticket_ID_List`: every ticket version's strong ID, in the order they were created.
- `Audit_Log` (extension): the incident's audit entries, oldest first, as `{"Seq", "Timestamp",
  "Event", "Actor", "Details"}`. The read itself is audited as `LOG_READ`, after the entries are
  read.

### `POST /teams`

| `Method` | Needs | Does | `Status` |
|---|---|---|---|
| `NEW` | `Team_Name` | Creates the team (`TEAM_EXISTS` if it's already there) | `Created` |
| `REMOVE` (or `DELETE`) | `Team_Name` | Removes it and its memberships (`TEAM_DNE` if it isn't there). A team that tickets, notifications or claims refer to stays: `INVALID_DATA` | `Removed` |
| `GET` | `Team_Name` | Checks it exists (`TEAM_DNE` if not), and returns its `Members` (extension) | `Team Received` |
| `LIST` | nothing | Every team name, oldest first, as `Team_List` | `Teams Listed` |
| `ADD_USER` | `Team_Name`, `Username` | Adds the user to the team. `TEAM_DNE`, `USER_DNE` if the user doesn't exist, `USER_EXISTS` if they're already a member | `User added` |
| `REMOVE_USER` | `Team_Name`, `Username` | Takes the user off the team. `TEAM_DNE`, `USER_DNE` if they aren't a member | `User removed` |

`Team_Name` is 1-64 characters with no leading or trailing spaces, and required for every
method except `LIST`. The response has `Status`, plus `Team_Name` (every method except `LIST`),
`Team_List` (`LIST`), `Members` (`GET`) and `Username` (`ADD_USER`/`REMOVE_USER`).

### `POST /users`

| `Method` | Needs | Does | `Status` |
|---|---|---|---|
| `NEW` | `Username`, `Auth_Hash`; optional `Contact` | Creates the user (`USER_EXISTS` if it's already there). `Unknown`, `ingestion-worker` and `notification-service` are reserved | `Created` |
| `EDIT` | `Username`; optional `Auth_Hash` (replaces the stored credential), `Contact` | Updates them (`USER_DNE`) | `Edited` |
| `REMOVE` (or `DELETE`) | `Username` | Removes the user and their memberships (`USER_DNE`) | `Removed` |
| `GET` | `Username` | The user (`USER_DNE`), extension | `User Received` |
| `LIST` | nothing | Every user, as `Users`, extension | `Users Listed` |

`Contact` is where the user's notifications go. Two optional extensions go with it:
`Contact_Channel`, the notification service channel (default `log`, the only one that delivers
anything today), and `Display_Name`. The response is `{"Username", "Status"}` plus, except for
`REMOVE`, `Contact`, `Contact_Channel`, `Display_Name` and `Teams`.

`Auth_Hash` is never returned. It's stored salted and hashed again with scrypt, since whatever
the client sends works like a password. Nothing checks it yet: sign-in is planned for Phase 5.

### `POST /dependencies` (also `/dependancies`)

The contract spells the path both ways, so both work. It uses lowercase `method` and `dp_name`.

| `method` | Does | `status` |
|---|---|---|
| `NEW` | Adds the dependency (`DP_EXISTS` if it's already there) and, for the real data, tells the worker | `Added` |
| `MATCH` | Checks whether it exists | `Exists` or `Does not Exist` |
| `REMOVE` | Removes it (`DP_DNE` if it isn't there) and, for the real data, tells the worker | `Removed` |
| `LIST` | Every dependency name (extension) | `Listed` |

A test session's dependencies never reach the worker, so tests can't make it match real feeds.

### `POST /reset`

Send `{"method": "RESET"}`. It deletes the request's data and restores its default teams, users
and audit genesis:

- **With `X-Session-ID`:** only that test session's data.
- **Without:** the real data, and it tells the worker to delete every dependency.

It returns `{"status": "DB Wiped"}`. **It takes no authentication**, so anyone can wipe the real
data; this is on the list for the pod (see [Known limitations](../limitations.md#for-the-pod)).

### `GET /health`

Always `{"status": "ok"}`. It doesn't check the database.

## Cross-team testing endpoints

These follow the course's cross-team testing interface (`src/testing.ts`). Each session gets its
own copy of the data (a scope), so sessions run in parallel and never touch the real data.

- **`POST /test/setup`:** send `{"session_id": "...", "setup": {...}?}`.
    - Creates the session's data with the default teams and users, and starts measuring it.
    - Returns 201 `{"session_id"}`.
    - Session IDs are single use: an active or earlier session's ID gives 409.
    - Limits: at most `MAX_TEST_SESSIONS` active sessions and `SETUPS_PER_MINUTE` setups per
      client IP; past either, 429.
- **Requests in the session** send `X-Session-ID: <session_id>`.
- **`GET /test/report?session_id=...`:** ends the session and returns its report:
    - `coverage.code`: `covered` and `total` lines inside functions of the compiled build
      (`dist/`) that ran between setup and report, from V8's precise coverage. V8 can't tell
      requests apart, so sessions running at the same time count each other's lines; `basis` names
      them. It's `null` when the API isn't running its compiled build or `CODE_COVERAGE=off`.
    - `metrics.requests`: per operation (path and `Method`), `count`, `errors` (status 400 or
      more), and `p50_ms`, `p95_ms` and `max_ms`.

    Asking again returns the stored report. An ID that was never set up gives 404.

A session idle for `SESSION_IDLE_MINUTES` ends by itself, with `metrics.ended: "idle"`. An ended
session's data is deleted `SESSION_IDLE_MINUTES` after it ends; its row in `test_sessions` and its
report stay. A restart ends every open session.

## Private endpoints for our services

| Endpoint | Token | Does |
|---|---|---|
| `GET /ingest/dependencies` | `INGEST_CORE_API_TOKEN` | Every dependency, as the worker's `Dependency` |
| `POST /ingest/incidents` | `INGEST_CORE_API_TOKEN` | See below |
| `POST /notif/notifications/{id}/results` | `NOTIF_CORE_API_TOKEN` | Stores the delivery results as a `NOTIFICATION_RESULTS` audit entry. 404 if `{id}` isn't an ingested incident |

The token also sets the audit log's actor: `ingestion-worker` or `notification-service`.

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
    - It sends the notification service one `Recipient` per team member, at the member's
      contact channel and address (the username when there's no address). A team with no
      members gets one recipient with `channel: "log"` and the team name as the address.
    - `claim_url` is `${WEB_APP_URL}/app/#/incidents/<id>`.
    - It writes a `NOTIFICATION_SENT` audit entry.

## Observability

Every request writes one JSON line to stdout (see the log viewer at `/logs/`):
`{"at", "operation", "status", "ms", "session"?, "user"?}`. `operation` is the route and `Method`,
e.g. `/incidents NEW`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `3001` | Listen port |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | `localhost`, `3306`, `seccheck` | MySQL |
| `DB_POOL_SIZE` | `10` | MySQL connections |
| `MIGRATIONS_DIR` | `../db/migrations` from the API (Compose mounts it at `/migrations`) | Migrations applied at startup |
| `WORKER_URL`, `NOTIFIER_URL` | unset | Where to send dependency events and notifications. Unset means skip |
| `WEB_APP_URL` | `http://localhost:8000` (Compose sets `http://localhost`) | Base of claim links |
| `INGEST_*_TOKEN`, `NOTIF_*_TOKEN` | none | See [Architecture](../architecture.md#service-to-service-authentication) |
| `SESSION_HEADERS` | `x-session-id` | Comma-separated headers a request may name its test session in |
| `MAX_TEST_SESSIONS` | `10` | Active test sessions at once |
| `SESSION_IDLE_MINUTES` | `30` | When an idle session ends, and how long after ending its data is deleted |
| `SETUPS_PER_MINUTE` | `20` | `/test/setup` calls per client IP per minute |
| `CODE_COVERAGE` | on | `off` stops measuring code coverage |

## Tests

`api/test/` holds 64 vitest tests:

- **`calendar.test.ts`:** 2 unit tests of the filing deadline's business days. They always run.
- **`db.test.ts`:** 24 tests of `MySqlDb` against a real MySQL. They skip unless `DB_USER` is set.
- **`api.test.ts`:** 38 HTTP tests against a running API. They skip unless `API_URL` is set.

The last two wipe the real data. `./test.sh` sets the variables and runs them all. See
[Testing](../testing.md).
