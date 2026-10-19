# Getting started

## Run the whole stack

You need Docker with the Compose plugin. To work on the API or run the checks, you also need
Node 24 and [uv](https://docs.astral.sh/uv/).

```bash
git clone git@github.com:AndrewDile/SEC-Check.git
cd SEC-Check
cp .env.example .env      # then change the passwords and tokens
docker compose up --build
```

Everything is behind Caddy on port 80:

| URL | What |
|---|---|
| `http://localhost/` | Web app (redirects to `/app/`) |
| `http://localhost/system/` | Core API, e.g. `/system/health`. "System" is the cross-team testing name for it |
| `http://localhost/tester/` | Tester, e.g. `POST /tester/test/setup` |
| `http://localhost/logs/` | Log viewer. Needs `LOGS_USER` and `LOGS_PASSWORD_HASH` in `.env` |
| `http://localhost/docs/` | These docs |

The database also listens on `127.0.0.1:3306`, for local tools only.

`db/migrations/*.sql` runs only when the `db-data` volume is first created. To pick up a schema
change locally, run `docker compose down -v`. That **deletes all data**.

## `.env`

Compose reads `.env` from the repo root. The deploy never copies it, so the server keeps its own
copy at `~/sec-check/.env`.

| Variable | Used by | Meaning |
|---|---|---|
| `DB_ROOT_PASSWORD`, `DB_USER`, `DB_PASSWORD` | db, api | MySQL credentials |
| `INGEST_CORE_API_TOKEN` | api, ingestion worker | Bearer token the worker sends to the Core API |
| `INGEST_INBOUND_TOKEN` | api, ingestion worker | Bearer token the Core API sends to the worker |
| `NOTIF_CORE_API_TOKEN` | api, notification service | Bearer token the notifier sends to the Core API |
| `NOTIF_INBOUND_TOKEN` | api, notification service | Bearer token the Core API sends to the notifier |
| `SEC_USER_AGENT` | ingestion worker | Who is calling, e.g. `"Team Name you@example.com"`. The SEC blocks requests without one |
| `WEB_APP_URL` | api | Public address of the web app, used for claim links in notifications. Default `http://localhost` |
| `LOGS_USER`, `LOGS_PASSWORD_HASH` | caddy | Login for `/logs/`. Set both or neither (see [Operations](operations.md#log-viewer)) |
| `LOG_LEVEL` | Python services run outside Docker | `INFO` by default |
| `DEPLOY_HOST`, `DEPLOY_KEY` | `deploy.sh` | SSH target and key, when you deploy from your machine |

`.env.example` also has `CORE_API_URL`, `CORE_API_TOKEN`, `INBOUND_TOKEN` and a few worker
settings. Those are for running the ingestion worker or notification service outside Docker;
Compose sets them itself.

## Work on one service

| Service | Command | Notes |
|---|---|---|
| Core API | `cd api && npm install && npm run dev` | Reloads on save. Needs `DB_*` pointing at a MySQL, e.g. `docker compose up db` |
| Web app | `cd web_app && python -m secheck_web --core-url http://127.0.0.1:3001` | Standard library only. `--port`, `--host`, `--quiet` |
| Ingestion worker | `uv run python -m ingestion_worker [--once] [--source cisa_kev]` | Reads only environment variables, so export `.env` first: `set -a; . ./.env; set +a` |
| Notification service | `uv run python -m notification_service` | The same |
| Tester | `cd tester && python -m secheck_tester --port 8100` | `python dev/mock_system.py --port 8200` gives it a fake system to test |

## Checks

| Command | What it does |
|---|---|
| `./lint.sh` | ruff on the Python services; `tsc` and Biome on the API. `--fix` fixes what it can |
| `./format.sh` | Formats everything. `--check` only reports |
| `./test.sh` | Starts the stack and runs every test suite. **Wipes the local database.** See [Testing](testing.md) |
| `./docs.sh` | Serves these docs at `http://127.0.0.1:8008`, reloading on save. `./docs.sh build` checks links the way CI does |

Run `(cd api && npm install)` once before the first lint or format.

The first formatting commit is listed in `.git-blame-ignore-revs`. Run
`git config blame.ignoreRevsFile .git-blame-ignore-revs` so `git blame` skips it.

## Adding a container

1. Put the service in its own folder with a `Dockerfile`.
2. Add it to `docker-compose.yml`. Containers reach each other by service name, e.g.
   `http://api:3001`.
3. If it should be public, give it a path in `Caddyfile`, and don't publish a port.
4. Add a page under `docs/pages/services/`, and list it in `docs/mkdocs.yml`.
