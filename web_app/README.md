# SEC-Check Web App

The Web App component of SEC-Check: a browser front end plus a small backend that implements the Web App API (`../spec_docs/Web App API.txt`) and talks to the Core API. It runs as **its own container** and needs nothing but Python 3.9+ (standard library only: no `pip install`, no Node, no database).

The test harness (mock Core API, tests, tools) is in `../Web Dev`. It uses the code in this folder; this folder doesn't depend on it.

## Run with Docker

From the repo root, alongside the Core API (`api/`):

```
docker compose up --build
```

Open **http://localhost:8000/app/** and pick a user in the top bar. In `docker-compose.yml` the Web App is the `web` service; it reaches the Core API at `http://api:3001`.

On its own:

```
docker build -t secheck-web ./web_app
docker run -p 8000:8000 -e CORE_API_URL=http://<core-api-host>:3001 secheck-web
```

The image runs as a non-root user, listens on port 8000, and has a health check on `/webapp/v1/health`.

## Run without Docker

```
cd web_app
python -m secheck_web --core-url http://127.0.0.1:3001
```

For local development with the **mock Core API** instead of the real one, use `run.py` in `../Web Dev`.

| Flag | Meaning |
|---|---|
| `--core-url URL` | Core API base URL (default from settings / `CORE_API_URL`) |
| `--host 0.0.0.0` | Accept connections from other machines (default: this computer only; the container sets `0.0.0.0`) |
| `--port 9000` | Port (default 8000) |
| `--settings FILE` | Use another settings file |
| `--quiet` | Don't log every request |

Useful URLs:

| URL | What |
|---|---|
| `/app/` | The web app |
| `/openapi.json` | The Web App contract the server is running |
| `/webapp/v1/health` | Is the server up, and can it reach the Core API? (A Core API that answers with an error, even `NOT_IMPLEMENTED`, counts as reachable.) |

## Settings

`config/settings.json`, overridden by environment variables (the usual way to configure the container):

| Setting | Env var | Default |
|---|---|---|
| `host` / `port` | `SECHECK_HOST` / `SECHECK_PORT` | `127.0.0.1` / `8000` (container: `0.0.0.0` / `8000`) |
| `core_api_url` | `CORE_API_URL` | `http://127.0.0.1:3001` (container: `http://api:3001`) |
| `core_timeout_seconds` | `CORE_TIMEOUT_SECONDS` | `10` |
| `teams` | `SECHECK_TEAMS` (JSON list) | `["LEGAL","CYBER1","CYBER2"]` |
| `users` | `SECHECK_USERS` (JSON object) | 4 sample users + `core-gateway` |
| `hidden_users` | n/a | `["core-gateway"]`: service accounts left out of the sign-in picker |
| `decision_teams` | `SECHECK_DECISION_TEAMS` (JSON list) | `[]` = any signed-in user may record decisions |
| `auth_mode` | `SECHECK_AUTH_MODE` | `dev` |
| `log_requests` | `SECHECK_LOG_REQUESTS` | `true` |

**Sign-in is a development placeholder.** Users pick a name; the browser sends it as an `X-User` header (and a `secheck_session` cookie). There is no password, so don't expose the container publicly until real authentication is chosen (gap G-6). `core-gateway` is the service user a Core API signs in as when it forwards calls to the Web App (see "gateway mode" in `../Web Dev/README.md`).

## Layout

```
web_app/
  Dockerfile, .dockerignore     container build
  config/settings.json          ports, Core URL, teams, dev users, who may record decisions
  contracts/webapp_api.*        Web App OpenAPI contract the server runs on (generated; don't hand-edit)
  secheck_web/
    __main__.py                 entry point: python -m secheck_web
    app.py                      spec-driven routing, auth, validation, errors
    core_client.py              Core API adapter (the ONLY place with Core field names and paths)
    handlers/                   one function per operationId, plus a few extension routes
    audit.py                    wording of audit tickets (intake, edit, decision)
    validation.py               JSON-schema subset validator
    web.py                      tiny HTTP server on the standard library
    config.py                   settings
    static/                     the browser app (HTML, CSS, JS; no build step)
      logo.png                  logo in the page footer + browser-tab icon (replace this file to update it)
```

## When a spec changes

1. Edit the spec in `../spec_docs/`.
2. In `../Web Dev`, run `python tools/sync_contracts.py` (needs `pip install pyyaml`). It regenerates `contracts/webapp_api.*` here, and the Core contract the mock and tests use.
3. Run the tests in `../Web Dev` (`python -m unittest`). They tell you what, if anything, needs code.

| Change in the spec | Where |
|---|---|
| Enum value, max length, pattern, required field | Nothing: validation and the UI dropdowns read the contract |
| New Web App operation | Add a function with `@operation("<operationId>")` in `secheck_web/handlers/` (until then it answers `501`) |
| Core API field or path renamed | `secheck_web/core_client.py` |
