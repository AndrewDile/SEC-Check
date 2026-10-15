# SEC-Check Web App

The Web App component of SEC-Check: a browser front end plus a small backend that implements the Web App API (`../spec_docs/Web App API.txt`) and talks to the Core API. It needs **Python 3.9 or newer and nothing else**: no `pip install`, no Node, no database.

## Run it

```
run.bat                 (Windows)
./run.sh                (macOS / Linux)
python run.py           (any platform)
```

Then open **http://localhost:8000/app/** and choose a user in the top bar.

By default this also starts a **mock Core API** on port 8001, an in-memory stand-in for the real Core API that is wiped when you stop the server. To use a real Core API instead:

```
python run.py --core-url http://<core-host>:<port>
```

| Flag | Meaning |
|---|---|
| `--port 9000` | Web App port (default 8000) |
| `--mock-port 9001` | Mock Core API port (default 8001) |
| `--core-url URL` | Use this Core API; the mock is not started |
| `--no-mock` | Don't start the mock (use `core_api_url` from settings) |
| `--mock-local` | Mock handles test-client calls itself instead of forwarding them to the Web App (see below) |
| `--host 0.0.0.0` | Accept connections from other machines (default: this computer only) |
| `--open` | Open the app in your browser |
| `--quiet` | Don't log every request |

Other useful URLs:

| URL | What |
|---|---|
| `/app/` | The web app |
| `/docs` | Interactive API docs (Swagger UI; needs internet to load) |
| `/openapi.json` | The Web App contract the server is running |
| `/webapp/v1/health` | Is the server up, and can it reach the Core API? |
| `http://localhost:8001/openapi.json` | The Core contract the mock enforces |

The mock Core API can also run alone: `python -m mock_core --port 8001` (add `--webapp-url http://127.0.0.1:8000` for gateway mode).

## System testing through the Core API (gateway mode)

In system testing, API test clients call the **Core API**, and the Core API drives the Web App through the Web App API ("external API is proxied through the internal API" in the system overview). The mock Core API does this by default under `run.py`:

```
test client --Core API call--> mock Core API --Web App API request--> Web App
                                                                      |  stores data by calling the Core API back,
                                                                      |  marked X-SECheck-Origin: webapp (handled locally)
test client <--Core API response (Core format)-- mock Core API <------+
```

- Calls **without** the `X-SECheck-Origin: webapp` header (test clients) are validated against the Core contract, translated to the matching Web App endpoint(s) (the section 2 mapping in the Web App spec, reversed), and the answer is converted back to the Core format. For example `/tickets NEW` becomes `POST /webapp/v1/incidents/{id}/tickets`, and `/incidents EDIT` with a new `Materiality` becomes `PUT /webapp/v1/incidents/{id}/decision` (optional `Rationale` field; a default note is used otherwise).
- Calls **with** the header come from the Web App and are stored by the mock. The Web App's Core client always sends it, which prevents an endless loop.
- `/reset` is always handled by the mock.
- The mock signs in to the Web App as the service user `core-gateway` (settings: `mock_core_gateway_user`), so audit tickets read "... by core-gateway". It is hidden from the sign-in picker.
- `--mock-local` (or `"mock_core_forwarding": false`) turns this off: the mock then answers test-client calls itself, as before.

Translation code: `mock_core/gateway.py`. Tests: `tests/test_core_gateway.py`.

The mock Core API's `/tickets GET` also accepts a version ID (`Ticket_type_strong`, e.g. `123_2_1`) and returns that exact version, the fix proposed for gap G-7. The Web App's full log (`GET /webapp/v1/incidents/{id}/log/entries`) uses it to show every entry's details, and falls back gracefully on a Core API without it (`MockCore(version_lookup=False)` simulates that).

## Test it

```
test.bat   /   ./test.sh   /   python -m unittest
```

The tests start their own servers on free ports; nothing needs to be running. Each test goes through real HTTP and checks **both directions of the contract**:

- every Web App response must match `contracts/webapp_api.json`
- every request the Web App sends to the Core API must match `contracts/core_api.json` (the mock also rejects anything that doesn't)

Against running servers (the mock or a real Core API):

```
python tools/smoke_test.py --webapp http://localhost:8000
```

This runs a full workflow through the Web App (dependency, intake, ticket, notify, claim, decision, 8-K view), then queries the **Core API directly** to confirm the data landed there.

`tests/current_tests.md` lists every test as the HTTP requests it sends and the responses it expects. It is generated from a passing run, so regenerate it after changing tests:

```
python tools/document_tests.py
```

## When a spec changes

The OpenAPI specs are expected to change. The app is built so most changes need no code edits:

1. Edit the spec document in the project's `spec_docs/` folder (`Web App API.txt` or `API Spec.txt`).
2. Run `python tools/sync_contracts.py` (needs `pip install pyyaml`, used only by this tool). It regenerates `contracts/*.json` from the spec documents without modifying them.
3. Run the tests. They tell you what, if anything, needs code.

| Change in the spec | What happens |
|---|---|
| New/changed enum value, max length, pattern, required field | Validation follows automatically; front-end dropdowns read enums from `/openapi.json` |
| New Web App operation | Server prints a warning and answers `501 NOT_IMPLEMENTED`; `test_every_spec_operation_has_a_handler` fails. Add a function with `@operation("<operationId>")` in `secheck_web/handlers/` |
| Removed or renamed operationId | Startup warning plus test failure listing the orphaned handler |
| Core API field or path renamed | Edit `secheck_web/core_client.py`, **the only file that knows Core field names and paths** |
| Core request rules tightened | The mock rejects non-conforming requests, so tests fail where the Web App needs updating |

## Layout

```
Web Dev/
  run.py, run.bat, run.sh      start the app (+ mock Core API)
  test.bat, test.sh            run the tests
  config/settings.json         ports, Core URL, teams, dev users, who may record decisions
  contracts/                   OpenAPI contracts the app runs on (generated, don't hand-edit)
  secheck_web/
    app.py                     spec-driven routing, auth, validation, errors
    core_client.py             Core API adapter (all Core paths and field names)
    handlers/                  one function per operationId
    audit.py                   wording of audit tickets (intake, edit, decision)
    validation.py              JSON-schema subset validator used for both contracts
    web.py                     tiny HTTP server on the standard library
    static/                    the browser app (HTML, CSS, JS; no build step)
      logo.png                 logo in the page footer + browser-tab icon (replace this file to update it)
  mock_core/                   in-memory Core API that enforces the Core contract
    gateway.py                 forwards test-client Core API calls to the Web App (gateway mode)
  tests/                       unittest suite
  tools/sync_contracts.py      regenerate contracts from the spec documents
  tools/smoke_test.py          end-to-end check against running servers
  Dockerfile                   optional container
```

## Settings

`config/settings.json`, overridable with environment variables:

| Setting | Env var | Default |
|---|---|---|
| `host` / `port` | `SECHECK_HOST` / `SECHECK_PORT` | `127.0.0.1` / `8000` |
| `core_api_url` | `CORE_API_URL` | `http://127.0.0.1:8001` |
| `core_timeout_seconds` | `CORE_TIMEOUT_SECONDS` | `10` |
| `start_mock_core` / `mock_core_port` | `SECHECK_START_MOCK_CORE` / `SECHECK_MOCK_CORE_PORT` | `true` / `8001` |
| `mock_core_forwarding` | `SECHECK_MOCK_CORE_FORWARDING` | `true` (gateway mode) |
| `mock_core_gateway_user` | n/a | `core-gateway` |
| `teams` | `SECHECK_TEAMS` (JSON list) | `["LEGAL","CYBER1","CYBER2"]` |
| `users` | n/a | 4 sample users and their teams |
| `decision_teams` | n/a | `[]` = any signed-in user may record decisions |
| `auth_mode` | `SECHECK_AUTH_MODE` | `dev` |

**Sign-in is a development placeholder.** Users pick a name; the browser sends it as an `X-User` header (and a `secheck_session` cookie). There is no password. Keep `host` at `127.0.0.1` until real authentication is chosen.
