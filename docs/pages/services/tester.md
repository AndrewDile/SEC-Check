# Tester

**Folder:** `tester/`. **Stack:** Python 3.9+, standard library only. **Port:** 8100 inside the
stack, `/tester/` through Caddy.

The tester implements the course's cross-team **tester interface**. It drives a target system
(ours or another team's) through that system's `/test/setup`, the Core API project endpoints,
and `/test/report`, and grades 54 ordered tests. It imports nothing from our system, so it can
point at any team's base URL. `tester/README.md` has the full detail; this page summarizes it.

| File | What's in it |
|---|---|
| `secheck_tester/server.py` | `POST /test/setup`, `POST /test/run`, `GET /test/report` |
| `secheck_tester/target.py` | The **only** place that knows the target's paths |
| `secheck_tester/suite.py` | The tests, T-01 … T-54 |
| `secheck_tester/judge.py` | Turns each response into pass, fail, error (with its source) or skip |
| `secheck_tester/runner.py` | Runs the suite: time budget, aborting after repeated communication errors, fetching coverage |
| `secheck_tester/coverage.py` | Acceptance-criteria (system) coverage, AC-01 … AC-06 |
| `secheck_tester/sessions.py` | Reports, kept in memory until the process stops |
| `dev/mock_system.py` | An in-memory reference system for local runs, with `--bug ...` fault modes |
| `run_tests.py` | A command-line client: setup, run and report, then a readable summary |

## A session

1. **`POST /test/setup`** with `{"target_url": "<system base URL>"}`.
    - The tester calls the target's `/test/setup` with a new `session_id`, and returns 201
      `{"session_id"}`.
    - **Failures:** a failure at the target is passed back with its status.
    - **Unreachable target:** 500, with source `communication`.
2. **`POST /test/run`** with `{"session_id"}`. It runs the suite and returns the full report.
3. **`GET /test/report?session_id=...`** returns the same stored report.

The tester never calls `/reset`. Every session makes fresh Incident_IDs and dependency names
instead. It assumes the target already has the teams `LEGAL`, `CYBER1` and `CYBER2`.

**Outcomes:**

| Outcome | When |
|---|---|
| `pass` | The response matches the spec, including expected 400s |
| `fail` | The response arrived but something in it is wrong |
| `error`, source `system` | The target returned 5xx |
| `error`, source `communication` | No response |
| `error`, source `tester` | A bug in the test |
| `skip` | A prerequisite didn't pass, or the run was cut short |

**Coverage:**

- **System:** AC-01 … AC-06, counting which criteria got an answered test. A full run is 6/6.
- **Code:** copied from the target's report. Our Core API reports `null`.
- **Component:** not measured.

## Interface

The `servers` URL in this spec is a placeholder. On our deployment, the tester is at
`http://<host>/tester`.

<swagger-ui src="../openapi/tester/tester.yaml"/>

## Running it against our stack

The tester runs inside Docker, so it has to reach our system by its Compose name, not
`localhost`:

```bash
python3 tester/run_tests.py http://caddy/system --tester http://localhost/tester
```

It **wipes the target's database**, because `/test/setup` does.

## Where the spec is ambiguous

When the spec allows more than one reading, the tester accepts each one, or has a setting for
it. For example:

- **Sessions:** it sends `X-Session-ID` (`TESTER_SESSION_HEADER`).
- **Incident IDs:** it uses 12-digit IDs (`TESTER_ID_STYLE`).
- **`Ticket_ID`:** it accepts weak or strong IDs.
- **`Ticket_ID_List`:** it accepts a comma-joined string or a list.

The full table and every setting (timeouts, run budget, base path) are in `tester/README.md`.

| Setting | Default | Meaning |
|---|---|---|
| `TESTER_PORT` / `TESTER_HOST` | `8100` / `0.0.0.0` | Listen address |
| `TESTER_BASE_PATH` | empty | Route prefix. Unset here, because Caddy strips `/tester` |
| `TESTER_REQUEST_TIMEOUT_S` | `10` | One call to the target |
| `TESTER_SETUP_TIMEOUT_S` | `60` | The target's `/test/setup` |
| `TESTER_RUN_BUDGET_S` | `240` | The whole suite |

## Its own tests

`tester/tests/` has 30 unittest checks of the tester against the mock system: the interface,
the fault modes, and T-41 … T-54. Run them with
`cd tester && python3 -m unittest discover -s tests`.
