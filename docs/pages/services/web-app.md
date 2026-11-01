# Web app

**Folder:** `web_app/`. **Stack:** Python 3.12, standard library only, so there's nothing to
install. **Port:** 8000 inside the stack, `/` through Caddy.

The web app is the browser UI (`/app/`) plus a small backend, the **Web App API** at
`/webapp/v1`, which the UI calls. The backend keeps no state of its own: every operation becomes
one or more Core API calls.

## How it's built

| File | What's in it |
|---|---|
| `secheck_web/__main__.py` | Entry point: `python -m secheck_web [--core-url URL] [--host H] [--port P] [--settings FILE] [--quiet]` |
| `secheck_web/app.py` | Builds the routes **from the contract**, checks who's signed in, validates requests against the spec, maps errors |
| `secheck_web/handlers/` | One function per `operationId` (`@operation("...")`), plus a few routes the spec doesn't have (`@extension(...)`) |
| `secheck_web/core_client.py` | The **only** module that knows Core API paths and field names |
| `secheck_web/audit.py` | The wording of the intake, edit and decision audit tickets, and the parser that reads decisions back |
| `secheck_web/validation.py` | A JSON Schema subset validator that runs on the contract |
| `secheck_web/web.py` | A small threaded HTTP server on `http.server` |
| `contracts/webapp_api.{yaml,json}` | The Web App OpenAPI contract the server runs on. **Generated, so don't edit it** (see below) |
| `config/settings.json` | Ports, Core URL, teams, development users, who may decide |
| `secheck_web/static/` | The UI: HTML, CSS and JS, with no build step |

The server routes requests from the contract:

- Each spec operation goes to the handler registered under its `operationId`.
- An operation with no handler answers `501 NOT_IMPLEMENTED`, and is listed at startup.
- Enums, lengths, patterns and required fields come from the contract. A spec change to one of
  those needs no code change.

## Functionality

- **Incidents:** manual intake, list, view, and edit the description or dependency. Each write
  adds an audit ticket.
- **Decisions:** record Materiality, Severity and Urgency with a rationale.
    - Only `decision_teams` may decide; any signed-in user can when that list is empty.
    - The first change to `MATERIAL` notifies every configured team through Core `/notifier`.
- **Tickets:** list them for an incident, create, view, edit (which adds a version), claim for
  one team, and notify teams.
- **Queue:** the tickets visible to a team, filtered by claim state.
- **Log:** the incident's ticket history. `/incidents/{id}/log/entries` (extension) gives each
  version in full.
- **Form 8-K view** (`MATERIAL` incidents only) assembles Item 1.05's content from the incident
  and its tickets:
    - **Nature:** the incident description plus the non-audit tickets.
    - **Scope:** severity, dependency and the teams involved.
    - **Timing:** discovered, determined, and an event list.
    - **Material impact:** the decision rationales.
- **Dependencies:** add, check and remove. Listing them is an extension.
- **Teams:** come from settings, not the Core API.

## Interfaces

**Web App API** (`/webapp/v1`): this is the contract the server runs on. If you're signed in to
the web app on the same host, **Try it out** sends real requests as that user, because the
session cookie is shared.

<swagger-ui src="../openapi/web_app/webapp_api.yaml"/>

**Routes the spec doesn't have** (extensions, all under `/webapp/v1`):

| Route | Auth | What |
|---|---|---|
| `GET /session` | yes | Who's signed in, their teams, and whether they may decide |
| `GET /dev/users` | no | The sign-in list. Only when `auth_mode` is `dev` |
| `GET /health` | no | Liveness, and whether the Core API answers. Any Core reply counts, even an error |
| `GET /dependencies` | yes | Every dependency (uses Core `LIST`) |
| `GET /incidents/{id}/log/entries` | yes | Every ticket version, with its details |

**Outside `/webapp/v1`:** `/` redirects to `/app/`; `/app/*` serves the UI; `/openapi.json`
returns the contract.

**Errors:**

- **Format:** the same envelope as the Core API, `{"Error", "Message"}`. Core errors pass through
  unchanged.
- **The web app's own errors:**

    | `Error` | Status |
    |---|---|
    | `UNAUTHORIZED` | 401 |
    | `FORBIDDEN` | 403 |
    | `NOT_FOUND` | 404 |
    | `METHOD_NOT_ALLOWED` | 405 |
    | `NOT_IMPLEMENTED` | 501 |
    | `UPSTREAM_UNAVAILABLE` | 502 |
    | `TIMEOUT` | 504 |

- **Multi-step operations:** when one fails partway, the error also has `Core_Path` and
  `Completed_Steps`, e.g. `["/incidents NEW"]`, because the steps already done aren't rolled
  back.

**Calls to the Core API:** every one carries `X-SECheck-Origin: webapp`. This lets a Core API
that forwards calls on to the web app ("gateway mode") avoid sending them back in a loop.

## Sign-in

**Sign-in is a development placeholder** (spec gap G-6):

- **Users:** you pick a name from `settings.json`. There are 4 sample users, plus a hidden
  `core-gateway` service user.
- **Requests:** the browser sends the name as `X-User` and as the `secheck_session` cookie.
- **No password**, so anyone who can reach the site can act as any user.

## Settings

The settings are in `config/settings.json`, and environment variables override them:

| Setting | Env var | Default |
|---|---|---|
| `host` / `port` | `SECHECK_HOST` / `SECHECK_PORT` | `127.0.0.1` / `8000` (the container sets `0.0.0.0`) |
| `core_api_url` | `CORE_API_URL` | `http://127.0.0.1:3001` (Compose sets `http://api:3001`) |
| `core_timeout_seconds` | `CORE_TIMEOUT_SECONDS` | `10` |
| `teams` | `SECHECK_TEAMS` (JSON list) | `["LEGAL","CYBER1","CYBER2"]`. Must match the Core API's teams |
| `users` | `SECHECK_USERS` (JSON object) | Sample users and their teams |
| `decision_teams` | `SECHECK_DECISION_TEAMS` | `[]`, meaning anyone may decide |
| `auth_mode` | `SECHECK_AUTH_MODE` | `dev` |
| `log_requests` | `SECHECK_LOG_REQUESTS` | `true`, which writes one line per request to stderr |

## Spec gaps

`G-1` … `G-10` in the code refer to the pod's list of ambiguities between the Web App and Core
specs. Each one is handled in `core_client.py`, so handlers see only Web App field names.

| Gap | What the code does |
|---|---|
| G-1 | The Incident_ID format is unclear; it generates 12-digit numbers |
| G-2 | The spec spells it `/dependencies` and `/dependancies`; it uses `/dependencies` |
| G-3 | Core says `Dependency`, the Web App says `Dependency_Name`; it maps between them |
| G-4 | Core ticket `EDIT` can't say which ticket; it sends `Ticket_number` |
| G-5 | Core has no list operations; it uses `Method: "LIST"`, which our Core API supports |
| G-6 | Authentication is undecided; it uses development sign-in |
| G-7 | Core can only `GET` the latest ticket version; it asks for strong IDs, and our Core API answers them |
| G-8 | No filing deadline from Core; `Filing_Deadline` is always `null` |
| G-9 | `Ticket_ID_List` may come as one comma-joined string; it splits it |
| G-10 | Core wants `Description` even on `GET`; it sends one |

## Changing the contract

The source spec and the generator live outside this repo, in the pod's `spec_docs/` and
`Web Dev/` folders:

1. Edit the spec there.
2. Run `python tools/sync_contracts.py` in `Web Dev/`. It regenerates `contracts/webapp_api.*`.
3. Run the web app tests in `Web Dev/` (`python -m unittest`).

A new operation needs an `@operation("<operationId>")` handler. A renamed Core field needs a
change in `core_client.py`.
