# Initial implementation: Web App

First working version of the Web App, built from `spec_docs/Web App API.txt`. All code is in **`Web Dev/`**; see `Web Dev/README.md` for how to run, test and change it.

**Existing files:** the spec documents (now in `spec_docs/`) and the Markdown copies (now in `data_schema_md/`) were not modified. `CLAUDE.md` got a short "Web App implementation" section and an updated repo layout.

## Quick start

```
cd "Web Dev"
run.bat            # or: python run.py
```

Open http://localhost:8000/app/ and pick a user. A mock Core API starts alongside it on port 8001. Run tests with `test.bat` (or `python -m unittest`).

## Approach and why

The brief asked for three things: easy deployment, easy testing through the Core API, and easy change, since the OpenAPI spec will change.

| Goal | What was done |
|---|---|
| **Ease of deployment** | Python standard library only: no `pip install`, no build step, no database. One command (`run.bat` / `python run.py`) starts everything. The browser app is plain HTML/CSS/JS served by the same process. An optional `Dockerfile` is included. |
| **Testing through the Core API** | A **mock Core API** (`mock_core/`) implements `API Spec.txt` in memory and **rejects any request that doesn't match the Core contract**. Point the Web App at the real Core API with `--core-url`. `tools/smoke_test.py` runs a full workflow through the Web App, then queries the Core API directly to confirm the data landed. The automated tests check every Core request against the Core contract. |
| **Changeability** | The server is **driven by the OpenAPI contract**: routes, path/query/body validation and `/openapi.json` all come from `contracts/webapp_api.json`, and handlers are wired up by `operationId`. The front end reads enum values from the contract. All Core API paths and field names live in one file (`secheck_web/core_client.py`). `tools/sync_contracts.py` regenerates the contracts from the spec documents, and the tests flag any drift (missing handlers, orphaned handlers, out-of-date contracts, Core requests that break the Core contract). |

The standard-library choice was also practical: package installs were blocked in both environments available while building this, and a zero-dependency app sidesteps the same problem on any teammate's or grader's machine.

## What was added

```
initial_implementation.md        this file
Web Dev/
  README.md                      run / test / change guide
  run.py, run.bat, run.sh        start Web App (+ mock Core API)
  test.bat, test.sh              run the test suite
  Dockerfile, .gitignore
  config/settings.json           ports, Core URL, teams, dev users, decision permissions
  contracts/
    webapp_api.yaml / .json      extracted from "spec_docs/Web App API.txt" section 5
    core_api.yaml / .json        extracted from "spec_docs/API Spec.txt" (repaired copy, see below)
  secheck_web/
    app.py                       spec-driven router, auth, validation, error envelope
    core_client.py               Core API adapter (only place with Core field names)
    handlers/                    incidents.py, tickets.py, dependencies.py, teams.py
    audit.py                     audit-ticket wording (INTAKE / EDIT / DECISION)
    validation.py                OpenAPI/JSON-schema subset validator
    errors.py, config.py, web.py
    static/                      index.html, app.js, styles.css, docs.html
  mock_core/                     server.py (in-memory Core API), __main__.py
  tests/                         58 unittest tests + contract checks
  tools/sync_contracts.py        regenerate contracts from spec documents
  tools/smoke_test.py            end-to-end check against running servers
```

## Spec coverage

All 18 operations in the Web App spec are implemented.

| Web App endpoint | Status |
|---|---|
| `POST /incidents` (intake) | Done. Generates a 12-digit ID if none is given; checks the dependency exists; logs an INTAKE audit ticket |
| `GET /incidents` (list) | Done. Uses a proposed Core `LIST` method (gap G-5); the mock supports it |
| `GET /incidents/{id}` | Done |
| `PATCH /incidents/{id}` | Done. Rejects decision fields; logs an EDIT audit ticket |
| `PUT /incidents/{id}/decision` | Done. Rationale required; DECISION audit ticket; notifies all teams on first MATERIAL; optional team restriction (`decision_teams`) |
| `GET/POST /incidents/{id}/tickets` | Done. `expand=true` fetches each ticket; create can notify assigned teams |
| `GET/PATCH /incidents/{id}/tickets/{n}` | Done. Edit creates a new version |
| `POST /tickets/{n}/claim` | Done. Exactly one team; user must be a member |
| `POST /tickets/{n}/notify` | Done |
| `GET /queue` | Done. Uses a proposed Core `LIST` method (gap G-5) |
| `GET /incidents/{id}/log` | Done. Normalises the comma-joined `Ticket_ID_List` (gap G-9) |
| `GET /incidents/{id}/form-8k` | Done. Rejects non-MATERIAL incidents (AC-06) |
| `POST/GET/DELETE /dependencies` | Done |
| `GET /teams` | Done (from settings) |

The browser app covers the same workflows: an incident list with intake form; an incident page with a materiality band, decision form, ticket timeline (claim, notify, update), new-ticket form, full log and 8-K view (with "copy as text"); a team queue with claim buttons; and dependency management.

## Decisions and deviations to review

These go beyond, or differ slightly from, `Web App API.txt`. Each is easy to change.

The items that would need a spec change are collected under **Proposed additions to the specs** below.

1. **Extra endpoints not in the spec yet** (marked as extensions, outside contract checks):
   - `GET /webapp/v1/session`: current user, their teams and whether they may record decisions (the UI needs this).
   - `GET /webapp/v1/dev/users`: user list for the development sign-in picker; only when `auth_mode` is `dev`.
   - `GET /webapp/v1/health`: liveness and Core API reachability (deployment and smoke tests).
   - `GET /webapp/v1/dependencies`: list all dependencies (the spec marks this PROPOSED in G-5).

   Consider adding these to section 5 of the spec.
2. **Development sign-in.** Users are picked from `config/settings.json` and sent as an `X-User` header or `secheck_session` cookie, with no password. This stands in until auth is decided (gap G-6), so keep the server bound to localhost.
3. **Extra error codes.** `NOT_FOUND` (404), `METHOD_NOT_ALLOWED` (405), `NOT_IMPLEMENTED` (501) and `INTERNAL_ERROR` (500) are used for routing and server faults. They aren't in `WebApp_error_type`; consider adding them to section 3.3.
4. **Completed_Steps on DP_DNE.** The spec example shows `[]`, but the implementation reports `["/dependencies MATCH"]` because that Core call did succeed before the Web App stopped. I think that's more accurate; adjust the spec example or the code.
5. **Ticket timestamps.** The 8-K view orders events and finds the determination time using a ticket `Timestamp` field. The Core spec doesn't return one; the mock does. Against the real Core API these show as empty until it's added. This is worth folding into gap G-12.
6. **Core requests carry G-gap workarounds**, all inside `core_client.py`: `Dependency` (not `Dependency_Name`) on `/incidents`, `Description: ""` on incident GET (G-10), `Ticket_number` on ticket EDIT (G-4), `UUID` returned as a string (G-9).

## Mock Core API behaviour

The mock follows `API Spec.txt` and `Data Schema & Examples.txt`, plus:

- `Method: "LIST"` on `/incidents`, `/tickets` (filter by `Team`, `Ticket_Claim`) and `/dependencies` (gap G-5)
- `Ticket_number` required on ticket EDIT, which returns status `"Edited"` (G-4)
- responses include `Timestamp` (incidents and tickets), `Ticket_Claim` and `Claimed_By` (G-3, G-12)
- accepts both `/dependencies` and `/dependancies` (G-2)
- a second CLAIM on a ticket is rejected with `INVALID_DATA` ("already claimed")
- `/reset` wipes all data

**About the Core contract file:** the OpenAPI block in `API Spec.txt` isn't valid YAML as written. It has tab-indented `Dependency` lines, and `/notifier` sits at the wrong indentation level. `tools/sync_contracts.py` fixes those two known problems in its extracted copy and adds `Dependency_Name` and `Ticket_Claim` from the Data Schema. `API Spec.txt` itself is untouched. If the Core team fixes the spec, the repairs simply stop applying.

## Verification

- **58 automated tests pass** (`python -m unittest`). They cover every endpoint, the spec's valid and invalid examples, auth, permissions, partial-failure reporting, Core-down handling (502), static file safety and contract drift. Every Web App response was checked against the Web App contract, and every Core request against the Core contract.
- **Smoke test** (`tools/smoke_test.py`) passes end to end against the running app and mock, including direct Core API checks.
- **Spec-change check:** on a scratch copy of the contract, adding a new severity value and a new operation was picked up with no code changes. The new value was accepted, and the new operation answered 501 with a startup warning.
- **UI** reviewed in a headless browser at desktop and phone widths (incident list, incident page, 8-K view, team queue).
- Developed on Python 3.13 and written for 3.9+.

## Known limitations and next steps

- **Auth** is a placeholder (G-6). Replace `WebApp._authenticate` in `secheck_web/app.py` once the team decides on a method.
- **Filing deadline** shows as "not provided" until the Core API exposes the deadline scheduler's output (G-8).
- **List and queue screens** depend on proposed Core list operations (G-5). Against a Core API without them, those screens show an explanatory message and the rest of the app still works.
- The standard-library HTTP server is fine for local and class use. For a production deployment, put it behind a reverse proxy or move it to a WSGI/ASGI server; only `secheck_web/web.py` would change.
- `Data Schema & Examples.txt` isn't used by the sync tool. Its examples are covered by hand in the tests.

## Proposed additions to the specs

Everything the implementation uses or needs beyond the two spec documents, in one place, ready to take to the spec owners. **Status** says what already works here. Gap numbers (G-*) refer to section 7 of `spec_docs/Web App API.txt`.

### To the Web App API spec (`spec_docs/Web App API.txt`)

| # | Proposed addition | Why | Status |
|---|---|---|---|
| W-1 | `GET /session` → `{User, Teams, Can_Decide}` | The UI needs the signed-in user's teams to offer claims and decisions | Implemented as an extension (`handlers/teams.py`) |
| W-2 | `GET /dev/users` → `{Users: [{User, Teams}]}`, no sign-in, only when `auth_mode` is `dev` | Development sign-in picker; remove once real auth exists (G-6) | Implemented as an extension |
| W-3 | `GET /health` → `{Status, Core_API_URL, Core_API_Reachable, Core_API_Detail}`, no sign-in | Deployment checks, the smoke test and the footer status | Implemented as an extension |
| W-4 | `GET /dependencies` → `{Dependencies: [...]}` | Dependency page and intake dropdown; already marked PROPOSED in G-5 | Implemented as an extension; needs C-1 |
| W-5 | `GET /incidents/{id}/log/entries` → `{Incident_ID, Entries: [{Ticket_ID, Ticket_number, Version, Details_Available, Entry_Type, Timestamp, Ticket_Description, ticket_severity, ticket_urgency, Team_List}], Status: "Log Entries Retrieved"}` | Full log with each entry's details | Implemented as an extension; uses C-2, with a fallback without it |
| W-6 | Add `NOT_FOUND` (404), `METHOD_NOT_ALLOWED` (405), `NOT_IMPLEMENTED` (501) and `INTERNAL_ERROR` (500) to `WebApp_error_type` (section 3.3) | Routing and server faults already return them | Implemented |
| W-7 | Section 6.1 example: `Completed_Steps` for `DP_DNE` should read `["/dependencies MATCH"]`, or define `Completed_Steps` as data-changing steps only | The example disagrees with the implementation | Spec text only |

### To the Core API spec (`spec_docs/API Spec.txt`, Core team)

| # | Proposed addition | Why | Status |
|---|---|---|---|
| C-1 | `Method: "LIST"` on `/incidents`, `/tickets` (filters `Team`, `Ticket_Claim`) and `/dependencies` | Incident list, team queue and dependency list (G-5) | Mock Core API supports it; the Web App uses it |
| C-2 | `/tickets GET` accepts a `Ticket_type_strong` (version ID) in `Ticket_number` and returns that exact version | Full log details (G-7) | Mock supports it; the Web App uses it, with a fallback |
| C-3 | `Ticket_number` required on `/tickets EDIT`, which returns status `"Edited"` | Otherwise EDIT can't say which ticket (G-4) | The Web App sends it; the mock requires it |
| C-4 | `Timestamp` in `/incidents` and `/tickets` responses | Log times, 8-K timing and event order (G-12) | Mock returns it; the Web App uses it when present |
| C-5 | `Ticket_Claim` and `Claimed_By` in `/tickets` responses; `Ticket_Claim` in the OpenAPI request schema (it's already in the Data Schema) | Show who claimed a ticket (G-3) | Mock returns them |
| C-6 | `Timestamp` in `/notifier` responses | When a team was notified or claimed, for AC-04 audit ordering (G-12) | Not implemented |
| C-7 | Optional `Actor` field on all write requests | REQ-02 needs who did each action (G-6); today the user's name is written into audit ticket text | Not implemented (text workaround) |
| C-8 | `Filing_Deadline` and `Deadline_Status` in `/incidents` and `/tickets` GET responses | Show the 4-business-day Form 8-K clock from the deadline scheduler (G-8) | Not implemented; the UI shows "not provided" |
| C-9 | `Description` required only for `/incidents` NEW and EDIT | A GET shouldn't need a description (G-10) | The Web App sends `""` on GET |
| C-10 | Optional `Rationale` on `/incidents EDIT` | The Web App requires a reason for materiality, severity and urgency decisions | The mock's gateway passes it through, or uses a default note |
| C-11 | **Gateway behaviour:** the Core API forwards test-client calls to the Web App as Web App API requests (mapping table under "Core API gateway mode" below) and returns the answer in Core format. Calls carrying the header `X-SECheck-Origin: webapp` come from the Web App and are handled by the Core API itself | System testing through the Core API; the header prevents an endless loop | The Web App sends the header; the mock implements the forwarding |
| C-12 | Spec consistency fixes: one `Incident_ID` type (G-1); one spelling, `/dependencies` (G-2); one name, `Dependency` or `Dependency_Name` (G-3); `_` as the separator in `Ticket_type_weak`, `Ticket_ID_List` as a real array, and one type for `UUID` (G-9); a valid YAML OpenAPI block (tab-indented `Dependency`, mis-indented `/notifier`) | Ambiguities every client must guess around | Workarounds in `core_client.py` and `tools/sync_contracts.py` |

**Open question for both teams (G-11):** REQ-03 talks about marking *tickets* material, but the Core schema stores materiality on the *incident*. The implementation follows the schema and records each decision as an audit ticket. Confirm that's the intended model.

## Later changes

### Core API gateway mode (mock Core API forwards to the Web App)

System testing is done partly through the Core API: API test clients call the Core API, and the Core API must drive the Web App through the Web App API. The mock Core API now does this.

- **New `Web Dev/mock_core/gateway.py`.** It translates each Core API call from a test client into the matching Web App API request(s), and converts the Web App's answer back into the Core response format (for example `Dependency_Name` becomes `Dependency`, and Web-App-only fields like `Intake_Ticket_ID` and `Notified_Teams` are dropped). Errors keep the Core `{Error, Message}` envelope.

  | Core API call | Web App request(s) generated |
  |---|---|
  | `/incidents NEW` | `POST /incidents` |
  | `/incidents GET` | `GET /incidents/{id}` |
  | `/incidents EDIT` | `GET /incidents/{id}`, then `PATCH /incidents/{id}` for Description/Dependency changes and/or `PUT /incidents/{id}/decision` for Materiality/Severity/Urgency changes, then `GET` again |
  | `/incidents LIST` | `GET /incidents` (all pages) |
  | `/tickets NEW` | `POST /incidents/{id}/tickets` with `Notify: false` (notifying is `/notifier`'s job in the Core API) |
  | `/tickets GET` / `EDIT` | `GET` / `PATCH /incidents/{id}/tickets/{n}` |
  | `/tickets LIST` | `GET /queue?team=&claim=` |
  | `/notifier CLAIM` / `NOTIFY` | `POST /tickets/{n}/claim` / `POST /tickets/{n}/notify` |
  | `/logs` | `GET /incidents/{id}/log` |
  | `/dependencies NEW` / `MATCH` / `REMOVE` / `LIST` | `POST /dependencies` / `GET /dependencies/{name}` / `DELETE /dependencies/{name}` / `GET /dependencies` |
  | `/reset` | not forwarded; handled by the mock |

- **Loop prevention.** The Web App's Core client now sends `X-SECheck-Origin: webapp` on every Core API call (`secheck_web/core_client.py`). The mock stores those locally and only forwards calls without the header. A real Core API that forwards to the Web App will need the same rule; consider adding the header to the Core API spec.
- **Service user.** The mock signs in to the Web App as `core-gateway` (all teams), added to `config/settings.json` and hidden from the sign-in picker. Audit tickets created this way say "... by core-gateway".
- **Rationale on decisions.** The Web App requires a reason for decisions, but Core `/incidents EDIT` has no such field. The gateway passes an optional `Rationale` field through if present, and otherwise uses "Recorded through the Core API (no rationale supplied)."
- **Settings and flags.** `mock_core_forwarding` (default `true`), `mock_core_gateway_user`, `run.py --mock-local` to turn forwarding off, and `python -m mock_core --webapp-url ...`.
- **Tests.** New `tests/test_core_gateway.py` (20 tests) sends Core API calls directly, as a test client would. It checks which Web App requests were generated, that the Web App's callbacks were stored and not forwarded again, the Core-format response (validated against the Core contract), and the result as seen through the Web App. The test helpers gained `core()`, `core_ok()`, `core_err()` and `forwarded()`.
- **Bug fixed along the way.** The 8-K view returned `"Dependency_Name": null` (and could return null timestamps) for incidents without a dependency, which the Web App spec doesn't allow. Unknown values are now left out. "Copy as text" in the 8-K view no longer prints "undefined" for missing times.
- **Known wording quirk.** Incidents created through the Core API get an intake audit ticket reading "incident created via manual intake by core-gateway", because they go through the Web App's intake endpoint.
- `tests/current_tests.md` now covers 78 tests and marks Core API requests and the Web App requests they generate.

### Full log shows every entry's details

The full log on an incident page used to list only version IDs (`<incident>_<ticket>_<version>`). Opening it now shows what each entry recorded: its time, description, severity, urgency and teams, oldest first, with each entry labelled ("Incident created", "New ticket", "Ticket update, version 2", "Decision recorded"). The panel now spans the full page width and stays open after other actions on the page.

- **New Web App endpoint `GET /webapp/v1/incidents/{id}/log/entries`** (an extension, not yet in `spec_docs/Web App API.txt`). It reads the log from the Core API (`/logs`), then requests **each log entry from the Core API by its version ID** (`/tickets GET` with `Ticket_number` set to e.g. `123_2_1`), as the real system will. Response: `{Incident_ID, Entries: [{Ticket_ID, Ticket_number, Version, Details_Available, Entry_Type, Timestamp, Ticket_Description, ticket_severity, ticket_urgency, Team_List}], Status: "Log Entries Retrieved"}`. Suggest adding it to the Web App spec.
- **Depends on gap G-7.** The Core spec only defines `/tickets GET` by plain ticket number, which returns the latest version. Looking up a specific version is the fix G-7 proposes. The mock Core API now supports it (`version_lookup`, on by default). If a Core API doesn't, the endpoint still works: entries that are the latest version show in full, and older ones come back with `Details_Available: false` and a note in the UI.
- **Gateway mode:** a Core `/tickets GET` with a version ID from a test client is forwarded to the new endpoint and answered with that version.
- **Tests:** 6 new (84 total). They cover every version shown with its own details; one Core API request per entry by version ID; the fallback when the Core API can't look up versions; version lookup through the Core API, both locally and in gateway mode; and unknown or invalid incident IDs.

### Fix: long text ran off the page

An incident description (or ticket text) containing a long unbroken string, such as a URL, hash or pasted log line, ran off the right edge of "What happened", ticket entries, the 8-K view and the full log. On phones it widened the whole page to about 3,200px. Fixed in `secheck_web/static/styles.css`: text in the page body may break inside long strings, but in tables only the description columns do, so IDs, severity and teams keep whole words. The phone layout's columns can no longer be stretched by their content. Checked in a headless browser at desktop and phone widths on the incident list, the incident page, the 8-K view and the full log, with no horizontal overflow.

