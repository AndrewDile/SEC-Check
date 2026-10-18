# SEC-Check Tester (Core API)

An example tester service for the SEC-Check pod. It implements the course's
cross-team tester interface and tests a target system **only through the
Core API** described in `spec_docs/API Spec.txt` and
`spec_docs/Data Schema & Examples.txt`. The Web App API is not used.

Python 3.9+, standard library only. Nothing here imports or depends on any
team's system code, so the same tester can be pointed at any team's system
by changing `target_url`.

```
secheck_tester/   the tester service
  server.py       POST /test/setup, POST /test/run, GET /test/report
  target.py       the ONLY place that knows the target's URLs and paths
  suite.py        the 54 ordered tests (T-01..T-54)
  judge.py        response -> pass / fail / error(source) / skip
  runner.py       runs the suite, abort handling, reads code coverage
  coverage.py     acceptance-criteria coverage (component: not yet measured)
  sessions.py     session store (reports kept until the process stops)
  config.py       environment settings for unsettled pod decisions
dev/mock_system.py  in-memory reference system for local runs (not deployed)
tests/              unittest checks of the tester against the mock system
                      (test_tester.py: interface and fault modes; test_ported.py: T-41..T-54 and edge cases)
openapi/tester.yaml OpenAPI 3.1.1 for the tester's three endpoints
```

## Run it

```bash
# Terminal 1: a reference system to test against
python dev/mock_system.py --port 8200

# Terminal 2: the tester
python -m secheck_tester --port 8100

# Terminal 3: one suite
curl -s -X POST localhost:8100/test/setup -H 'Content-Type: application/json' \
     -d '{"target_url":"http://127.0.0.1:8200"}'
# -> 201 {"session_id":"run-…"}
curl -s -X POST localhost:8100/test/run -H 'Content-Type: application/json' \
     -d '{"session_id":"run-…"}'
# -> 200 full report
curl -s 'localhost:8100/test/report?session_id=run-…'
# -> 200 the same stored report
```

Or let a script make those three calls and print a readable summary (exit
code 0 only if everything passed). It talks to a deployed tester: `--tester`,
else `TESTER_URL`, else `http://localhost:8100`. Only Python is needed.

```bash
python run_tests.py http://localhost:3001                      # e.g. the docker compose Core API
python run_tests.py http://localhost:3001 --failures-only --json report.json
python run_tests.py https://our-system.example.edu --tester https://our-tester.example.edu
```

`python -m secheck_tester --list` prints the planned tests.
`python -m unittest discover -s tests -v` checks the tester itself.

To see failures being reported, start the mock with a fault:
`--bug wrong-status | no-validation | crash-logs | unordered-logs | setup-fails |
claim-steal | edit-drops-fields | log-latest-only`. `--bug ignore-session` makes
the mock share one state across sessions, like a system that ignores
`X-Session-ID` (the suite should still pass).

Where the spec leaves a choice, the mock behaves like the pod's Core API in
`api/` (for example, a second team can't claim a ticket another team holds,
and a ticket EDIT keeps the severity, urgency and teams it doesn't send).

Docker: `docker build -t secheck-tester . && docker run -p 8100:8100 secheck-tester`.

With the whole stack (`docker compose up --build` from the repo root) the
tester runs as the `tester` service on http://localhost:8100. Inside the stack
the Core API is `http://api:3001`, so that's the target URL to give it:

```bash
python run_tests.py http://api:3001
```

(`localhost` inside the tester container is the tester itself.) Running the
suite wipes the stack's database, because `/test/setup` does.

## How the tester talks to a system

The tester touches the target in exactly three ways:

1. **`POST {target}/test/setup`** with
   `{"session_id": "run-<uuid>", "setup": {}}`. `setup` is always empty: the
   tests create all their data through the Core API calls.
   It waits for `201` with the same ID. Any failure is passed back to the
   caller with the same status, message and source. Unreachable gives 500 /
   `communication`.
2. **Core API project calls**: `POST /incidents`, `/tickets`, `/notifier`,
   `/logs`, `/dependencies`, with the exact field names from the spec. Each
   request carries the session ID in the `X-Session-ID` header.
3. **`GET {target}/test/report?session_id=…`** after the last project call.
   This reads `coverage.code`. If it's missing or malformed, the tester
   reports `null`/`null` with the reason in `basis`.

The tester **never calls `/reset`**. It wipes the whole database, which
would destroy other sessions' data on a shared system. Instead, every
session uses freshly generated Incident_IDs and dependency names, so suites
don't depend on or interfere with each other.

## Outcomes

| Situation | Outcome |
|---|---|
| Response matches the spec, including an **expected** 400 error | `pass` |
| A response was received but status, `Error`, `Status` or a field is wrong | `fail` |
| Target returned 5xx | `error`, source `system` |
| No response (timeout, refused) | `error`, source `communication` |
| Bug in a test function | `error`, source `tester` |
| A prerequisite test did not pass | `skip` |
| Target unreachable 3 times in a row: remaining tests aren't sent | `skip` |
| Run time limit reached: test in progress / the rest | `error` `tester` / `skip`; run returns 500 and the partial report is stored |

## Coverage

* **code**: copied from the target's `/test/report`.
* **component**: not measured yet; reported as `null`/`null` with basis
  "not yet measured" (the spec allows null when a measure isn't available).
* **system**: AC-01..AC-06. A criterion counts when a test mapped to it got
  a response. A full run reports **6/6**. AC-06 is covered only as far as
  the Core `/logs` path goes; the 8-K view itself belongs to the Web App.

Coverage counts what was exercised, not what passed.

## The suite

| ID | Test | Criteria | Runs after |
|---|---|---|---|
| T-01 | Create a material incident (NEW) | AC-01 | - |
| T-02 | Fetch the stored incident (GET) | AC-01 | T-01 |
| T-03 | Reject a duplicate Incident_ID (NEW twice) | AC-01 | T-01 |
| T-04 | Reject GET of an unknown incident | AC-01 | - |
| T-05 | Reject an incident timestamp in the future | AC-01 | - |
| T-06 | Reject a Description over 5000 characters | AC-01 | - |
| T-07 | Reject an invalid Severity value | AC-01 | - |
| T-08 | Reject an incident without Description | AC-01 | - |
| T-09 | Reject an invalid Method | AC-01 | - |
| T-10 | Create an incident with optional fields omitted | AC-01 | - |
| T-11 | Omitted fields default to UNDECIDED | AC-01 | T-10 |
| T-12 | Mark an incident immaterial with low severity (EDIT) | AC-03 | T-10 |
| T-13 | The edited marking is stored | AC-03 | T-12 |
| T-14 | Reject EDIT of an unknown incident | AC-03 | - |
| T-15 | Log a ticket on the material incident (NEW) | AC-02, AC-03 | T-01 |
| T-16 | Display the logged ticket (GET by weak ticket number) | AC-02 | T-15 |
| T-17 | A second ticket gets the next ticket number | AC-02 | T-15 |
| T-18 | Editing a ticket creates a new version (EDIT) | AC-02 | T-15 |
| T-19 | Reject a ticket for an unknown incident | AC-02 | - |
| T-20 | Reject a NEW ticket without Description | AC-02 | T-01 |
| T-21 | Reject a ticket timestamp in the future | AC-02 | T-01 |
| T-22 | Reject an invalid Ticket_urgency value | AC-02 | T-01 |
| T-23 | Retrieve the incident log with all its tickets | AC-02, AC-06 | T-15, T-17 |
| T-24 | Log entries are in the order the actions happened | AC-02 | T-23 |
| T-25 | Reject a log request for an unknown incident | AC-06 | - |
| T-26 | Reject a log request with a future timestamp | AC-02 | T-01 |
| T-27 | Notify all teams about a ticket (NOTIFY) | AC-04 | T-15 |
| T-28 | One team claims the ticket (CLAIM) | AC-04 | T-15 |
| T-29 | The claim is visible on the ticket | AC-04 | T-28 |
| T-30 | Reject a claim with no team | AC-04 | T-15 |
| T-31 | Reject an invalid notifier Method | AC-04 | T-15 |
| T-32 | Reject a claim on an unknown ticket | AC-04 | - |
| T-33 | Add a third-party dependency (NEW) | AC-05 | - |
| T-34 | Reject a duplicate dependency | AC-05 | T-33 |
| T-35 | Match a stored dependency (MATCH) | AC-05 | T-33 |
| T-36 | Record an incident against a dependency | AC-05, AC-01 | T-33 |
| T-37 | Remove the dependency (REMOVE) | AC-05 | T-33 |
| T-38 | A removed dependency no longer matches | AC-05 | T-37 |
| T-39 | Reject removal of an unknown dependency | AC-05 | - |
| T-40 | Reject an invalid dependency method | AC-05 | - |
| T-41 | A second team cannot claim an already claimed ticket | AC-04 | T-28 |
| T-42 | Reject a CLAIM naming more than one team | AC-04 | T-17 |
| T-43 | Reject a ticket assigned to an unknown team | AC-02, AC-04 | T-01 |
| T-44 | Reject NOTIFY with no teams | AC-04 | T-15 |
| T-45 | Reject a ticket number that belongs to another incident | AC-02 | T-15, T-10 |
| T-46 | Reject an unknown ticket number on a known incident | AC-02 | T-01 |
| T-47 | Reject a ticket EDIT without Description | AC-02 | T-15 |
| T-48 | An edited ticket shows the new text and keeps unchanged fields | AC-02 | T-18 |
| T-49 | The log keeps every version of an edited ticket, in order | AC-02, AC-06 | T-18, T-23 |
| T-50 | Ticket responses carry the incident's details | AC-02 | T-17 |
| T-51 | The log response carries the incident's details | AC-06 | T-23 |
| T-52 | An incident's description and urgency can be edited | AC-01 | T-13 |
| T-53 | Dependency names with spaces work end to end | AC-05 | - |
| T-54 | Error responses use the `{Error, Message}` format | AC-01, AC-02, AC-05 | - |

T-41..T-54 are ported from the Web App team's mock-Core test suite
(`Web Dev/tests`). Only checks a client can observe through the Core API were
ported. Web App behaviour (sign-in, decision rationale, the 8-K view, the
team queue, the gateway translation) stays in the Web App's own tests, and
`/tickets GET` by version ID (a proposed fix for gap G-7, not in the spec)
and the `LIST` methods (gap G-5) were left out.

Expected values come from the spec examples: Status strings `Created` /
`Edited` / `Data Fetched` / `Logged` / `Displayed` / `Log Retrieved` /
`Notified team` / `Claimed ticket` / `Added` / `Exists` / `Removed`, and
errors `UUID_EXISTS`, `UUID_DNE`, `INVALID_DATA`, `DP_EXISTS`, `DP_DNE`.

## Where the spec is ambiguous, and what the tester does

These are pod decisions. Each one is either a setting or handled leniently
in the test, so the suite doesn't fail a system for picking a reading the
spec allows.

| Issue | Tester behavior | Setting |
|---|---|---|
| Core requests have no session field | Sends `X-Session-ID` header; can also add `session_id` to bodies | `TESTER_SESSION_HEADER`, `TESTER_SESSION_IN_BODY` |
| Incident_ID: uuid vs integer vs digit string (G-1) | 12-digit strings; accepts the ID back as string or number | `TESTER_ID_STYLE=digits\|uuid` |
| `/dependencies` vs `/dependancies` (G-2) | `/dependencies` | `TESTER_DEPENDENCIES_PATH` |
| `Dependency` vs `Dependency_Name`; `Ticket_Claim` not in OpenAPI (G-3) | Sends `Dependency`; checks either name and `Ticket_Claim` only if returned | - |
| Ticket EDIT can't name a ticket; no EDIT Status (G-4) | Sends `Ticket_number`; checks only same ticket number and newer version | - |
| Description required on GET (G-10) | Sends `""` on GET | - |
| Ticket_ID example is weak (`id_1`), spec says strong (`id_1_1`) | Accepts both | - |
| `Ticket_ID_List` example is one comma-joined string (G-9) | Accepts both forms | - |
| MATCH on a missing dependency: `DP_DNE` or `"Does not Exist"` | Accepts both | - |
| Error type for an unknown ticket in `/notifier` | `UUID_DNE` or `INVALID_DATA` | - |
| Ticket number from another incident, or one that doesn't exist (T-45, T-46) | `UUID_DNE` or `INVALID_DATA` | - |
| Re-claim by the team that already holds the ticket | Not tested; only a claim by a *different* team must be rejected (T-41) | - |
| Team names (the Core API has no path to create teams) | Uses `LEGAL, CYBER1, CYBER2` in ticket and notifier calls; the target must already have teams with these names | `TESTER_TEAMS` |
| Target clock skew | Timestamps are 60 s behind the tester's clock and strictly increasing | - |

## Settings and time limits

| Variable | Default | Meaning |
|---|---|---|
| `TESTER_PORT` / `TESTER_HOST` | 8100 / 0.0.0.0 | Listen address |
| `TESTER_BASE_PATH` | (empty) | Route prefix, e.g. `/tester` |
| `TESTER_REQUEST_TIMEOUT_S` | 10 | One Core API call |
| `TESTER_SETUP_TIMEOUT_S` | 60 | Target `/test/setup` |
| `TESTER_RUN_BUDGET_S` | 240 | Whole suite; after this the run aborts |
| `TESTER_REPORT_RETRIES` | 3 | Retries when target `/test/report` returns 409 |
| `TESTER_MAX_COMM_ERRORS` | 3 | Consecutive no-response tests before skipping the rest |

For the spreadsheet, register a tester setup limit of about 60 s and a
tester run limit of about 270 s (the run budget plus the coverage fetch).

## What the system needs for this tester

The tester relies on the target system providing:

* `POST /test/setup` that accepts `{"session_id", "setup"}` and returns
  `201 {"session_id"}`. It should return `409` for a reused ID.
* `GET /test/report?session_id=` returning `{"session_id", "coverage": {"code": {...}}}`.
* The Core API paths at the system base URL. Reading `X-Session-ID` is
  optional; a system that ignores it still passes, because the tester's IDs
  are unique.

The pod's Core API provides both in `api/src/testing.ts`. It keeps one session
at a time: a successful setup wipes the database (like `/reset`, restoring the
default teams), the previous session is forgotten, `X-Session-ID` is ignored,
and `coverage.code` is reported as `null`/`null` for now.
