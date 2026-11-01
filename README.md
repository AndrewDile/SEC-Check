# SEC-Check

Incident tracking for SEC cybersecurity disclosure (Form 8-K Item 1.05).

```
api/                    Core API (Express + TypeScript)
web_app/                Web app (Python, standard library only)
ingestion_worker/       Polls CISA KEV and SEC EDGAR for incidents (Python)
notification_service/   Notifies teams of new incidents (Python)
tester/                 Cross-team tester (Python)
db/migrations/          MySQL schema, applied when the database volume is created
docs/                   Developer docs (MkDocs), served at /docs/
```

Developer docs for everything here, including interfaces and known limitations, are at
http://localhost/docs/ once the stack is up, or run `./docs.sh` to preview them.

## Setup

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and Node 24.

```bash
git clone git@github.com:AndrewDile/SEC-Check.git
cd SEC-Check
docker compose up --build
```

Everything public goes through [Caddy](https://caddyserver.com/) on port 80, one path per
container (see `Caddyfile`):

```
http://localhost/          web app
http://localhost/system/   Core API (the "system" for cross-team testing), e.g. /system/health
http://localhost/tester/   tester
http://localhost/logs/     live logs for every container (login: LOGS_USER and password in .env)
http://localhost/docs/     developer docs: services, interfaces, data model, known limitations
```

The log viewer needs `LOGS_USER` and `LOGS_PASSWORD_HASH` in `.env`; `.env.example` shows how to make the hash.

Working on just the API (reloads on save):

```bash
cd api && npm install && npm run dev
```

## Linting and formatting

Python services use [ruff](https://docs.astral.sh/ruff/) (needs [uv](https://docs.astral.sh/uv/)); the API uses
[Biome](https://biomejs.dev/) and `tsc`. CI runs both checks on every PR.

```bash
(cd api && npm install)   # once
./lint.sh                 # lint everything
./lint.sh --fix           # fix lint issues that can be fixed automatically
./format.sh --check       # check formatting
./format.sh               # format everything
```

## Tests

`./test.sh` starts the stack (without the ingestion worker and notifier), then runs the tester's own tests,
the API and database tests (`api/test/`), and the 54-test cross-team suite against our system. It **wipes the
local database**. CI runs it after lint and format pass, and deploys `main` only if it passes.

## Adding a container

Put your part in its own folder with a `Dockerfile`, then add a service to `docker-compose.yml`.
Containers reach each other by service name, e.g. `http://api:3001`.
