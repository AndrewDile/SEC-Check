# CLAUDE.md

Context for Claude sessions working in this repo. Edit freely.

## Project

**SEC-Check** is a team project for ECE 30861. It is a workflow tool that helps companies track and manage cybersecurity incidents in line with the SEC cybersecurity disclosure rule (Form 8-K Item 1.05, Regulation S-K Item 106).

Core regulatory drivers (from `spec_docs/Requirements.txt`):
- A materiality determination must be made "without unreasonable delay" after an incident is discovered.
- An Item 1.05 Form 8-K is due within **four business days** of determining an incident is material.
- Companies must describe how they oversee risks from **third-party service providers**.

## This Directory: Web App

The project is split into components (see `spec_docs/system_overview.png`). **This Directory is Responsible for the Web App**: the browser-facing front end that handles the system workflow:
- Manual intake of incidents
- Incident info (view and edit incidents, tickets, logs)
- Decision and priority (materiality, severity, urgency)
- Queue and claim (team ticket queues)
- Dependencies (third-party dependency list)
- 8-K view (incident info organized by Form 8-K Item 1.05)

The Web App spec is `spec_docs/Web App API.txt` (Markdown copy in `data_schema_md/Web App API.md`).

## System architecture (from `spec_docs/system_overview.png`)

| Component | Role |
|---|---|
| Users | Browser over HTTPS. Auth method TBD. |
| **Web App** | Front end. Talks to Core API only. Receives claims from teams. |
| Core API | OpenAPI REST. Logs reads and writes. The single way into the data. |
| Database | dependencies, incidents, incident_info, teams, claims, decisions + priority, audit_log (hash-chained), business_calendar |
| Ingestion worker | Polls the 3rd-party tracker / incident feed and matches against dependencies |
| Deadline scheduler | Tracks the 4-business-day deadline; sends due/overdue to Core API |
| Notification service | Sends alerts and deadlines to teams. Channel TBD. |
| All teams | Receive alerts, claim tickets back through the Web App |
| API test clients | Testing only, not prod. Use OpenAPI against Core API. |

Agreed approach: an internal API for accessing all services and data; the external API is proxied through it, which gives testers access to the system.

**Rule: the Web App never touches the database directly. Everything goes through the Core API.**

## Requirements (summary of `spec_docs/Requirements.txt`)

| ID | Requirement |
|---|---|
| REQ-01 | Ingest and store cybersecurity incidents |
| REQ-02 | Log user actions and accesses to tickets immutably |
| REQ-03 | Tickets can be marked material/immaterial and given a priority |
| REQ-04 | Notify all teams; one team claims; submit info within 4 days |
| REQ-05 | Monitor 3rd-party dependency vulnerabilities and ingest them |
| REQ-06 | Organize incident info per Form 8-K Item 1.05 (no auto-filing) |

Acceptance criteria AC-01 to AC-06 map 1:1 to these requirements and are in `spec_docs/Requirements.txt`. Notable ones for the Web App:
- AC-02: logs must be in timestamp order with one universal time zone.
- AC-06: 8-K view must reject incidents not marked material.

## Core API (summary of `spec_docs/API Spec.txt`)

All paths are `POST` with a `Method` field in the body:

| Path | Methods | Req |
|---|---|---|
| `/incidents` | NEW, EDIT, GET | REQ-01 |
| `/tickets` | NEW, EDIT, GET (edit creates a new version; old kept in log) | REQ-02, REQ-03 |
| `/notifier` | CLAIM, NOTIFY | REQ-04 |
| `/logs` | (none) returns incident + list of ticket IDs | REQ-06 |
| `/dependencies` | NEW, MATCH, REMOVE (lowercase `dp_name`, `method`) | REQ-05 |
| `/reset` | RESET (testing only) | - |

Key types: `Materiality_type {MATERIAL, IMMATERIAL, UNDECIDED}`, `Severity_type {HIGH, MEDIUM, LOW, UNDECIDED, RESOLVED}`, `Urgency_type {URGENT, NOT_URGENT, UNDECIDED, RESOLVED}`, `Error_type {UUID_EXISTS, UUID_DNE, INVALID_DATA, DP_EXISTS, DP_DNE, TIMEOUT}`.

Ticket IDs: weak = `<Incident_ID>_<n>` (e.g. `102356304331_1`), strong = `<Incident_ID>_<n>_<version>`.

Errors are `{ "Error": <Error_type>, "Message": "..." }` with HTTP 400.

## Web App API design decisions

- Base path `/webapp/v1`, REST-style resources for the browser; each endpoint maps to one or more Core API calls (mapping table in section 2 of the spec).
- Same field names, enums and error envelope as Core. Web-only errors: `UNAUTHORIZED` (401), `FORBIDDEN` (403), `UPSTREAM_UNAVAILABLE` (502); `TIMEOUT` is 504.
- Web App sets all Core `Timestamp` values itself in UTC (except optional discovery time on intake).
- Materiality/severity/urgency change only via `PUT /incidents/{id}/decision`, which requires a `Rationale` and writes a decision audit ticket. Marking MATERIAL notifies all teams.
- Every user action creates an audit ticket so it lands in the immutable log.
- A claim is exactly one team.
- Multi-step operations return `Completed_Steps` on partial failure (Core has no transactions).
- `/reset` is not exposed.

## Open gaps with the Core API

Section 7 of `spec_docs/Web App API.txt` lists G-1 to G-12. The most important:
- **G-1** Incident_ID type conflicts (uuid vs integer vs numeric string). Web App uses digit string.
- **G-4** `/tickets` EDIT has no way to name which ticket.
- **G-5** No list/query operations (incidents, team queue, dependencies, teams). `GET /incidents` and `GET /queue` are marked PROPOSED.
- **G-6** No actor/user field on Core requests (needed for REQ-02).
- **G-8** Filing deadlines are not exposed by Core; `Filing_Deadline` is null for now.

When the Core API spec is updated, re-check these gaps and update the Web App spec.

## Web App implementation (`web_app/`) and test harness (`Web Dev/`)

History and decisions: `initial_implementation.md`. Guides: `web_app/README.md` (the app, Docker) and `Web Dev/README.md` (harness, tests).

- **`web_app/`** is the Web App, deployed as its own Docker container (`web` service in `docker-compose.yml`, port 8000, `CORE_API_URL=http://api:3001`). Python 3.9+ standard library only. Entry point: `python -m secheck_web`. It must not depend on anything in `Web Dev/`.
- **`Web Dev/`** is the test harness: mock Core API (`mock_core/`), tests, tools, and `run.py` for local dev (Web App from `../web_app` + mock Core API on :8001 -> http://localhost:8000/app/; real Core API: `--core-url URL`). It imports the app via `devpath.py`; mock-only settings live in `dev_settings.py` (`DevSettings`).
- Tests: `python -m unittest` in `Web Dev/`. They check Web App responses against `web_app/contracts/webapp_api.json` and every Core request against `Web Dev/contracts/core_api.json`.
- Spec-driven: routes and validation come from `web_app/contracts/webapp_api.json`; handlers are registered by `operationId` in `web_app/secheck_web/handlers/`. After a spec change run `python tools/sync_contracts.py` in `Web Dev/` (needs PyYAML; reads `spec_docs/`, writes both contract folders), then the tests.
- `web_app/secheck_web/core_client.py` is the ONLY place that knows Core API paths and field names.
- The team's real Core API is in `api/` (TypeScript/Express, port 3001). As of this writing its operations are stubs that return `501 NOT_IMPLEMENTED`.
- Extensions not yet in the spec: `GET /session`, `GET /dev/users`, `GET /health`, `GET /dependencies` (list), `GET /incidents/{id}/log/entries` (every log entry with details; fetches each version from Core `/tickets GET` by Ticket_type_strong, the gap G-7 fix, with a fallback). Core `Method: "LIST"` is a proposed extension (gap G-5), supported by the mock only.
- Sign-in is a dev placeholder (X-User header / `secheck_session` cookie). Locally keep the server bound to 127.0.0.1; don't expose the container publicly until real auth exists.
- **Gateway mode** (default under `run.py`): Core API calls from test clients are forwarded by the mock Core API to the Web App as Web App API requests (`Web Dev/mock_core/gateway.py`). The Web App marks its own Core calls with `X-SECheck-Origin: webapp` so they are stored, not forwarded (prevents a loop). Service user `core-gateway`. `--mock-local` turns it off.
- `tests/current_tests.md` documents every test as HTTP requests and expected responses; regenerate with `python tools/document_tests.py`.

## Repo layout

```
SEC-Check/
  spec_docs/                    Specification documents (source of truth)
    API Spec.txt                Core API spec (team-owned)
    Data Schema & Examples.txt  Field-level schema + request/response examples
    Requirements.txt            REQ-01..06 and AC-01..06
    Web App API.txt             Web App API spec
    system_overview.png         Architecture diagram
  data_schema_md/               Markdown copies of the specs (derived)
    API Spec.md                 from spec_docs/API Spec.txt
    Web App API.md              from spec_docs/Web App API.txt
  web_app/                      Web App: its own Docker container (see its README.md)
  Web Dev/                      Test harness: mock Core API, tests, tools, local run.py (see its README.md)
  api/                          Core API (team-owned, TypeScript; its own container)
  docker-compose.yml            api + web services
  initial_implementation.md     What the first implementation added and why
  README.md
  CLAUDE.md
```

## Working rules

- **Do not modify, move or delete anything in `spec_docs/`** unless explicitly asked. Those files are the source of truth.
- The `.md` files in `data_schema_md/` are derived copies. If a `.txt` spec changes, regenerate the matching `.md` so they stay in sync. Spec text and OpenAPI blocks are copied verbatim.
- Field names must match the Core API exactly (including mixed case like `Incident_ID`, `ticket_severity`, `dp_name`).
- Git: Web App work happens on the `web_app_dev` branch; `main` is shared. Don't commit or push unless asked.
